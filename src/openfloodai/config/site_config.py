"""Site and camera configuration loading for local POC runs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

InputType = Literal["local_video", "camera_stream"]

REQUIRED_FIELDS = {
    "site_id",
    "camera_id",
    "site_name",
    "input_type",
}
OPTIONAL_FIELDS = {
    "public_location",
    "reference_region",
    "privacy_notes",
    "normal_waterline_guides",
}
ALLOWED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

ALLOWED_GUIDE_STATUSES = {"draft", "confirmed", "invalid"}
ALLOWED_INVALIDATION_REASONS = {
    "camera_moved",
    "view_changed",
    "bank_changed",
    "visibility_unreliable",
    "other",
}


class SiteConfigError(ValueError):
    """Raised when a site/camera config file is invalid."""


@dataclass(frozen=True)
class ReferenceRegion:
    """A broad image region to watch, written as percentages of the full frame."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class WaterlinePoint:
    """One point along a normal-waterline guide, as a percentage of the frame."""

    x: float
    y: float


@dataclass(frozen=True)
class NormalWaterlineGuide:
    """A human-traced polyline marking the normal water edge/bank boundary.

    Tracks only the current state (like ``reference_region`` itself) rather
    than a history of past confirmations or invalidations. Manual drawing
    tools in this project are limited to this and the watched area — the
    machine draws only current observations, never a suggested baseline.
    """

    id: str
    label: str
    points: tuple[WaterlinePoint, ...]
    video_id: str
    video_time_seconds: float
    site_id: str
    camera_id: str
    status: str  # "draft" | "confirmed" | "invalid"
    normal_condition: bool
    notes: str
    confirmed_at: str | None
    invalidated_at: str | None
    invalidation_reason: str | None
    # A guide's source is either a video (video_id + video_time_seconds) or a
    # saved image-sequence still (image_sequence_id + image_filename) —
    # exactly one, never both, never neither. See _load_normal_waterline_guide.
    image_sequence_id: str = ""
    image_filename: str = ""


@dataclass(frozen=True)
class SiteCameraConfig:
    """Safe public config for one local POC site and camera."""

    site_id: str
    camera_id: str
    site_name: str
    public_location: str | None
    input_type: InputType
    reference_region: ReferenceRegion | None = None
    privacy_notes: str | None = None
    normal_waterline_guides: tuple[NormalWaterlineGuide, ...] = ()


def load_site_config(config_path: Path) -> SiteCameraConfig:
    """Load and validate a safe site/camera config from a JSON file."""

    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SiteConfigError(f"Site config file was not found: {config_path}") from error
    except json.JSONDecodeError as error:
        raise SiteConfigError(f"Site config file is not valid JSON: {config_path}") from error

    if not isinstance(raw_config, dict):
        raise SiteConfigError("Site config must be a JSON object")

    config = dict[str, Any](raw_config)
    _validate_fields(config)

    input_type = _load_input_type(config["input_type"])
    reference_region = _load_reference_region(config.get("reference_region"))

    return SiteCameraConfig(
        site_id=_load_required_text(config, "site_id"),
        camera_id=_load_required_text(config, "camera_id"),
        site_name=_load_required_text(config, "site_name"),
        public_location=_load_optional_text(config.get("public_location"), "public_location"),
        input_type=input_type,
        reference_region=reference_region,
        privacy_notes=_load_optional_text(config.get("privacy_notes"), "privacy_notes"),
        normal_waterline_guides=_load_normal_waterline_guides(
            config.get("normal_waterline_guides"),
            parent_region=reference_region,
        ),
    )


def write_reference_region(config_path: Path, value: Mapping[str, object]) -> None:
    """Update a site's watched region while preserving its other config fields."""

    reference_region = _load_reference_region(dict(value))
    if reference_region is None:
        raise SiteConfigError("Reference region cannot be empty")

    raw_config = _read_config_json(config_path)
    raw_config["reference_region"] = _region_to_dict(reference_region)
    config_path.write_text(json.dumps(raw_config, indent=2) + "\n", encoding="utf-8")


def write_normal_waterline_guide(
    config_path: Path, payload: Mapping[str, object]
) -> NormalWaterlineGuide:
    """Save a draft or confirmed normal-waterline guide, upserted by ``id``.

    Re-reads the config file so the guide can be validated against the
    site's *current* ``reference_region``, and rewrites only the
    ``normal_waterline_guides`` key. ``confirmed_at`` is always server-set,
    never taken from ``payload``. A guide whose ``id`` matches an existing
    saved guide replaces it in place; otherwise it is appended.
    """

    raw_config = _read_config_json(config_path)
    parent_region = _load_reference_region(raw_config.get("reference_region"))
    if parent_region is None:
        raise SiteConfigError("Set the site's watched area before saving a normal waterline guide")

    status = payload.get("status")
    if status not in {"draft", "confirmed"}:
        raise SiteConfigError(
            "Normal waterline guide field 'status' must be 'draft' or 'confirmed'"
        )

    candidate = dict(payload)
    candidate["confirmed_at"] = _now_iso() if status == "confirmed" else None
    candidate["invalidated_at"] = None
    candidate["invalidation_reason"] = None

    guide = _load_normal_waterline_guide(candidate, parent_region=parent_region)

    existing_raw = raw_config.get("normal_waterline_guides")
    existing_guides = list(existing_raw) if isinstance(existing_raw, list) else []
    updated_guides = [
        entry
        for entry in existing_guides
        if not (isinstance(entry, dict) and entry.get("id") == guide.id)
    ]
    updated_guides.append(_normal_waterline_guide_to_dict(guide))

    raw_config["normal_waterline_guides"] = updated_guides
    config_path.write_text(json.dumps(raw_config, indent=2) + "\n", encoding="utf-8")
    return guide


def write_normal_waterline_guides(
    config_path: Path, payloads: Sequence[Mapping[str, object]]
) -> tuple[NormalWaterlineGuide, ...]:
    """Save many normal-waterline guides in a single write, each upserted by id.

    Unlike ``write_normal_waterline_guide``, each payload may use any status
    (``draft``/``confirmed``/``invalid``) and an ``invalid`` payload must
    carry its own ``invalidation_reason`` directly — this bulk save is how
    the multi-line guide editor persists every line (new, edited, or
    invalidated) in one request, so no line's status is set from outside
    the payload the caller sent for it.
    """

    raw_config = _read_config_json(config_path)
    parent_region = _load_reference_region(raw_config.get("reference_region"))
    if parent_region is None:
        raise SiteConfigError("Set the site's watched area before saving a normal waterline guide")

    existing_raw = raw_config.get("normal_waterline_guides")
    existing_guides_raw = [
        entry
        for entry in (existing_raw if isinstance(existing_raw, list) else [])
        if isinstance(entry, dict)
    ]
    existing_confirmed_at_by_id = {
        entry["id"]: entry.get("confirmed_at")
        for entry in existing_guides_raw
        if isinstance(entry.get("id"), str)
    }

    guides: list[NormalWaterlineGuide] = []
    for payload in payloads:
        status = payload.get("status")
        if status not in ALLOWED_GUIDE_STATUSES:
            joined = ", ".join(sorted(ALLOWED_GUIDE_STATUSES))
            raise SiteConfigError(f"Normal waterline guide field 'status' must be one of: {joined}")

        candidate = dict(payload)
        guide_id = candidate.get("id")
        existing_confirmed_at = (
            existing_confirmed_at_by_id.get(guide_id) if isinstance(guide_id, str) else None
        )
        _stamp_guide_status_fields(candidate, status, existing_confirmed_at=existing_confirmed_at)
        guides.append(_load_normal_waterline_guide(candidate, parent_region=parent_region))

    seen_ids = [guide.id for guide in guides]
    if len(set(seen_ids)) != len(seen_ids):
        raise SiteConfigError("Duplicate normal waterline guide id in request")

    saved_ids = set(seen_ids)
    remaining = [entry for entry in existing_guides_raw if entry.get("id") not in saved_ids]
    raw_config["normal_waterline_guides"] = remaining + [
        _normal_waterline_guide_to_dict(guide) for guide in guides
    ]
    config_path.write_text(json.dumps(raw_config, indent=2) + "\n", encoding="utf-8")
    return tuple(guides)


def delete_normal_waterline_guide(config_path: Path, guide_id: str) -> None:
    """Permanently remove one normal-waterline guide from a site's config.

    Unlike ``invalidate_normal_waterline_guide``, this leaves no trace of
    the guide — for a line the multi-line editor is told to delete outright,
    not one that stays on record as no longer trustworthy.
    """

    raw_config = _read_config_json(config_path)
    existing_raw = raw_config.get("normal_waterline_guides")
    existing_guides = list(existing_raw) if isinstance(existing_raw, list) else []
    remaining = [
        entry
        for entry in existing_guides
        if not (isinstance(entry, dict) and entry.get("id") == guide_id)
    ]
    if len(remaining) == len(existing_guides):
        raise SiteConfigError("There is no normal waterline guide with that id to delete")

    raw_config["normal_waterline_guides"] = remaining
    config_path.write_text(json.dumps(raw_config, indent=2) + "\n", encoding="utf-8")


def invalidate_normal_waterline_guide(
    config_path: Path, guide_id: str, reason: str, notes: str | None = None
) -> NormalWaterlineGuide:
    """Mark one of a site's normal-waterline guides as invalid, by id."""

    if reason not in ALLOWED_INVALIDATION_REASONS:
        joined = ", ".join(sorted(ALLOWED_INVALIDATION_REASONS))
        raise SiteConfigError(f"Invalidation reason must be one of: {joined}")

    raw_config = _read_config_json(config_path)
    parent_region = _load_reference_region(raw_config.get("reference_region"))
    guides = _load_normal_waterline_guides(
        raw_config.get("normal_waterline_guides"), parent_region=parent_region
    )
    existing = next((guide for guide in guides if guide.id == guide_id), None)
    if existing is None:
        raise SiteConfigError("There is no normal waterline guide with that id to invalidate")

    invalidated = NormalWaterlineGuide(
        id=existing.id,
        label=existing.label,
        points=existing.points,
        video_id=existing.video_id,
        video_time_seconds=existing.video_time_seconds,
        site_id=existing.site_id,
        camera_id=existing.camera_id,
        status="invalid",
        normal_condition=existing.normal_condition,
        notes=notes.strip() if isinstance(notes, str) and notes.strip() else existing.notes,
        confirmed_at=existing.confirmed_at,
        invalidated_at=_now_iso(),
        invalidation_reason=reason,
    )

    updated_guides = [
        _normal_waterline_guide_to_dict(invalidated if guide.id == guide_id else guide)
        for guide in guides
    ]
    raw_config["normal_waterline_guides"] = updated_guides
    config_path.write_text(json.dumps(raw_config, indent=2) + "\n", encoding="utf-8")
    return invalidated


def _read_config_json(config_path: Path) -> dict[str, Any]:
    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SiteConfigError(f"Site config file was not found: {config_path}") from error
    except json.JSONDecodeError as error:
        raise SiteConfigError(f"Site config file is not valid JSON: {config_path}") from error

    if not isinstance(raw_config, dict):
        raise SiteConfigError("Site config must be a JSON object")
    return dict[str, Any](raw_config)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _stamp_guide_status_fields(
    candidate: dict[str, Any], status: str, *, existing_confirmed_at: object
) -> None:
    """Set server-controlled timestamp/reason fields for a guide payload in place.

    ``confirmed_at`` is preserved across a transition to ``invalid`` (the
    guide was confirmed once; invalidating it does not erase that history),
    but is never taken from the caller directly.
    """

    if status == "confirmed":
        candidate["confirmed_at"] = _now_iso()
        candidate["invalidated_at"] = None
        candidate["invalidation_reason"] = None
    elif status == "invalid":
        candidate["confirmed_at"] = (
            existing_confirmed_at if isinstance(existing_confirmed_at, str) else None
        )
        candidate["invalidated_at"] = _now_iso()
    else:
        candidate["confirmed_at"] = None
        candidate["invalidated_at"] = None
        candidate["invalidation_reason"] = None


def _region_to_dict(region: ReferenceRegion) -> dict[str, float]:
    return {"x": region.x, "y": region.y, "width": region.width, "height": region.height}


def _point_to_dict(point: WaterlinePoint) -> dict[str, float]:
    return {"x": point.x, "y": point.y}


def _normal_waterline_guide_to_dict(value: NormalWaterlineGuide) -> dict[str, Any]:
    return {
        "id": value.id,
        "label": value.label,
        "points": [_point_to_dict(point) for point in value.points],
        "video_id": value.video_id,
        "video_time_seconds": value.video_time_seconds,
        "site_id": value.site_id,
        "camera_id": value.camera_id,
        "status": value.status,
        "normal_condition": value.normal_condition,
        "notes": value.notes,
        "confirmed_at": value.confirmed_at,
        "invalidated_at": value.invalidated_at,
        "invalidation_reason": value.invalidation_reason,
        "image_sequence_id": value.image_sequence_id,
        "image_filename": value.image_filename,
    }


def _validate_fields(config: dict[str, Any]) -> None:
    missing_fields = sorted(REQUIRED_FIELDS - config.keys())
    if missing_fields:
        joined_fields = ", ".join(missing_fields)
        raise SiteConfigError(f"Site config is missing required field(s): {joined_fields}")

    extra_fields = sorted(config.keys() - ALLOWED_FIELDS)
    if extra_fields:
        joined_fields = ", ".join(extra_fields)
        raise SiteConfigError(f"Site config has unsupported field(s): {joined_fields}")


def _load_required_text(config: dict[str, Any], field_name: str) -> str:
    value = config[field_name]
    if not isinstance(value, str) or not value.strip():
        raise SiteConfigError(f"Site config field '{field_name}' must be a non-empty string")
    return value.strip()


def _load_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SiteConfigError(f"Site config field '{field_name}' must be a non-empty string")
    return value.strip()


def _load_input_type(value: object) -> InputType:
    if value not in {"local_video", "camera_stream"}:
        raise SiteConfigError(
            "Site config field 'input_type' must be 'local_video' or 'camera_stream'"
        )
    return value


def _load_reference_region(value: object) -> ReferenceRegion | None:
    if value is None:
        return None

    if not isinstance(value, dict):
        raise SiteConfigError("Site config field 'reference_region' must be a JSON object")

    region = dict[str, Any](value)
    expected_fields = {"x", "y", "width", "height"}
    missing_fields = sorted(expected_fields - region.keys())
    if missing_fields:
        joined_fields = ", ".join(missing_fields)
        raise SiteConfigError(f"Reference region is missing required field(s): {joined_fields}")

    extra_fields = sorted(region.keys() - expected_fields)
    if extra_fields:
        joined_fields = ", ".join(extra_fields)
        raise SiteConfigError(f"Reference region has unsupported field(s): {joined_fields}")

    x = _load_region_number(region["x"], "x")
    y = _load_region_number(region["y"], "y")
    width = _load_region_number(region["width"], "width")
    height = _load_region_number(region["height"], "height")

    if x < 0 or y < 0:
        raise SiteConfigError("Reference region x and y must be 0 or greater")
    if width <= 0 or height <= 0:
        raise SiteConfigError("Reference region width and height must be greater than 0")
    if x + width > 100 or y + height > 100:
        raise SiteConfigError("Reference region must fit inside the 0-100 image area")

    return ReferenceRegion(x=x, y=y, width=width, height=height)


def _load_region_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SiteConfigError(f"Reference region field '{field_name}' must be a number")
    return float(value)


def _load_waterline_point(value: object) -> WaterlinePoint:
    if not isinstance(value, dict):
        raise SiteConfigError("Each normal waterline guide point must be a JSON object")

    point = dict[str, Any](value)
    expected_fields = {"x", "y"}
    missing_fields = sorted(expected_fields - point.keys())
    if missing_fields:
        joined_fields = ", ".join(missing_fields)
        raise SiteConfigError(f"Waterline point is missing required field(s): {joined_fields}")

    extra_fields = sorted(point.keys() - expected_fields)
    if extra_fields:
        joined_fields = ", ".join(extra_fields)
        raise SiteConfigError(f"Waterline point has unsupported field(s): {joined_fields}")

    x = _load_region_number(point["x"], "x")
    y = _load_region_number(point["y"], "y")
    if x < 0 or x > 100 or y < 0 or y > 100:
        raise SiteConfigError("Waterline point x and y must be within the 0-100 image area")

    return WaterlinePoint(x=x, y=y)


def _point_inside_region(point: WaterlinePoint, region: ReferenceRegion) -> bool:
    return (
        region.x <= point.x <= region.x + region.width
        and region.y <= point.y <= region.y + region.height
    )


def _load_normal_waterline_guide(
    value: object, *, parent_region: ReferenceRegion | None
) -> NormalWaterlineGuide:
    if not isinstance(value, dict):
        raise SiteConfigError("Normal waterline guide must be a JSON object")

    record = dict[str, Any](value)
    required_fields = {
        "id",
        "label",
        "points",
        "video_id",
        "video_time_seconds",
        "site_id",
        "camera_id",
        "status",
        "normal_condition",
        "notes",
        "confirmed_at",
        "invalidated_at",
        "invalidation_reason",
    }
    optional_fields = {"image_sequence_id", "image_filename"}
    missing_fields = sorted(required_fields - record.keys())
    if missing_fields:
        joined_fields = ", ".join(missing_fields)
        raise SiteConfigError(
            f"Normal waterline guide is missing required field(s): {joined_fields}"
        )

    extra_fields = sorted(record.keys() - required_fields - optional_fields)
    if extra_fields:
        joined_fields = ", ".join(extra_fields)
        raise SiteConfigError(f"Normal waterline guide has unsupported field(s): {joined_fields}")

    status = record["status"]
    if status not in ALLOWED_GUIDE_STATUSES:
        joined = ", ".join(sorted(ALLOWED_GUIDE_STATUSES))
        raise SiteConfigError(f"Normal waterline guide field 'status' must be one of: {joined}")

    if parent_region is None:
        raise SiteConfigError("Normal waterline guide requires the site to have a watched area")

    points = _load_guide_points(record["points"], parent_region=parent_region)

    invalidation_reason = record["invalidation_reason"]
    if status == "invalid":
        if invalidation_reason not in ALLOWED_INVALIDATION_REASONS:
            joined = ", ".join(sorted(ALLOWED_INVALIDATION_REASONS))
            raise SiteConfigError(
                f"Normal waterline guide field 'invalidation_reason' must be one of: {joined}"
            )
    elif invalidation_reason is not None:
        raise SiteConfigError(
            "Normal waterline guide field 'invalidation_reason' must be empty unless invalid"
        )

    video_id = _load_guide_text_allow_empty(record["video_id"], "video_id")
    video_time_seconds = _load_guide_time(record["video_time_seconds"])
    image_sequence_id = _load_guide_text_allow_empty(
        record.get("image_sequence_id", ""), "image_sequence_id"
    )
    image_filename = _load_guide_text_allow_empty(
        record.get("image_filename", ""), "image_filename"
    )
    if bool(image_sequence_id) != bool(image_filename):
        raise SiteConfigError(
            "Normal waterline guide fields 'image_sequence_id' and 'image_filename' "
            "must both be set or both be empty"
        )
    has_video_source = bool(video_id)
    has_image_source = bool(image_sequence_id)
    if has_video_source == has_image_source:
        raise SiteConfigError(
            "Normal waterline guide must have exactly one source: "
            "a video (video_id) or a saved image (image_sequence_id + image_filename)"
        )

    return NormalWaterlineGuide(
        id=_load_required_text(record, "id"),
        label=_load_required_text(record, "label"),
        points=points,
        video_id=video_id,
        video_time_seconds=video_time_seconds,
        site_id=_load_required_text(record, "site_id"),
        camera_id=_load_required_text(record, "camera_id"),
        status=status,
        normal_condition=_load_guide_bool(record["normal_condition"]),
        notes=_load_guide_notes(record["notes"]),
        confirmed_at=_load_optional_text(record["confirmed_at"], "confirmed_at"),
        invalidated_at=_load_optional_text(record["invalidated_at"], "invalidated_at"),
        invalidation_reason=invalidation_reason,
        image_sequence_id=image_sequence_id,
        image_filename=image_filename,
    )


def _load_guide_points(
    value: object, *, parent_region: ReferenceRegion
) -> tuple[WaterlinePoint, ...]:
    if not isinstance(value, list):
        raise SiteConfigError("Normal waterline guide field 'points' must be a list")
    if len(value) < 2:
        raise SiteConfigError("Normal waterline guide must have at least 2 points")

    points: list[WaterlinePoint] = []
    for entry in value:
        point = _load_waterline_point(entry)
        if not _point_inside_region(point, parent_region):
            raise SiteConfigError(
                "Every normal waterline guide point must fit inside the watched area"
            )
        points.append(point)

    return tuple(points)


def _load_normal_waterline_guides(
    value: object, *, parent_region: ReferenceRegion | None
) -> tuple[NormalWaterlineGuide, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SiteConfigError("Site config field 'normal_waterline_guides' must be a list")

    guides: list[NormalWaterlineGuide] = []
    seen_ids: set[str] = set()
    for entry in value:
        guide = _load_normal_waterline_guide(entry, parent_region=parent_region)
        if guide.id in seen_ids:
            raise SiteConfigError(f"Duplicate normal waterline guide id: {guide.id}")
        seen_ids.add(guide.id)
        guides.append(guide)

    return tuple(guides)


def _load_guide_time(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SiteConfigError("Normal waterline guide field 'video_time_seconds' must be a number")
    if value < 0:
        raise SiteConfigError(
            "Normal waterline guide field 'video_time_seconds' must be 0 or greater"
        )
    return float(value)


def _load_guide_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise SiteConfigError(
            "Normal waterline guide field 'normal_condition' must be true or false"
        )
    return value


def _load_guide_notes(value: object) -> str:
    if not isinstance(value, str):
        raise SiteConfigError("Normal waterline guide field 'notes' must be a string")
    return value.strip()


def _load_guide_text_allow_empty(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise SiteConfigError(f"Normal waterline guide field '{field_name}' must be a string")
    return value.strip()

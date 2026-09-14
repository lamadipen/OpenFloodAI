"""Site and camera configuration loading for local POC runs."""

from __future__ import annotations

import json
from collections.abc import Mapping
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
    "confirmed_reference",
}
ALLOWED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

ALLOWED_CONFIRMED_REFERENCE_STATUSES = {"draft", "confirmed", "invalid"}
ALLOWED_CONFIRMED_REFERENCE_ORIGINS = {"machine_suggested", "manual"}
DEFAULT_CONFIRMED_REFERENCE_ORIGIN = "manual"
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
class ConfirmedReferenceMarker:
    """A named, stable extra reference point inside a site's watched area."""

    label: str
    region: ReferenceRegion


@dataclass(frozen=True)
class ConfirmedReference:
    """The confirmed riverbank/reference record inside a site's watched area.

    Tracks only the current state (like ``reference_region`` itself) rather
    than a history of past confirmations or invalidations.
    """

    status: str  # "draft" | "confirmed" | "invalid"
    origin: str  # "machine_suggested" | "manual"
    region: ReferenceRegion
    video_id: str
    video_time_seconds: float
    site_id: str
    camera_id: str
    normal_condition: bool
    notes: str
    markers: tuple[ConfirmedReferenceMarker, ...]
    confirmed_at: str | None
    invalidated_at: str | None
    invalidation_reason: str | None


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
    confirmed_reference: ConfirmedReference | None = None


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

    return SiteCameraConfig(
        site_id=_load_required_text(config, "site_id"),
        camera_id=_load_required_text(config, "camera_id"),
        site_name=_load_required_text(config, "site_name"),
        public_location=_load_optional_text(config.get("public_location"), "public_location"),
        input_type=input_type,
        reference_region=_load_reference_region(config.get("reference_region")),
        privacy_notes=_load_optional_text(config.get("privacy_notes"), "privacy_notes"),
        confirmed_reference=_load_confirmed_reference(
            config.get("confirmed_reference"),
            parent_region=_load_reference_region(config.get("reference_region")),
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


def write_confirmed_reference(
    config_path: Path, payload: Mapping[str, object]
) -> ConfirmedReference:
    """Save a draft or confirmed riverbank reference tied to the site's watched area.

    Re-reads the config file so the confirmed reference can be validated
    against the site's *current* ``reference_region``, and rewrites only the
    ``confirmed_reference`` key. ``confirmed_at`` is always server-set, never
    taken from ``payload``.
    """

    raw_config = _read_config_json(config_path)
    parent_region = _load_reference_region(raw_config.get("reference_region"))
    if parent_region is None:
        raise SiteConfigError("Set the site's watched area before confirming a reference")

    status = payload.get("status")
    if status not in {"draft", "confirmed"}:
        raise SiteConfigError("Confirmed reference field 'status' must be 'draft' or 'confirmed'")

    candidate = dict(payload)
    candidate["confirmed_at"] = _now_iso() if status == "confirmed" else None
    candidate["invalidated_at"] = None
    candidate["invalidation_reason"] = None

    confirmed_reference = _load_confirmed_reference(candidate, parent_region=parent_region)
    if confirmed_reference is None:
        raise SiteConfigError("Confirmed reference cannot be empty")

    raw_config["confirmed_reference"] = _confirmed_reference_to_dict(confirmed_reference)
    config_path.write_text(json.dumps(raw_config, indent=2) + "\n", encoding="utf-8")
    return confirmed_reference


def invalidate_confirmed_reference(
    config_path: Path, reason: str, notes: str | None = None
) -> ConfirmedReference:
    """Mark a site's existing confirmed reference as invalid, keeping its provenance."""

    if reason not in ALLOWED_INVALIDATION_REASONS:
        joined = ", ".join(sorted(ALLOWED_INVALIDATION_REASONS))
        raise SiteConfigError(f"Invalidation reason must be one of: {joined}")

    raw_config = _read_config_json(config_path)
    parent_region = _load_reference_region(raw_config.get("reference_region"))
    existing = _load_confirmed_reference(
        raw_config.get("confirmed_reference"), parent_region=parent_region
    )
    if existing is None:
        raise SiteConfigError("There is no confirmed reference to invalidate yet")

    invalidated = ConfirmedReference(
        status="invalid",
        origin=existing.origin,
        region=existing.region,
        video_id=existing.video_id,
        video_time_seconds=existing.video_time_seconds,
        site_id=existing.site_id,
        camera_id=existing.camera_id,
        normal_condition=existing.normal_condition,
        notes=notes.strip() if isinstance(notes, str) and notes.strip() else existing.notes,
        markers=existing.markers,
        confirmed_at=existing.confirmed_at,
        invalidated_at=_now_iso(),
        invalidation_reason=reason,
    )

    raw_config["confirmed_reference"] = _confirmed_reference_to_dict(invalidated)
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


def _region_to_dict(region: ReferenceRegion) -> dict[str, float]:
    return {"x": region.x, "y": region.y, "width": region.width, "height": region.height}


def _confirmed_reference_to_dict(value: ConfirmedReference) -> dict[str, Any]:
    return {
        "status": value.status,
        "origin": value.origin,
        "region": _region_to_dict(value.region),
        "video_id": value.video_id,
        "video_time_seconds": value.video_time_seconds,
        "site_id": value.site_id,
        "camera_id": value.camera_id,
        "normal_condition": value.normal_condition,
        "notes": value.notes,
        "markers": [
            {"label": marker.label, "region": _region_to_dict(marker.region)}
            for marker in value.markers
        ],
        "confirmed_at": value.confirmed_at,
        "invalidated_at": value.invalidated_at,
        "invalidation_reason": value.invalidation_reason,
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


def _region_fits_inside(region: ReferenceRegion, parent: ReferenceRegion) -> bool:
    return (
        region.x >= parent.x
        and region.y >= parent.y
        and region.x + region.width <= parent.x + parent.width
        and region.y + region.height <= parent.y + parent.height
    )


def _load_confirmed_reference(
    value: object, *, parent_region: ReferenceRegion | None
) -> ConfirmedReference | None:
    if value is None:
        return None

    if not isinstance(value, dict):
        raise SiteConfigError("Confirmed reference must be a JSON object")

    record = dict[str, Any](value)
    if "origin" not in record:
        # Records saved before OF-086 have no origin — machine suggestions
        # did not exist yet, so treat them as manually drawn.
        record = {**record, "origin": DEFAULT_CONFIRMED_REFERENCE_ORIGIN}
    expected_fields = {
        "status",
        "origin",
        "region",
        "video_id",
        "video_time_seconds",
        "site_id",
        "camera_id",
        "normal_condition",
        "notes",
        "markers",
        "confirmed_at",
        "invalidated_at",
        "invalidation_reason",
    }
    missing_fields = sorted(expected_fields - record.keys())
    if missing_fields:
        joined_fields = ", ".join(missing_fields)
        raise SiteConfigError(f"Confirmed reference is missing required field(s): {joined_fields}")

    extra_fields = sorted(record.keys() - expected_fields)
    if extra_fields:
        joined_fields = ", ".join(extra_fields)
        raise SiteConfigError(f"Confirmed reference has unsupported field(s): {joined_fields}")

    status = record["status"]
    if status not in ALLOWED_CONFIRMED_REFERENCE_STATUSES:
        joined = ", ".join(sorted(ALLOWED_CONFIRMED_REFERENCE_STATUSES))
        raise SiteConfigError(f"Confirmed reference field 'status' must be one of: {joined}")

    origin = record["origin"]
    if origin not in ALLOWED_CONFIRMED_REFERENCE_ORIGINS:
        joined = ", ".join(sorted(ALLOWED_CONFIRMED_REFERENCE_ORIGINS))
        raise SiteConfigError(f"Confirmed reference field 'origin' must be one of: {joined}")

    if parent_region is None:
        raise SiteConfigError("Confirmed reference requires the site to have a watched area")

    region = _load_reference_region(record["region"])
    if region is None:
        raise SiteConfigError("Confirmed reference field 'region' cannot be empty")
    if not _region_fits_inside(region, parent_region):
        raise SiteConfigError("Confirmed reference must fit inside the site's watched area")

    markers = _load_confirmed_reference_markers(record["markers"], parent_region=parent_region)

    invalidation_reason = record["invalidation_reason"]
    if status == "invalid":
        if invalidation_reason not in ALLOWED_INVALIDATION_REASONS:
            joined = ", ".join(sorted(ALLOWED_INVALIDATION_REASONS))
            raise SiteConfigError(
                f"Confirmed reference field 'invalidation_reason' must be one of: {joined}"
            )
    elif invalidation_reason is not None:
        raise SiteConfigError(
            "Confirmed reference field 'invalidation_reason' must be empty unless invalid"
        )

    return ConfirmedReference(
        status=status,
        origin=origin,
        region=region,
        video_id=_load_required_text(record, "video_id"),
        video_time_seconds=_load_confirmed_reference_time(record["video_time_seconds"]),
        site_id=_load_required_text(record, "site_id"),
        camera_id=_load_required_text(record, "camera_id"),
        normal_condition=_load_confirmed_reference_bool(record["normal_condition"]),
        notes=_load_confirmed_reference_notes(record["notes"]),
        markers=markers,
        confirmed_at=_load_optional_text(record["confirmed_at"], "confirmed_at"),
        invalidated_at=_load_optional_text(record["invalidated_at"], "invalidated_at"),
        invalidation_reason=invalidation_reason,
    )


def _load_confirmed_reference_markers(
    value: object, *, parent_region: ReferenceRegion
) -> tuple[ConfirmedReferenceMarker, ...]:
    if not isinstance(value, list):
        raise SiteConfigError("Confirmed reference field 'markers' must be a list")

    markers: list[ConfirmedReferenceMarker] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise SiteConfigError("Each confirmed reference marker must be a JSON object")

        marker = dict[str, Any](entry)
        expected_fields = {"label", "region"}
        missing_fields = sorted(expected_fields - marker.keys())
        if missing_fields:
            joined_fields = ", ".join(missing_fields)
            raise SiteConfigError(f"Marker is missing required field(s): {joined_fields}")
        extra_fields = sorted(marker.keys() - expected_fields)
        if extra_fields:
            joined_fields = ", ".join(extra_fields)
            raise SiteConfigError(f"Marker has unsupported field(s): {joined_fields}")

        label = _load_required_text(marker, "label")
        region = _load_reference_region(marker["region"])
        if region is None:
            raise SiteConfigError("Marker field 'region' cannot be empty")
        if not _region_fits_inside(region, parent_region):
            raise SiteConfigError(f"Marker '{label}' must fit inside the site's watched area")

        markers.append(ConfirmedReferenceMarker(label=label, region=region))

    return tuple(markers)


def _load_confirmed_reference_time(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SiteConfigError("Confirmed reference field 'video_time_seconds' must be a number")
    if value < 0:
        raise SiteConfigError("Confirmed reference field 'video_time_seconds' must be 0 or greater")
    return float(value)


def _load_confirmed_reference_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise SiteConfigError("Confirmed reference field 'normal_condition' must be true or false")
    return value


def _load_confirmed_reference_notes(value: object) -> str:
    if not isinstance(value, str):
        raise SiteConfigError("Confirmed reference field 'notes' must be a string")
    return value.strip()

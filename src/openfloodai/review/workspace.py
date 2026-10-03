"""Saved evidence and human review for the separate review workspace.

Machine records and input snapshots are read-only. Video observations use the
existing label writer. Image observations use the same vocabulary, with an
explicit pair identity instead of invented video timestamps.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any

from openfloodai.contracts import read_jsonl_records, write_jsonl_record
from openfloodai.ingestion.river_images import resolve_sequence_image
from openfloodai.review.dataset_groups import (
    assign_dataset_group,
    dataset_group_for_date,
    list_dataset_group_assignments,
)
from openfloodai.review.dataset_manifest import (
    ALLOWED_MANIFEST_SPLITS,
    load_manifest_records,
)
from openfloodai.review.human_labels import (
    ALLOWED_CONFIDENCE_LEVELS,
    ALLOWED_TRISTATE_VALUES,
    ALLOWED_VISIBILITY_CONDITIONS,
    create_human_label_record,
    load_human_label_records,
    normalize_human_label,
)
from openfloodai.review.label_comparison import compare_label_records
from openfloodai.validation.image_sequence_runner import (
    legacy_gauge_series,
    read_run_gauge_evidence,
)

_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_lock = RLock()

# The reviewed-observation contract (docs: Water-Signal data collection plan).
# schema_version 0 = a pre-existing record with none of these fields; 1 = the
# fields below are present. normalize_observation() fills 0 -> 1 on read so
# historical records stay valid without ever being rewritten on disk.
OBSERVATION_SCHEMA_VERSION = 2
ALLOWED_EVENT_VALIDITY = {"real", "not_real", "uncertain", "not_reviewed"}
ALLOWED_CROSSING_REVIEWS = {"change", "no_change", "unclear"}
ALLOWED_OVERLAY_REVIEWS = {"accepted", "rejected", "not_reviewed"}
ALLOWED_PILOT_CONDITIONS = {
    "muddy_water",
    "glare",
    "shadows",
    "vegetation",
    "snow",
    "low_light",
}
_CHANGE_PRESENCE_BY_HUMAN_LABEL = {
    "water_level_rising": "change",
    "water_level_falling": "change",
    "no_water_level_change": "no_change",
    "cannot_judge_water_level": "cannot_judge",
    "camera_video_problem": "cannot_judge",
}
_UNASSIGNED_DATASET_GROUP = "unassigned"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=64)
def _cached_hash(path: Path, identity: tuple[int, int, int, int]) -> str:
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    after = path.stat()
    if identity != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("Media changed while it was being read. Try again.")
    return digest


def _hash(path: Path) -> str:
    stat = path.stat()
    return _cached_hash(path, (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))


def run_path(site: Path, kind: str, run_id: str) -> Path:
    if kind not in {"video", "image"} or not _ID.fullmatch(run_id):
        raise ValueError("Choose a valid saved run.")
    root = (site / "outputs" / ("runs" if kind == "video" else "image-sequence-runs")).resolve()
    path = (root / run_id).resolve()
    if path.parent != root or not path.is_dir() or not path.is_relative_to(site.resolve()):
        raise ValueError("Saved run not found.")
    return path


def _inside(root: Path, *parts: str) -> Path:
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Evidence must stay inside its site or run.")
    return path


def catalogue(site: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for kind, folder, summary_file in (
        ("video", "runs", "run-metadata.json"),
        ("image", "image-sequence-runs", "run-summary.json"),
    ):
        for candidate in sorted((site / "outputs" / folder).glob("*"), reverse=True):
            if not candidate.is_dir():
                continue
            try:
                run = run_path(site, kind, candidate.name)
                summary = _json(run / summary_file)
                if kind == "video":
                    media = [p.stem for p in sorted((run / "records").glob("*.jsonl"))]
                else:
                    media = [str(summary["sequence_id"])]
                entries.extend(
                    {
                        "kind": kind,
                        "run_id": run.name,
                        "media_id": name,
                        "created_at": summary.get("created_at", run.name),
                    }
                    for name in media
                )
            except (OSError, ValueError, KeyError):
                continue
    return entries


def _finite(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _key(record: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:24]


def _observation_id(*, kind: str, run_id: str, media_id: str, sample_key: str) -> str:
    """Stable identity for one reviewable sample -- unchanged across re-reviews.

    A new review of the same sample gets a new revision (see
    _next_label_revision), not a new identity: this is what "duplicate
    reviews of the same observation" and "latest revision wins" resolve
    against.
    """

    return _key({"kind": kind, "run_id": run_id, "media_id": media_id, "sample_key": sample_key})


def _change_presence_from_human_label(human_label: object) -> str:
    return _CHANGE_PRESENCE_BY_HUMAN_LABEL.get(str(human_label), "cannot_judge")


def _next_label_revision(existing_reviews: list[dict[str, Any]], observation_id: str) -> int:
    prior = [r for r in existing_reviews if r.get("observation_id") == observation_id]
    return len(prior) + 1


def _dataset_group_for_observation(
    site: Path, *, kind: str, media_id: str, captured_at_utc: object
) -> str:
    """The dataset group this observation belonged to at review time.

    Stamped onto the observation itself (not just looked up later) so a
    later re-grouping can't silently change what split a past review's
    metrics were computed against -- reproducibility depends on this being
    frozen at the moment of review, not resolved dynamically forever.
    """

    if kind == "image":
        assignments = list_dataset_group_assignments(site)
        target_date = str(captured_at_utc or "")[:10]
        if not target_date:
            return _UNASSIGNED_DATASET_GROUP
        return dataset_group_for_date(assignments, target_date)
    manifest = site / "manifest.jsonl"
    if not manifest.exists():
        return _UNASSIGNED_DATASET_GROUP
    matches = [r for r in load_manifest_records(manifest) if r.get("video_id") == media_id]
    if len(matches) != 1:
        return _UNASSIGNED_DATASET_GROUP
    split = matches[0].get("split")
    return (
        str(split)
        if isinstance(split, str) and split in ALLOWED_MANIFEST_SPLITS
        else (_UNASSIGNED_DATASET_GROUP)
    )


def normalize_observation(record: dict[str, Any]) -> dict[str, Any]:
    """Fill contract fields on a possibly-historical observation record.

    Never mutates the file on disk -- a record written before this
    contract existed simply gets these fields derived on read, every time,
    so "existing records remain readable" holds without a migration step.
    """

    if record.get("schema_version") == OBSERVATION_SCHEMA_VERSION and "observation_id" in record:
        return record

    normalized = dict(record)
    kind = str(record.get("kind", ""))
    run_id = str(record.get("run_id", ""))
    media_id = str(record.get("media_id", ""))
    sample_key = str(record.get("sample_key", ""))
    normalized.setdefault(
        "observation_id",
        _observation_id(kind=kind, run_id=run_id, media_id=media_id, sample_key=sample_key),
    )
    normalized.setdefault("source", "image_pair" if kind == "image" else "video_window")
    label = record.get("label")
    human_label = label.get("human_label") if isinstance(label, dict) else None
    normalized.setdefault("change_presence", _change_presence_from_human_label(human_label))
    normalized.setdefault("event_validity", "not_reviewed")
    normalized.setdefault("dataset_group", _UNASSIGNED_DATASET_GROUP)
    normalized.setdefault("label_revision", 1)
    normalized["schema_version"] = OBSERVATION_SCHEMA_VERSION
    return normalized


def load_observations(run: Path) -> list[dict[str, Any]]:
    """Read one run's human-review observations, normalized to the current contract."""

    path = _inside(run, "human-review", "observations.jsonl")
    if not path.exists():
        return []
    return [normalize_observation(record) for record in read_jsonl_records(path)]


def _has_riverbank_overlay_samples(record: dict[str, Any]) -> bool:
    quality = record.get("quality")
    if not isinstance(quality, dict):
        return False
    samples = quality.get("samples")
    return isinstance(samples, list) and bool(samples)


def evidence(site: Path, kind: str, run_id: str, media_id: str) -> dict[str, Any]:
    run = run_path(site, kind, run_id)
    if not _ID.fullmatch(media_id):
        raise ValueError("Invalid media ID.")
    config = _json(_inside(run, "inputs-used", "site-config.snapshot.json"))
    review_file = _inside(run, "human-review", "observations.jsonl")
    reviews = read_jsonl_records(review_file) if review_file.exists() else []
    current_reviews = {
        str(r.get("sample_key")): r for r in reviews if r.get("media_id") == media_id
    }
    points: list[dict[str, Any]] = []
    if kind == "image":
        summary = _json(run / "run-summary.json")
        if summary.get("sequence_id") != media_id:
            raise ValueError("This sequence does not belong to the selected run.")
        records = read_jsonl_records(_inside(run, "image-sequence-records.jsonl"))
        evidence_path = _inside(run, "evidence-records.jsonl")
        riverbank_records = (
            [
                record
                for record in read_jsonl_records(evidence_path)
                if record.get("plugin_id") == "riverbank_crossing_v1"
            ]
            if evidence_path.is_file()
            else []
        )
        for record in records:
            key = _key(record)
            review = current_reviews.get(key)
            riverbank = next(
                (
                    evidence_record
                    for evidence_record in riverbank_records
                    if evidence_record.get("timestamp") == record.get("captured_at_utc")
                    and evidence_record.get("status") == "available"
                    and _has_riverbank_overlay_samples(evidence_record)
                ),
                None,
            )
            points.append(
                {
                    "key": key,
                    "title": record.get("local_time") or record.get("captured_at_utc"),
                    "time": record.get("captured_at_utc"),
                    "filename": record.get("filename"),
                    "score": record.get("region_change_score"),
                    "machine": record.get("result"),
                    "reason": record.get("reason"),
                    "has_media": record.get("download_status") == "downloaded",
                    "label": review.get("label") if review else None,
                    "riverbank_evidence_record_id": (
                        riverbank.get("record_id") if riverbank is not None else None
                    ),
                    "riverbank_crossing_value": (
                        riverbank.get("value") if riverbank is not None else None
                    ),
                }
            )
        for point in points:
            point["comparison"] = _image_comparison(point)
        baseline = summary.get("baseline_filename")
        groups = [asdict(a) for a in list_dataset_group_assignments(site)]
        gauge = _gage_for_run(run)
        comparisons: list[dict[str, Any]] = []
    else:
        records = read_jsonl_records(_inside(run, "records", media_id + ".jsonl"))
        labels = [
            r
            for p in sorted((site / "labels").glob("*.jsonl"))
            for r in load_human_label_records(p)
            if r.get("video_id") == media_id
        ]
        metadata = [r for r in records if r.get("record_type") == "video_frame_metadata"]
        fps = (_finite(metadata[0].get("frame_rate")) or 1.0) if metadata else 1.0
        frame_period = 1 / max(fps, 0.001)
        for record in records:
            if record.get("record_type") != "visual_signal_output":
                continue
            start = _finite(record.get("comparison_start_seconds"))
            end = _finite(record.get("comparison_end_seconds"))
            if start is None or end is None or start < 0 or end <= start:
                continue
            upper = end + frame_period
            prior = current_reviews.get(_key(record), {}).get("label")
            window = prior.get("time_window_seconds") if isinstance(prior, dict) else [start, upper]
            matching = [label for label in labels if label.get("time_window_seconds") == window]
            machine = compare_label_records(
                system_records=[record], human_labels=[], video_id=media_id
            )
            result = machine.comparisons[0].system_result
            mapped = {
                "water_change_seen": "possible_water_level_change",
                "no_clear_change": "no_water_level_change",
            }
            points.append(
                {
                    "key": _key(record),
                    "title": f"{start:g}–{end:g}s",
                    "start": start,
                    "end": end,
                    "label_end": upper,
                    "score": record.get("region_change_score"),
                    "machine": mapped.get(result, "cannot_judge_water_level"),
                    "reason": record.get("human_summary", "No saved explanation."),
                    "has_media": True,
                    "label": matching[0] if len(matching) == 1 else None,
                }
            )
        points.sort(key=lambda p: (p["end"], p["start"]))
        comparisons = [
            asdict(c)
            for c in compare_label_records(
                system_records=records, human_labels=labels, video_id=media_id
            ).comparisons
        ]
        baseline = None
        manifest = site / "manifest.jsonl"
        groups = (
            [r for r in load_manifest_records(manifest) if r.get("video_id") == media_id]
            if manifest.exists()
            else []
        )
        gauge = None
    return {
        "kind": kind,
        "run_id": run_id,
        "media_id": media_id,
        "points": points,
        "config": config,
        "baseline_filename": baseline,
        "groups": groups,
        "gauge": gauge,
        "comparisons": comparisons,
    }


def _image_comparison(point: dict[str, Any]) -> dict[str, str]:
    label = point.get("label")
    if not label:
        return {"result": "cannot_compare", "note": "No human label for comparison."}
    human = normalize_human_label(label.get("human_label"))
    machine = point["machine"]
    if machine not in {"no_water_level_change", "possible_water_level_change"} or human in {
        "cannot_judge_water_level",
        "camera_video_problem",
    }:
        return {
            "result": "cannot_compare",
            "note": "The human or machine could not judge this evidence.",
        }
    if human not in {"water_level_rising", "water_level_falling", "no_water_level_change"}:
        return {
            "result": "cannot_compare",
            "note": "No comparison rule exists for this manual label.",
        }
    agrees = (machine == "no_water_level_change" and human == "no_water_level_change") or (
        machine == "possible_water_level_change"
        and human in {"water_level_rising", "water_level_falling"}
    )
    return {
        "result": "agree" if agrees else "disagree",
        "note": (
            "Compared as change/no change only. "
            "Machine evidence does not establish direction or flood safety."
        ),
    }


_GAUGE_STATUS_MESSAGES = {
    "not_captured": (
        "No gauge evidence was saved with this run. It is not rebuilt from later data."
    ),
    "no_station_association": "No USGS gauge is associated with this camera.",
    "service_unavailable": "The USGS service was unavailable when this run's gauge data was saved.",
    "no_readings_in_range": "USGS returned no valid readings for this run's period.",
    "available": "No USGS reading was within 15 minutes of any image in this run.",
}


def _gage_for_run(run: Path) -> dict[str, Any]:
    """The gauge evidence frozen with this run, with its capture state.

    Reads only the run's own saved evidence, never the sequence's current
    gauge files, so a later download cannot change what a finished run shows.
    `status` keeps "not captured", "no station", "service unavailable", "no
    readings" and "no image matched" distinct; `rows` is empty for all of them.
    """

    evidence = read_run_gauge_evidence(run)
    rows = legacy_gauge_series(evidence)
    status = str(evidence.get("status") or "not_captured")
    association = evidence.get("association") or {}
    parameter = evidence.get("parameter") or {}
    return {
        "captured": bool(evidence.get("captured")),
        "status": status,
        "message": None if rows else _GAUGE_STATUS_MESSAGES.get(status, evidence.get("reason")),
        "parameter": parameter.get("label"),
        "unit": parameter.get("unit"),
        "relationship": association.get("relationship"),
        "relationship_note": association.get("relationship_note"),
        "rows": rows,
        "provenance": (
            "Gauge readings frozen with this run; each is the nearest valid USGS "
            "reading within 15 minutes of its image."
        ),
    }


def media_path(site: Path, kind: str, run_id: str, media_id: str, filename: str = "") -> Path:
    """Only serve original media whose bytes match the selected run's snapshot."""
    run = run_path(site, kind, run_id)
    if not _ID.fullmatch(media_id):
        raise ValueError("Invalid media ID.")
    if kind == "video":
        identity = _json(run / "inputs-used" / "video-list.snapshot.json")
        matches = [r for r in identity if r.get("video_id") == media_id]
        if len(matches) != 1:
            raise ValueError("Video identity missing or ambiguous in this run.")
        record = matches[0]
        path = _inside(site, "inputs", "videos", str(record["filename"]))
    else:
        summary = _json(run / "run-summary.json")
        if summary.get("sequence_id") != media_id:
            raise ValueError("Sequence does not belong to this run.")
        identity = _json(run / "inputs-used" / "images.snapshot.json")
        matches = [r for r in identity if r.get("filename") == filename]
        if not matches:
            raise ValueError("Image was not used by this run.")
        record = matches[0]
        path = resolve_sequence_image(site, media_id, filename)
    if _hash(path) != record.get("sha256"):
        raise ValueError(
            "Media has changed since analysis. Run analysis again before reviewing it."
        )
    return path


def _label_fields(data: dict[str, Any]) -> dict[str, Any]:
    label = normalize_human_label(data.get("human_label"))
    if not label or len(label) > 64 or not _ID.fullmatch(label):
        raise ValueError("Choose a human label or enter a valid manual label.")
    result: dict[str, Any] = {"human_label": label}
    allowed = {
        "confidence": ALLOWED_CONFIDENCE_LEVELS,
        "riverbank_visible": ALLOWED_TRISTATE_VALUES,
        "stable_marker_visible": ALLOWED_TRISTATE_VALUES,
        "water_boundary_visible": ALLOWED_TRISTATE_VALUES,
        "camera_stable": ALLOWED_TRISTATE_VALUES,
        "visibility_condition": ALLOWED_VISIBILITY_CONDITIONS,
    }
    for key, values in allowed.items():
        value = str(data.get(key) or "").strip()
        if value:
            if value not in values:
                raise ValueError(f"Invalid {key}.")
            result[key] = value
    for key in ("note", "reviewer_id"):
        if data.get(key):
            result[key] = str(data[key]).strip()
    return result


def _event_validity_field(data: dict[str, Any]) -> str:
    value = str(data.get("event_validity") or "not_reviewed").strip()
    if value not in ALLOWED_EVENT_VALIDITY:
        raise ValueError(
            f"event_validity must be one of {sorted(ALLOWED_EVENT_VALIDITY)}, got {value!r}."
        )
    return value


def _pilot_review_fields(data: dict[str, Any], point: dict[str, Any]) -> dict[str, Any]:
    evidence_record_id = point.get("riverbank_evidence_record_id")
    supplied = any(key in data for key in ("crossing_review", "overlay_review", "pilot_conditions"))
    if not supplied:
        return {}
    if not isinstance(evidence_record_id, str) or not evidence_record_id:
        raise ValueError("No available riverbank-crossing evidence exists for this sample.")

    crossing_review = str(data.get("crossing_review") or "").strip()
    if crossing_review not in ALLOWED_CROSSING_REVIEWS:
        raise ValueError(f"crossing_review must be one of {sorted(ALLOWED_CROSSING_REVIEWS)}.")
    overlay_review = str(data.get("overlay_review") or "").strip()
    if overlay_review not in ALLOWED_OVERLAY_REVIEWS:
        raise ValueError(f"overlay_review must be one of {sorted(ALLOWED_OVERLAY_REVIEWS)}.")

    raw_conditions = data.get("pilot_conditions", [])
    if not isinstance(raw_conditions, list):
        raise ValueError("pilot_conditions must be a list.")
    conditions: list[str] = []
    for raw_condition in raw_conditions:
        condition = str(raw_condition).strip()
        if condition not in ALLOWED_PILOT_CONDITIONS:
            raise ValueError(f"pilot_conditions must use {sorted(ALLOWED_PILOT_CONDITIONS)}.")
        if condition not in conditions:
            conditions.append(condition)

    fields: dict[str, Any] = {
        "evidence_record_id": evidence_record_id,
        "crossing_review": crossing_review,
        "overlay_review": overlay_review,
        "pilot_conditions": conditions,
    }
    crossing_value = _finite(point.get("riverbank_crossing_value"))
    if crossing_review == "no_change" and crossing_value is not None and crossing_value > 0:
        if data.get("camera_stable") == "no":
            fields["false_crossing_cause"] = "camera_movement"
        else:
            for condition in ("glare", "shadows", "vegetation"):
                if condition in conditions:
                    fields["false_crossing_cause"] = condition
                    break
    return fields


def save_observation(site: Path, data: dict[str, Any]) -> dict[str, Any]:
    kind, run_id, media_id = (str(data.get(k, "")) for k in ("kind", "run_id", "media_id"))
    with _lock:
        payload = evidence(site, kind, run_id, media_id)
        point = next((p for p in payload["points"] if p["key"] == data.get("sample_key")), None)
        if point is None:
            raise ValueError("Selected sample was not found in the saved machine evidence.")
        label = _label_fields(data)
        event_validity = _event_validity_field(data)
        pilot_review = _pilot_review_fields(data, point)
        run = run_path(site, kind, run_id)
        if kind == "video":
            media_path(site, kind, run_id, media_id)
            start = _finite(data.get("start_second"))
            end = _finite(data.get("end_second"))
            if start is None or end is None or not 0 <= start < end:
                raise ValueError("Enter a valid start and end second.")
            result = create_human_label_record(
                site_dir=site,
                video_id=media_id,
                start_second=start,
                end_second=end,
                overwrite=data.get("overwrite") is True,
                **label,
            )
            if not result.created or result.record is None:
                raise ValueError(result.message)
            label = dict(result.record)
        else:
            if point["has_media"]:
                media_path(site, kind, run_id, media_id, str(point["filename"]))
            media_path(site, kind, run_id, media_id, str(payload["baseline_filename"]))
        observation_id = _observation_id(
            kind=kind, run_id=run_id, media_id=media_id, sample_key=point["key"]
        )
        review_path = _inside(run, "human-review", "observations.jsonl")
        existing_reviews = read_jsonl_records(review_path) if review_path.exists() else []
        human_label = label.get("human_label") if isinstance(label, dict) else None
        observation = {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "observation_id": observation_id,
            "source": "image_pair" if kind == "image" else "video_window",
            "sample_key": point["key"],
            "media_id": media_id,
            "kind": kind,
            "run_id": run_id,
            "label": label,
            "change_presence": _change_presence_from_human_label(human_label),
            "event_validity": event_validity,
            "dataset_group": _dataset_group_for_observation(
                site, kind=kind, media_id=media_id, captured_at_utc=point.get("time")
            ),
            "label_revision": _next_label_revision(existing_reviews, observation_id),
            "baseline_filename": payload["baseline_filename"],
            "filename": point.get("filename"),
            "captured_at_utc": point.get("time"),
            "config_sha256": _hash(run / "inputs-used" / "site-config.snapshot.json"),
            "reviewed_at_utc": datetime.now(UTC).isoformat(),
            **pilot_review,
        }
        try:
            write_jsonl_record(review_path, observation)
        except (OSError, ValueError):
            if kind == "video":
                return {
                    "success": True,
                    "message": (
                        "Video label saved, but the run review link could not be saved. "
                        "Check disk permissions before continuing."
                    ),
                    "label": label,
                }
            raise
        return {
            "success": True,
            "message": "Human review saved. Machine evidence is unchanged.",
            "label": label,
        }


def save_group(site: Path, data: dict[str, Any]) -> None:
    kind, run_id, media_id = (str(data.get(k, "")) for k in ("kind", "run_id", "media_id"))
    payload = evidence(site, kind, run_id, media_id)
    group = str(data.get("group", ""))
    with _lock:
        if kind == "image":
            run = run_path(site, kind, run_id)
            manifest = read_jsonl_records(run / "inputs-used" / "sequence-manifest.snapshot.jsonl")
            dates = [str(r.get("local_time") or r.get("captured_at_utc"))[:10] for r in manifest]
            if not dates:
                raise ValueError("No dates available for this sequence.")
            if any(
                a["start_date"] == min(dates)
                and a["end_date"] == max(dates)
                and a["group"] == group
                for a in payload["groups"]
            ):
                return
            assign_dataset_group(
                site,
                group=group,
                start_date=min(dates),
                end_date=max(dates),
                note=str(data.get("note", "")),
            )
        else:
            if group not in ALLOWED_MANIFEST_SPLITS:
                raise ValueError("Choose practice or locked_validation.")
            path = _inside(site, "manifest.jsonl")
            rows = load_manifest_records(path)
            matches = [r for r in rows if r.get("video_id") == media_id]
            if len(matches) != 1:
                raise ValueError("Repair the video manifest before assigning a dataset group.")
            matches[0]["split"] = group
            temporary: Path | None = None
            try:
                with NamedTemporaryFile(mode="w", dir=site, delete=False, encoding="utf-8") as out:
                    temporary = Path(out.name)
                    for row in rows:
                        out.write(json.dumps(row, sort_keys=True) + "\n")
                temporary.replace(path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

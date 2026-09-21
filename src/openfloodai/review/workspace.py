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
from openfloodai.review.dataset_groups import assign_dataset_group, list_dataset_group_assignments
from openfloodai.review.dataset_manifest import ALLOWED_MANIFEST_SPLITS, load_manifest_records
from openfloodai.review.human_labels import (
    ALLOWED_CONFIDENCE_LEVELS,
    ALLOWED_TRISTATE_VALUES,
    ALLOWED_VISIBILITY_CONDITIONS,
    create_human_label_record,
    load_human_label_records,
    normalize_human_label,
)
from openfloodai.review.label_comparison import compare_label_records

_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_lock = RLock()


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
        for record in records:
            key = _key(record)
            review = current_reviews.get(key)
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
                }
            )
        for point in points:
            point["comparison"] = _image_comparison(point)
        baseline = summary.get("baseline_filename")
        groups = [asdict(a) for a in list_dataset_group_assignments(site)]
        gauge = _gage_for_run(site, media_id)
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


def _gage_for_run(site: Path, sequence: str) -> dict[str, Any] | None:
    # Existing runs did not snapshot gage data. Explicitly identify this as current
    # supplemental evidence; do not present it as an original machine input.
    root = _inside(site, "inputs", "image-sequences", sequence)
    summary = root / "gauge-readings-summary.json"
    series = root / "gauge-daily-series.json"
    if not summary.exists() or not series.exists():
        return None
    data = _json(summary)
    if not data.get("available"):
        return None
    return {
        "parameter": data.get("parameter_label"),
        "unit": data.get("unit"),
        "relationship": data.get("gage_relationship"),
        "relationship_note": data.get("gage_relationship_note"),
        "rows": _json(series),
        "provenance": "Current supplemental gage data; not a saved machine input.",
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


def save_observation(site: Path, data: dict[str, Any]) -> dict[str, Any]:
    kind, run_id, media_id = (str(data.get(k, "")) for k in ("kind", "run_id", "media_id"))
    with _lock:
        payload = evidence(site, kind, run_id, media_id)
        point = next((p for p in payload["points"] if p["key"] == data.get("sample_key")), None)
        if point is None:
            raise ValueError("Selected sample was not found in the saved machine evidence.")
        label = _label_fields(data)
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
        observation = {
            "sample_key": point["key"],
            "media_id": media_id,
            "kind": kind,
            "run_id": run_id,
            "label": label,
            "baseline_filename": payload["baseline_filename"],
            "filename": point.get("filename"),
            "captured_at_utc": point.get("time"),
            "config_sha256": _hash(run / "inputs-used" / "site-config.snapshot.json"),
            "reviewed_at_utc": datetime.now(UTC).isoformat(),
        }
        try:
            write_jsonl_record(_inside(run, "human-review", "observations.jsonl"), observation)
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

"""Freeze one reviewed observation of a saved run into a self-describing evidence record.

An observation is one source image as a saved validation run saw it. This module only READS the
run, its frozen inputs and the review/segmentation outputs; it never edits them. The result is a
plain JSON-serializable dict (the "observation snapshot") that a dataset keeps, plus the paths of
the bytes (original image, mask files) that a dataset copies so the example can be reproduced even
if the working site folder changes later.

Collection group, numeric gauge target, human label, image quality and review status stay in
separate fields on purpose: a sampling group depends on the requested date range and must never
become a training label.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from openfloodai.contracts import read_jsonl_records
from openfloodai.curation.common import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    CurationError,
    content_id,
    reason,
    sha256_file,
)
from openfloodai.ingestion.river_images import RiverImageError, resolve_sequence_image
from openfloodai.ingestion.sequence_store import read_batches, samples_by_filename
from openfloodai.review.dataset_groups import (
    dataset_group_for_date,
    list_dataset_group_assignments,
)
from openfloodai.review.human_labels import normalize_human_label
from openfloodai.validation import hosted_sam_runner

_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_FILENAME = re.compile(r"^[A-Za-z0-9_-]+___\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z\.jpg$")
UNASSESSABLE_LABELS = {"cannot_judge_water_level", "camera_video_problem"}


@dataclass
class LoadedObservation:
    """The evidence snapshot plus the source files a dataset copies (never serialized)."""

    snapshot: dict[str, Any]
    image_path: Path | None
    problems: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class MaskCandidate:
    """A saved segmentation result for the same image bytes, with its mask files."""

    run_id: str
    result_id: str
    prompt: str
    status: str
    review_status: str
    record: dict[str, Any]
    mask_paths: tuple[Path, ...]


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_dir(site_dir: Path, run_id: str) -> Path:
    if not _ID.fullmatch(run_id):
        raise CurationError("Choose a valid saved run.")
    root = (site_dir / "outputs" / "image-sequence-runs").resolve()
    run = (root / run_id).resolve()
    if run.parent != root or not run.is_dir():
        raise CurationError("Saved run not found.")
    return run


@lru_cache(maxsize=16)
def _gauge_source_info(path: str, mtime_ns: int, size: int) -> dict[str, Any]:
    """The station association and parameter of a run's frozen gauge readings (not the readings)."""

    loaded = _json(Path(path))
    return {
        "status": loaded.get("status"),
        "association": loaded.get("association"),
        "parameter": loaded.get("parameter"),
        "source_url": loaded.get("source_url"),
    }


def _gauge_source(run: Path) -> dict[str, Any]:
    path = run / "inputs-used" / "gauge-readings.snapshot.json"
    if not path.is_file():
        return {}
    stat = path.stat()
    try:
        return _gauge_source_info(str(path), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError):
        return {}


def _latest_review(run: Path, filename: str) -> dict[str, Any] | None:
    path = run / "human-review" / "observations.jsonl"
    if not path.is_file():
        return None
    rows: list[dict[str, Any]] = [
        dict(row)
        for row in read_jsonl_records(path)
        if row.get("filename") == filename and row.get("kind") == "image"
    ]
    if not rows:
        return None
    return max(rows, key=lambda row: int(row.get("label_revision") or 0))


def _review_summary(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    raw_label = row.get("label")
    label: dict[str, Any] = raw_label if isinstance(raw_label, dict) else {}
    return {
        "observation_id": row.get("observation_id"),
        "label_revision": row.get("label_revision"),
        "reviewed_at_utc": row.get("reviewed_at_utc"),
        "human_label": normalize_human_label(label.get("human_label")),
        "confidence": label.get("confidence"),
        "note": label.get("note"),
        "visibility": {
            key: label.get(key)
            for key in (
                "riverbank_visible",
                "stable_marker_visible",
                "water_boundary_visible",
                "camera_stable",
                "visibility_condition",
            )
            if label.get(key)
        },
        "change_presence": row.get("change_presence"),
        "event_validity": row.get("event_validity"),
        "dataset_group": row.get("dataset_group"),
        "config_sha256": row.get("config_sha256"),
    }


def _rows_by_filename(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    return {str(r.get("filename")): dict(r) for r in read_jsonl_records(path) if r.get("filename")}


def load_observation(site_dir: Path, run_id: str, filename: str) -> LoadedObservation:
    """Read one image of a saved run and freeze what a dataset needs to reproduce it."""

    if not _FILENAME.fullmatch(filename):
        raise CurationError("Choose a valid image.")
    run = _run_dir(site_dir, run_id)
    inputs = run / "inputs-used"
    summary = _json(run / "run-summary.json")
    sequence_id = str(summary.get("sequence_id", ""))
    problems: list[dict[str, str]] = []

    manifest = _rows_by_filename(inputs / "sequence-manifest.snapshot.jsonl")
    source_row = manifest.get(filename)
    if source_row is None or source_row.get("download_status") != "downloaded":
        raise CurationError("This image is not a downloaded image of that run.")
    machine_row = _rows_by_filename(run / "image-sequence-records.jsonl").get(filename, {})

    snapshot_images = {
        str(r.get("filename")): r
        for r in _json(inputs / "images.snapshot.json")
        if isinstance(r, dict)
    }
    recorded = snapshot_images.get(filename)

    image_path: Path | None = None
    actual_sha: str | None = None
    try:
        image_path = resolve_sequence_image(site_dir, sequence_id, filename)
        actual_sha = sha256_file(image_path)
    except (RiverImageError, OSError, ValueError):
        problems.append(
            reason("source_missing", "The original image file is no longer in the site folder.")
        )
    recorded_sha = str(recorded["sha256"]) if recorded and recorded.get("sha256") else None
    if recorded_sha is None:
        problems.append(
            reason("image_not_in_run", "This image has no checksum in the run's frozen inputs.")
        )
    elif actual_sha is not None and actual_sha != recorded_sha:
        problems.append(
            reason(
                "source_changed",
                "The image file changed after the run used it, so it is not the same evidence.",
            )
        )
    image_sha = recorded_sha or actual_sha or ""

    baseline_name = str(summary.get("baseline_filename") or "")
    baseline_rec = snapshot_images.get(baseline_name)
    gauge_source = _gauge_source(run)
    match = _json(inputs / "gauge-matches.snapshot.json").get("matches", {}).get(filename)
    reading = match.get("reading") if isinstance(match, dict) else None
    gauge: dict[str, Any] = {
        "match_status": (match or {}).get("match_status", "missing"),
        "reason": (match or {}).get("reason"),
        "reading": reading,
        "time_difference_seconds": (match or {}).get("time_difference_seconds"),
        "station": (gauge_source.get("association") or {}),
        "parameter": gauge_source.get("parameter"),
        "source_status": gauge_source.get("status"),
        "readings_source_url": gauge_source.get("source_url"),
    }

    config = _json(inputs / "site-config.snapshot.json")
    review = _review_summary(_latest_review(run, filename))
    captured = str(source_row.get("captured_at_utc") or "")
    # The group in force NOW decides eligibility and the split, so locking or excluding a date
    # range after a review is respected. The group stamped at review time is kept as history.
    dataset_group = current_dataset_group(site_dir, captured)

    sequence_dir = site_dir / "inputs" / "image-sequences" / sequence_id
    sample = samples_by_filename(read_batches(sequence_dir)).get(filename)
    site_id = str(source_row.get("site_id") or summary.get("site_id") or "")
    camera_id = str(source_row.get("camera_id") or "")
    key_parts = {
        "site_id": site_id,
        "camera_id": camera_id,
        "captured_at_utc": captured,
        "image_sha256": image_sha,
    }
    snapshot = {
        "observation_key": content_id(key_parts, 24),
        "site": {"folder_name": site_dir.name, "site_id": site_id, "camera_id": camera_id},
        "source": {
            "source_system": source_row.get("source_system"),
            "source_url": source_row.get("source_url"),
            "captured_at_utc": captured,
            "local_time": source_row.get("local_time"),
            "sequence_id": sequence_id,
            "run_id": run_id,
        },
        "image": {
            "filename": filename,
            "sha256": image_sha,
            "size_bytes": (recorded or {}).get("size_bytes"),
        },
        "baseline": (
            {
                "filename": baseline_name,
                "sha256": (baseline_rec or {}).get("sha256"),
            }
            if baseline_name
            else None
        ),
        "collection": {
            "group": (sample or {}).get("group"),
            "batch_number": (sample or {}).get("batch_number"),
            "note": "How the image was sampled for download. It is not a training label.",
        },
        "dataset_group": dataset_group,
        "dataset_group_at_review": (review or {}).get("dataset_group"),
        "gauge": gauge,
        "configuration": {
            "config_sha256": (review or {}).get("config_sha256")
            or _file_sha(inputs / "site-config.snapshot.json"),
            "reference_region": config.get("reference_region"),
            "normal_waterline_guides": config.get("normal_waterline_guides") or [],
            "watched_area_used": summary.get("watched_area_used"),
        },
        "review": review,
        "machine": {
            "result": machine_row.get("result"),
            "region_change_score": machine_row.get("region_change_score"),
            "reason": machine_row.get("reason"),
            "note": "Machine output. It is not a label.",
        },
    }
    return LoadedObservation(snapshot=snapshot, image_path=image_path, problems=problems)


def current_dataset_group(site_dir: Path, captured_at_utc: str) -> str:
    """The site's dataset group for this capture date as assigned today."""

    return dataset_group_for_date(list_dataset_group_assignments(site_dir), captured_at_utc[:10])


def _file_sha(path: Path) -> str | None:
    try:
        return sha256_file(path)
    except OSError:
        return None


def find_mask_candidates(site_dir: Path, snapshot: dict[str, Any]) -> list[MaskCandidate]:
    """Saved segmentation results made from exactly this image's bytes, newest first."""

    source = snapshot["source"]
    image = snapshot["image"]
    candidates: list[MaskCandidate] = []
    for record in hosted_sam_runner.list_sam_results(site_dir, str(source["sequence_id"])):
        if record.get("filename") != image["filename"]:
            continue
        if record.get("image_sha256") != image["sha256"]:
            continue
        run_dir = hosted_sam_runner._run_dir(site_dir, str(record["run_id"]))
        paths = tuple(
            (run_dir / str(d["mask_png"])).resolve()
            for d in record.get("detections", [])
            if isinstance(d, dict) and d.get("mask_png")
        )
        candidates.append(
            MaskCandidate(
                run_id=str(record["run_id"]),
                result_id=str(record["result_id"]),
                prompt=str(record.get("prompt", "")),
                status=str(record.get("status", "")),
                review_status=str(record.get("review_status", "unreviewed")),
                record=record,
                mask_paths=paths,
            )
        )
    return candidates


def has_unassessable_label(snapshot: dict[str, Any]) -> bool:
    review = snapshot.get("review")
    return bool(review and review.get("human_label") in UNASSESSABLE_LABELS)


def integrity_reasons(loaded: LoadedObservation) -> list[dict[str, str]]:
    """Missing or changed source bytes always block an example."""

    return [p for p in loaded.problems if p["severity"] in (SEVERITY_ERROR, SEVERITY_WARNING)]

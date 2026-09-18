"""Run local validation against a saved USGS image sequence (issue #182).

This is a separate, parallel path to `site_runner.py`'s video validation: it
reads `inputs/image-sequences/<sequence_id>/sequence-manifest.jsonl` (built
by the image-sequence intake flow, issue #181) and writes its own run folder
under `outputs/image-sequence-runs/<run_id>/`. It shares only data types
(site config) with the video flow, no functions, and never touches
`outputs/runs/` or anything the video `Run validation` flow reads.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import cv2

from openfloodai.config import load_site_config, reference_region_to_dict
from openfloodai.contracts import read_jsonl_records, write_jsonl_records
from openfloodai.review.event_reviews import (
    EventReviewError,
    compute_evidence_key,
    list_event_reviews,
)
from openfloodai.review.review_images import generate_biggest_change_review_images
from openfloodai.vision.simple_signals import (
    VisualSignalError,
    compare_region_signals,
    extract_region_signals,
)

RESULT_POSSIBLE_WATER_LEVEL_CHANGE = "possible_water_level_change"
RESULT_NO_WATER_LEVEL_CHANGE = "no_water_level_change"
RESULT_CANNOT_JUDGE_WATER_LEVEL = "cannot_judge_water_level"
RESULT_CAMERA_OR_IMAGE_PROBLEM = "camera_or_image_problem"

_DARK_BRIGHTNESS_THRESHOLD = 0.08
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_SEQUENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class ImageSequenceValidationError(ValueError):
    """Raised when an image-sequence validation run cannot be configured."""


@dataclass(frozen=True)
class ImageSequenceRecord:
    """One compared image's machine observation."""

    filename: str
    captured_at_utc: str
    local_time: str
    download_status: str
    result: str
    reason: str
    region_change_score: float | None = None
    region_brightness_score: float | None = None


@dataclass(frozen=True)
class ImageSequenceValidationReport:
    """Result of one image-sequence validation run."""

    site_name: str
    sequence_id: str
    run_id: str
    run_dir: Path
    baseline_filename: str
    records: list[ImageSequenceRecord]
    possible_change_count: int
    no_change_count: int
    cannot_judge_count: int
    camera_or_image_problem_count: int

    @property
    def image_count(self) -> int:
        """Return how many images were compared (excluding the baseline)."""

        return len(self.records)


def run_image_sequence_validation(
    site_dir: Path,
    sequence_id: str,
    *,
    baseline_filename: str | None = None,
) -> ImageSequenceValidationReport:
    """Run local validation against one saved image sequence in a site folder."""

    if not site_dir.exists() or not site_dir.is_dir():
        raise ImageSequenceValidationError(f"Site folder does not exist: {site_dir}")
    if not _SEQUENCE_ID_PATTERN.fullmatch(sequence_id or ""):
        raise ImageSequenceValidationError("Invalid sequence_id.")

    config_path = _find_config_path(site_dir)
    site_config = load_site_config(config_path)
    if site_config.reference_region is None:
        raise ImageSequenceValidationError(
            "Set the site's watched area before running image-sequence validation."
        )

    sequence_dir = site_dir / "inputs" / "image-sequences" / sequence_id
    manifest_path = sequence_dir / "sequence-manifest.jsonl"
    images_dir = sequence_dir / "images"
    if not manifest_path.is_file():
        raise ImageSequenceValidationError(f"Image sequence not found: {sequence_id}")

    try:
        manifest_records = read_jsonl_records(manifest_path)
    except ValueError as error:
        raise ImageSequenceValidationError(
            f"Could not read image sequence manifest: {error}"
        ) from error

    sorted_records = sorted(
        manifest_records, key=lambda record: str(record.get("captured_at_utc", ""))
    )
    downloaded_records = [
        record for record in sorted_records if record.get("download_status") == "downloaded"
    ]
    if len(downloaded_records) < 2:
        raise ImageSequenceValidationError(
            "At least two downloaded images (a baseline and one to compare) are "
            "required to run image-sequence validation."
        )

    baseline_record = _select_baseline(downloaded_records, baseline_filename)
    baseline_path = images_dir / str(baseline_record["filename"])
    baseline_frame = cv2.imread(str(baseline_path))
    if baseline_frame is None:
        raise ImageSequenceValidationError(
            f"Could not read the baseline image: {baseline_record['filename']}"
        )
    # Never silently trust the earliest downloaded image as a normal baseline
    # without checking it's actually usable — a dark/near-black baseline
    # would make every later comparison meaningless. Applies whether the
    # baseline was chosen automatically or given explicitly.
    baseline_signals = extract_region_signals(
        baseline_frame, site_config.reference_region, site_config.site_id, site_config.camera_id
    )
    baseline_brightness = cast(float, baseline_signals["region_brightness_score"])
    if baseline_brightness < _DARK_BRIGHTNESS_THRESHOLD:
        raise ImageSequenceValidationError(
            f"The baseline image ({baseline_record['filename']}) is too dark to use as a "
            "normal baseline. Choose a different, clearer baseline image."
        )

    records: list[ImageSequenceRecord] = []
    best_score = -1.0
    best_filename: str | None = None
    best_frame = None

    for record in sorted_records:
        filename = str(record.get("filename", ""))
        if filename == str(baseline_record["filename"]):
            continue
        captured_at_utc = str(record.get("captured_at_utc", ""))
        local_time = str(record.get("local_time", captured_at_utc))
        download_status = str(record.get("download_status", "missing"))

        if download_status != "downloaded":
            records.append(
                ImageSequenceRecord(
                    filename=filename,
                    captured_at_utc=captured_at_utc,
                    local_time=local_time,
                    download_status=download_status,
                    result=RESULT_CAMERA_OR_IMAGE_PROBLEM,
                    reason=f"Image was not downloaded ({download_status}); cannot judge.",
                )
            )
            continue

        current_frame = cv2.imread(str(images_dir / filename))
        if current_frame is None:
            records.append(
                ImageSequenceRecord(
                    filename=filename,
                    captured_at_utc=captured_at_utc,
                    local_time=local_time,
                    download_status=download_status,
                    result=RESULT_CAMERA_OR_IMAGE_PROBLEM,
                    reason="Image file could not be read.",
                )
            )
            continue

        try:
            signals = compare_region_signals(
                baseline_frame,
                current_frame,
                site_config.reference_region,
                site_config.site_id,
                site_config.camera_id,
                timestamp=captured_at_utc or None,
            )
        except VisualSignalError as error:
            records.append(
                ImageSequenceRecord(
                    filename=filename,
                    captured_at_utc=captured_at_utc,
                    local_time=local_time,
                    download_status=download_status,
                    result=RESULT_CAMERA_OR_IMAGE_PROBLEM,
                    reason=f"Could not compare this image with the baseline: {error}",
                )
            )
            continue

        change_score = cast(float, signals["region_change_score"])
        brightness_score = cast(float, signals["region_brightness_score"])
        evidence_state = str(signals["water_level_evidence_state"])
        result, reason = _classify_comparison(evidence_state, brightness_score)
        records.append(
            ImageSequenceRecord(
                filename=filename,
                captured_at_utc=captured_at_utc,
                local_time=local_time,
                download_status=download_status,
                result=result,
                reason=reason,
                region_change_score=change_score,
                region_brightness_score=brightness_score,
            )
        )
        if result != RESULT_CAMERA_OR_IMAGE_PROBLEM and change_score > best_score:
            best_score = change_score
            best_filename = filename
            best_frame = current_frame

    counts = Counter(record.result for record in records)
    run_id = f"{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    run_dir = site_dir / "outputs" / "image-sequence-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    review_images_generated = False
    if best_frame is not None:
        try:
            generate_biggest_change_review_images(
                [baseline_frame, best_frame],
                run_dir / "review-images",
                reference_region=site_config.reference_region,
                normal_waterline_guides=site_config.normal_waterline_guides,
                prefix="image-sequence",
            )
            review_images_generated = True
        except Exception:  # noqa: BLE001 - review images are best-effort, never fail the run
            review_images_generated = False

    report = ImageSequenceValidationReport(
        site_name=site_dir.name,
        sequence_id=sequence_id,
        run_id=run_id,
        run_dir=run_dir,
        baseline_filename=str(baseline_record["filename"]),
        records=records,
        possible_change_count=counts[RESULT_POSSIBLE_WATER_LEVEL_CHANGE],
        no_change_count=counts[RESULT_NO_WATER_LEVEL_CHANGE],
        cannot_judge_count=counts[RESULT_CANNOT_JUDGE_WATER_LEVEL],
        camera_or_image_problem_count=counts[RESULT_CAMERA_OR_IMAGE_PROBLEM],
    )

    write_jsonl_records(
        run_dir / "image-sequence-records.jsonl",
        [asdict(record) for record in records],
    )
    _write_run_summary(
        run_dir=run_dir,
        report=report,
        site_config=site_config,
        best_filename=best_filename,
        review_images_generated=review_images_generated,
    )
    _write_report_markdown(
        run_dir=run_dir, report=report, review_images_generated=review_images_generated
    )
    _write_inputs_used(
        run_dir=run_dir,
        manifest_path=manifest_path,
        images_dir=images_dir,
        site_config=site_config,
        report=report,
    )

    return report


def list_image_sequence_runs(site_dir: Path, sequence_id: str) -> list[dict[str, Any]]:
    """Return saved run summaries for one site's image sequence, newest first."""

    runs_dir = site_dir / "outputs" / "image-sequence-runs"
    if not runs_dir.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for run_dir in runs_dir.iterdir():
        summary_path = run_dir / "run-summary.json"
        if not run_dir.is_dir() or not summary_path.is_file():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(summary, dict) and summary.get("sequence_id") == sequence_id:
            summaries.append(summary)
    return sorted(summaries, key=lambda summary: str(summary.get("created_at", "")), reverse=True)


def resolve_image_sequence_run_image(site_dir: Path, run_id: str, filename: str) -> Path:
    """Serve only a review image belonging to one saved image-sequence run."""

    if not _RUN_ID_PATTERN.fullmatch(run_id or "") or not re.fullmatch(
        r"image-sequence-[a-z-]+\.png", filename or ""
    ):
        raise ImageSequenceValidationError("Review image not found.")
    runs_root = (site_dir / "outputs" / "image-sequence-runs").resolve()
    review_images_dir = (runs_root / run_id / "review-images").resolve()
    try:
        review_images_dir.relative_to(runs_root)
    except ValueError as error:
        raise ImageSequenceValidationError("Review image not found.") from error
    candidate = review_images_dir / filename
    if review_images_dir.is_symlink() or candidate.is_symlink() or not candidate.is_file():
        raise ImageSequenceValidationError("Review image not found.")
    candidate.resolve().relative_to(review_images_dir)
    return candidate


def resolve_run_config_snapshot(site_dir: Path, run_id: str) -> dict[str, Any]:
    """Load the exact watched-area/waterline-guide config one saved run used.

    A run's own comparison images must always reflect what that run was
    scored against, even after the site's live config is later edited —
    this reads the frozen `site-config.snapshot.json` written at run time
    (`_write_inputs_used`), never the current config.
    """

    if not _RUN_ID_PATTERN.fullmatch(run_id or ""):
        raise ImageSequenceValidationError("Run not found.")
    runs_root = (site_dir / "outputs" / "image-sequence-runs").resolve()
    snapshot_path = (runs_root / run_id / "inputs-used" / "site-config.snapshot.json").resolve()
    try:
        snapshot_path.relative_to(runs_root)
    except ValueError as error:
        raise ImageSequenceValidationError("Run not found.") from error
    if snapshot_path.is_symlink() or not snapshot_path.is_file():
        raise ImageSequenceValidationError("Run configuration snapshot not found.")
    try:
        loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ImageSequenceValidationError("Run configuration snapshot not found.") from error
    if not isinstance(loaded, dict):
        raise ImageSequenceValidationError("Run configuration snapshot not found.")
    return loaded


def read_image_sequence_run_detail(site_dir: Path, run_id: str) -> dict[str, Any]:
    """Read one saved image-sequence run's summary, records, and report text."""

    if not _RUN_ID_PATTERN.fullmatch(run_id or ""):
        raise ImageSequenceValidationError("Run not found.")
    runs_root = (site_dir / "outputs" / "image-sequence-runs").resolve()
    run_dir = (runs_root / run_id).resolve()
    try:
        run_dir.relative_to(runs_root)
    except ValueError as error:
        raise ImageSequenceValidationError("Run not found.") from error
    summary_path = run_dir / "run-summary.json"
    if not run_dir.is_dir() or not summary_path.is_file():
        raise ImageSequenceValidationError("Run not found.")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    records_path = run_dir / "image-sequence-records.jsonl"
    records = read_jsonl_records(records_path) if records_path.is_file() else []
    report_path = run_dir / "image-sequence-report.md"
    report_text = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    review_images: list[str] = []
    review_images_dir = run_dir / "review-images"
    if review_images_dir.is_dir():
        review_images = sorted(path.name for path in review_images_dir.glob("*.png"))

    gauge_series: list[dict[str, Any]] = []
    event_reviews: dict[str, str] = {}
    sequence_id = summary.get("sequence_id") if isinstance(summary, dict) else None
    if isinstance(sequence_id, str) and sequence_id:
        sequence_dir = site_dir / "inputs" / "image-sequences" / sequence_id
        gauge_series_path = sequence_dir / "gauge-daily-series.json"
        if gauge_series_path.is_file():
            try:
                loaded = json.loads(gauge_series_path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    gauge_series = loaded
            except (OSError, ValueError):
                gauge_series = []
        evidence_key = compute_evidence_key(
            summary.get("baseline_filename") if isinstance(summary, dict) else None,
            summary.get("watched_area_used") if isinstance(summary, dict) else None,
        )
        try:
            event_reviews = list_event_reviews(sequence_dir, evidence_key=evidence_key)
        except EventReviewError:
            event_reviews = {}

    return {
        "summary": summary,
        "records": records,
        "report": report_text,
        "review_images": review_images,
        "gauge_series": gauge_series,
        "event_reviews": event_reviews,
    }


def _select_baseline(
    downloaded_records: list[dict[str, Any]], baseline_filename: str | None
) -> dict[str, Any]:
    if baseline_filename is None:
        return downloaded_records[0]
    for record in downloaded_records:
        if record.get("filename") == baseline_filename:
            return record
    raise ImageSequenceValidationError(
        f"baseline_filename is not a downloaded image in this sequence: {baseline_filename}"
    )


def _classify_comparison(evidence_state: str, brightness_score: float) -> tuple[str, str]:
    if brightness_score < _DARK_BRIGHTNESS_THRESHOLD:
        return (
            RESULT_CAMERA_OR_IMAGE_PROBLEM,
            "The watched area is very dark; the camera may be offline or it is nighttime.",
        )
    if evidence_state == "cannot_judge_whole_region_changed":
        return (
            RESULT_CAMERA_OR_IMAGE_PROBLEM,
            "The whole watched area changed at once, which usually means lighting, "
            "weather, or camera movement rather than a real water-level change.",
        )
    if evidence_state == "cannot_judge_region_too_small":
        return (
            RESULT_CANNOT_JUDGE_WATER_LEVEL,
            "The watched area is too small to judge water-level evidence.",
        )
    if evidence_state == "weak_visual_evidence":
        return (
            RESULT_NO_WATER_LEVEL_CHANGE,
            "No meaningful change was detected in the watched area compared to the baseline image.",
        )
    if evidence_state == "useful_water_level_evidence":
        return (
            RESULT_POSSIBLE_WATER_LEVEL_CHANGE,
            "The watched area changed in a pattern consistent with a possible water-level "
            "change. This is not proof of flooding.",
        )
    # An unrecognized signal must never be treated as a possible water-level
    # change by default — if openfloodai.vision.simple_signals ever adds or
    # renames a state, this falls back to the conservative "cannot judge"
    # bucket instead of silently reporting a false positive.
    return (
        RESULT_CANNOT_JUDGE_WATER_LEVEL,
        f"Unrecognized comparison signal ({evidence_state}); cannot judge safely.",
    )


def _find_config_path(site_dir: Path) -> Path:
    configs_dir = site_dir / "configs"
    config_paths = sorted(configs_dir.glob("*.json")) if configs_dir.exists() else []
    if not config_paths:
        raise ImageSequenceValidationError(f"No site config JSON file found under: {configs_dir}")
    return config_paths[0]


def _confirmed_riverbank_guide_ids(site_config: Any) -> list[str]:
    return [
        guide.id
        for guide in site_config.normal_waterline_guides
        if guide.status == "confirmed" and guide.normal_condition
    ]


def _write_run_summary(
    *,
    run_dir: Path,
    report: ImageSequenceValidationReport,
    site_config: Any,
    best_filename: str | None,
    review_images_generated: bool,
) -> None:
    summary = {
        "run_id": report.run_id,
        "sequence_id": report.sequence_id,
        "site_name": report.site_name,
        "site_id": site_config.site_id,
        "camera_id": site_config.camera_id,
        "baseline_filename": report.baseline_filename,
        "image_count": report.image_count,
        "possible_water_level_change_count": report.possible_change_count,
        "no_water_level_change_count": report.no_change_count,
        "cannot_judge_water_level_count": report.cannot_judge_count,
        "camera_or_image_problem_count": report.camera_or_image_problem_count,
        "watched_area_used": reference_region_to_dict(site_config.reference_region),
        "confirmed_riverbank_guide_ids": _confirmed_riverbank_guide_ids(site_config),
        "biggest_change_filename": best_filename,
        "review_images_generated": review_images_generated,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }
    (run_dir / "run-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


def _write_report_markdown(
    *,
    run_dir: Path,
    report: ImageSequenceValidationReport,
    review_images_generated: bool,
) -> None:
    lines = [
        "# Image Sequence Validation Report",
        "",
        f"- Site: {report.site_name}",
        f"- Sequence: {report.sequence_id}",
        f"- Run: {report.run_id}",
        f"- Baseline image: {report.baseline_filename}",
        "",
        "## Counts",
        f"- Images compared: {report.image_count}",
        f"- Possible water level change: {report.possible_change_count}",
        f"- No water level change: {report.no_change_count}",
        f"- Cannot judge water level: {report.cannot_judge_count}",
        f"- Camera or image problem: {report.camera_or_image_problem_count}",
        "",
        "## Summary",
        (
            f"Compared {report.image_count} image(s) against the baseline image "
            f"{report.baseline_filename}: {report.possible_change_count} possible water "
            f"level change, {report.no_change_count} no change, "
            f"{report.cannot_judge_count} cannot judge, and "
            f"{report.camera_or_image_problem_count} camera or image problem."
        ),
        "",
    ]
    if not review_images_generated:
        lines.append(
            "No review images were generated because every compared image had a "
            "camera or image problem, or none produced a usable comparison."
        )
        lines.append("")
    lines.append("## Detailed Results")
    for record in report.records:
        lines.append(f"### {record.filename}")
        lines.append(f"- Captured: {record.captured_at_utc}")
        lines.append(f"- Local time: {record.local_time}")
        lines.append(f"- Download status: {record.download_status}")
        lines.append(f"- Result: {record.result}")
        lines.append(f"- Reason: {record.reason}")
        if record.region_change_score is not None:
            lines.append(f"- Region change score: {record.region_change_score}")
        lines.append("")
    lines.append("## Safety Boundary")
    lines.append(
        "Visual change does not establish water direction or flood safety. This "
        "report is for local review only and must never be issued as a public "
        "flood warning."
    )
    lines.append("")
    (run_dir / "image-sequence-report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_inputs_used(
    *,
    run_dir: Path,
    manifest_path: Path,
    images_dir: Path,
    site_config: Any,
    report: ImageSequenceValidationReport,
) -> None:
    root = run_dir / "inputs-used"
    root.mkdir(exist_ok=False)
    shutil.copyfile(manifest_path, root / "sequence-manifest.snapshot.jsonl")
    config_snapshot = {
        "reference_region": reference_region_to_dict(site_config.reference_region),
        # Full guide records (points, source, timestamps, status, notes) —
        # not just id/label/status — so a run proves the exact riverbank
        # guide it used, not merely which guide id existed at the time.
        "normal_waterline_guides": [asdict(guide) for guide in site_config.normal_waterline_guides],
    }
    (root / "site-config.snapshot.json").write_text(
        json.dumps(config_snapshot, indent=2) + "\n", encoding="utf-8"
    )

    # A sha256 per processed image file, so a run proves exactly which image
    # bytes it used even after the live image sequence is later replaced or
    # re-downloaded under the same filenames.
    hashed_filenames = [report.baseline_filename] + [
        record.filename for record in report.records if record.download_status == "downloaded"
    ]
    images_used = []
    for filename in hashed_filenames:
        image_path = images_dir / filename
        if not image_path.is_file():
            continue
        images_used.append(
            {
                "filename": filename,
                "sha256": _sha256_of_file(image_path),
                "size_bytes": image_path.stat().st_size,
            }
        )
    (root / "images.snapshot.json").write_text(
        json.dumps(images_used, indent=2) + "\n", encoding="utf-8"
    )

    receipt = {
        "run_id": report.run_id,
        "sequence_id": report.sequence_id,
        "site_name": report.site_name,
        "baseline_filename": report.baseline_filename,
        "image_count": report.image_count,
        "captured_at": datetime.now(tz=UTC).isoformat(),
        "status": "complete",
    }
    (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

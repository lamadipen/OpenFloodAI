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
from openfloodai.evidence.adapters.pixel_change import (
    PLUGIN_ID as _PIXEL_CHANGE_PLUGIN_ID,
)
from openfloodai.evidence.adapters.pixel_change import (
    PLUGIN_VERSION as _PIXEL_CHANGE_PLUGIN_VERSION,
)
from openfloodai.evidence.adapters.pixel_change import evidence_from_pixel_change_signal
from openfloodai.evidence.adapters.riverbank_crossing import (
    PLUGIN_ID as _RIVERBANK_CROSSING_PLUGIN_ID,
)
from openfloodai.evidence.adapters.riverbank_crossing import (
    PLUGIN_VERSION as _RIVERBANK_CROSSING_PLUGIN_VERSION,
)
from openfloodai.evidence.adapters.riverbank_crossing import RiverbankCrossingObservationAdapter
from openfloodai.evidence.contract import EvidenceRecord, build_unavailable_evidence
from openfloodai.evidence.settings import (
    EvidenceSettingsError,
    resolve_adapter_setting_source,
    resolve_effective_adapter_settings,
)
from openfloodai.ingestion.river_images import WATER_LEVEL_SELECTION_FILENAME
from openfloodai.ingestion.sequence_store import (
    SequenceBusyError,
    read_batches,
    read_display_name,
    samples_by_filename,
    sequence_label,
    sequence_lock,
)
from openfloodai.ingestion.usgs_gage_data import (
    GAUGE_SOURCE_FILENAME,
    RUN_GAUGE_EVIDENCE_FILENAME,
    build_run_gauge_evidence,
    load_gauge_matches,
    parse_gauge_source,
)
from openfloodai.ingestion.water_level_intake import recover_interrupted_append
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

WATER_LEVEL_SELECTION_SNAPSHOT = "water-level-selection.snapshot.json"
WATER_LEVEL_SAMPLING_SNAPSHOT_DIR = "sampling"
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
    """Run local validation against one saved image sequence in a site folder.

    The sequence is held while the run reads it, so an append that is committing at
    the same moment cannot change the manifest, images, gauge data, or sampling record
    half way through. Every run therefore sees one consistent snapshot, which it then
    freezes in its own folder.
    """

    if not site_dir.exists() or not site_dir.is_dir():
        raise ImageSequenceValidationError(f"Site folder does not exist: {site_dir}")
    if not _SEQUENCE_ID_PATTERN.fullmatch(sequence_id or ""):
        raise ImageSequenceValidationError("Invalid sequence_id.")
    sequence_dir = site_dir / "inputs" / "image-sequences" / sequence_id
    if not sequence_dir.is_dir():
        raise ImageSequenceValidationError(f"Image sequence not found: {sequence_id}")
    try:
        with sequence_lock(sequence_dir):
            # An interrupted append may have committed images whose sampling history is
            # still pending, or left a stale summary. Repair that first, under the lock, so
            # this run reads (and freezes) one complete, consistent sequence.
            recover_interrupted_append(sequence_dir)
            return _run_image_sequence_validation(
                site_dir, sequence_id, baseline_filename=baseline_filename
            )
    except SequenceBusyError as error:
        raise ImageSequenceValidationError(str(error)) from error


def _run_image_sequence_validation(
    site_dir: Path,
    sequence_id: str,
    *,
    baseline_filename: str | None = None,
) -> ImageSequenceValidationReport:

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

    if baseline_filename is None and read_batches(sequence_dir):
        # A water-level sample set is picked for level variety, so its earliest image is not
        # a meaningful "normal" reference. Never fall back to it silently.
        raise ImageSequenceValidationError(
            "Choose a baseline image for this water-level sample set. Its earliest image is "
            "not assumed to be a normal reference."
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

    # The pixel-change adapter now drives this row's actual classification, not just a
    # side-channel evidence-records.jsonl (docs/architecture/plugin-evidence-architecture.md,
    # issue #193): build the evidence record once from compare_region_signals()'s output, then
    # classify from that record instead of re-reading the raw signals dict a second time. When
    # the adapter is disabled for this site (site override wins over the global setting), no
    # comparison is attempted at all -- the row becomes "cannot judge", not a silently-normal
    # result, matching "missing evidence is not normal evidence".
    # site_dir is always <sites_dir>/<folder_name> (see home_server.py's
    # _resolve_site_dir), and the reference directory is a sibling of
    # sites_dir itself, matching home_server.py's own _reference_dir() --
    # i.e. two levels up from an individual site, not one.
    reference_dir = site_dir.parent.parent / "reference"
    try:
        pixel_change_enabled = resolve_effective_adapter_settings(
            reference_dir, site_overrides=site_config.evidence_adapter_overrides
        )[_PIXEL_CHANGE_PLUGIN_ID]
        pixel_change_adapter_source = resolve_adapter_setting_source(
            reference_dir,
            _PIXEL_CHANGE_PLUGIN_ID,
            site_overrides=site_config.evidence_adapter_overrides,
        )
    except EvidenceSettingsError as error:
        raise ImageSequenceValidationError(
            f"Could not read evidence adapter settings: {error}"
        ) from error

    # riverbank_crossing_v1 is independent from pixel_change_region_v1: its
    # own enable/disable resolution, its own evidence records, and it never
    # affects this row's result/reason -- unevaluated evidence must not
    # change the existing classification (see the adapter's catalog entry:
    # is_default=False until proven against the human-reviewed pilot).
    try:
        riverbank_crossing_enabled = resolve_effective_adapter_settings(
            reference_dir, site_overrides=site_config.evidence_adapter_overrides
        )[_RIVERBANK_CROSSING_PLUGIN_ID]
        riverbank_crossing_adapter_source = resolve_adapter_setting_source(
            reference_dir,
            _RIVERBANK_CROSSING_PLUGIN_ID,
            site_overrides=site_config.evidence_adapter_overrides,
        )
    except EvidenceSettingsError as error:
        raise ImageSequenceValidationError(
            f"Could not read evidence adapter settings: {error}"
        ) from error
    # The confirmed, normal-condition guide with a water_side_point set, if
    # any -- resolved once per run since guides don't change mid-run. A site
    # with more than one eligible guide uses the first one whose saved
    # SOURCE actually matches this sequence, in config order; fusing
    # multiple guides' evidence is not part of this v1 slice.
    #
    # A guide's points are only meaningful relative to the exact frame it
    # was traced on -- comparing against some other, arbitrary frame (e.g.
    # this run's chosen baseline_filename, which may be a completely
    # different image) can produce convincing but wrong crossing evidence,
    # so riverbank_crossing_v1 always loads its OWN baseline frame from the
    # guide's own image_sequence_id/image_filename, never baseline_frame.
    eligible_riverbank_guides = [
        guide
        for guide in site_config.normal_waterline_guides
        if guide.status == "confirmed"
        and guide.normal_condition
        and guide.water_side_point is not None
    ]
    riverbank_crossing_guide = next(
        (guide for guide in eligible_riverbank_guides if guide.image_sequence_id == sequence_id),
        None,
    )
    riverbank_crossing_source_mismatch = (
        riverbank_crossing_guide is None and len(eligible_riverbank_guides) > 0
    )

    riverbank_crossing_baseline_frame = None
    if riverbank_crossing_guide is not None:
        riverbank_crossing_baseline_frame = cv2.imread(
            str(images_dir / riverbank_crossing_guide.image_filename)
        )

    def _riverbank_crossing_unavailable(
        *, timestamp: str, status: str, reason_codes: tuple[str, ...]
    ) -> EvidenceRecord:
        return build_unavailable_evidence(
            plugin_id=_RIVERBANK_CROSSING_PLUGIN_ID,
            plugin_version=_RIVERBANK_CROSSING_PLUGIN_VERSION,
            plugin_family="observation",
            site_id=site_config.site_id,
            camera_id=site_config.camera_id,
            evidence_type="riverbank_crossing_percentage",
            status=status,
            reason_codes=reason_codes,
            timestamp=timestamp or None,
        )

    def _riverbank_crossing_disabled(*, timestamp: str) -> EvidenceRecord:
        return build_unavailable_evidence(
            plugin_id=_RIVERBANK_CROSSING_PLUGIN_ID,
            plugin_version=_RIVERBANK_CROSSING_PLUGIN_VERSION,
            plugin_family="observation",
            site_id=site_config.site_id,
            camera_id=site_config.camera_id,
            evidence_type="riverbank_crossing_percentage",
            status="disabled",
            reason_codes=("ADAPTER_DISABLED",),
            timestamp=timestamp or None,
        )

    evidence_records: list[EvidenceRecord] = []

    def _unavailable_evidence(*, timestamp: str, reason_codes: tuple[str, ...]) -> EvidenceRecord:
        return build_unavailable_evidence(
            plugin_id=_PIXEL_CHANGE_PLUGIN_ID,
            plugin_version=_PIXEL_CHANGE_PLUGIN_VERSION,
            plugin_family="observation",
            site_id=site_config.site_id,
            camera_id=site_config.camera_id,
            evidence_type="region_pixel_change_score",
            status="unavailable",
            reason_codes=reason_codes,
            timestamp=timestamp or None,
        )

    def _disabled_evidence(*, timestamp: str) -> EvidenceRecord:
        return build_unavailable_evidence(
            plugin_id=_PIXEL_CHANGE_PLUGIN_ID,
            plugin_version=_PIXEL_CHANGE_PLUGIN_VERSION,
            plugin_family="observation",
            site_id=site_config.site_id,
            camera_id=site_config.camera_id,
            evidence_type="region_pixel_change_score",
            status="disabled",
            reason_codes=("ADAPTER_DISABLED",),
            timestamp=timestamp or None,
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
            evidence_records.append(
                _unavailable_evidence(
                    timestamp=captured_at_utc, reason_codes=("IMAGE_NOT_DOWNLOADED",)
                )
            )
            evidence_records.append(
                _riverbank_crossing_unavailable(
                    timestamp=captured_at_utc,
                    status="unavailable",
                    reason_codes=("IMAGE_NOT_DOWNLOADED",),
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
            evidence_records.append(
                _unavailable_evidence(
                    timestamp=captured_at_utc, reason_codes=("IMAGE_FILE_UNREADABLE",)
                )
            )
            evidence_records.append(
                _riverbank_crossing_unavailable(
                    timestamp=captured_at_utc,
                    status="unavailable",
                    reason_codes=("IMAGE_FILE_UNREADABLE",),
                )
            )
            continue

        # riverbank_crossing_v1 always runs its own gating here, entirely
        # independent of pixel_change_region_v1's enabled/disabled state
        # below -- neither adapter's outcome affects the other's evidence or
        # this row's result/reason.
        if not riverbank_crossing_enabled:
            riverbank_crossing_evidence = _riverbank_crossing_disabled(timestamp=captured_at_utc)
        elif riverbank_crossing_guide is None:
            reason = (
                "GUIDE_SOURCE_MISMATCH" if riverbank_crossing_source_mismatch else "GUIDE_MISSING"
            )
            riverbank_crossing_evidence = _riverbank_crossing_unavailable(
                timestamp=captured_at_utc, status="invalid", reason_codes=(reason,)
            )
        elif riverbank_crossing_baseline_frame is None:
            riverbank_crossing_evidence = _riverbank_crossing_unavailable(
                timestamp=captured_at_utc,
                status="unavailable",
                reason_codes=("GUIDE_BASELINE_MISSING",),
            )
        else:
            riverbank_crossing_evidence = RiverbankCrossingObservationAdapter(
                site_id=site_config.site_id,
                camera_id=site_config.camera_id,
                guide_id=riverbank_crossing_guide.id,
                guide_points=riverbank_crossing_guide.points,
                water_side_point=riverbank_crossing_guide.water_side_point,
                reference_region=site_config.reference_region,
                previous_frame=riverbank_crossing_baseline_frame,
                current_frame=current_frame,
                timestamp=captured_at_utc or None,
            ).collect()
        evidence_records.append(riverbank_crossing_evidence)

        # The adapter-enabled check comes after download/readability, not before:
        # a missing or unreadable image is a fact about the IMAGE, not the adapter,
        # and must still count as camera_or_image_problem regardless of whether the
        # adapter is on. Only once an image is confirmed valid and readable does
        # "the adapter is off" become the reason nothing was measured.
        if not pixel_change_enabled:
            records.append(
                ImageSequenceRecord(
                    filename=filename,
                    captured_at_utc=captured_at_utc,
                    local_time=local_time,
                    download_status=download_status,
                    result=RESULT_CANNOT_JUDGE_WATER_LEVEL,
                    reason=(
                        "The pixel-change signal is turned off for this site, "
                        "so water-level change cannot be judged."
                    ),
                )
            )
            evidence_records.append(_disabled_evidence(timestamp=captured_at_utc))
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
            evidence_records.append(
                _unavailable_evidence(
                    timestamp=captured_at_utc, reason_codes=("VISUAL_COMPARISON_FAILED",)
                )
            )
            continue

        # Build the evidence record once, then classify FROM it -- not from a second,
        # independent read of the same raw `signals` dict. This is the one thing that
        # changed here: same numbers, same rules, one source of truth for both this row's
        # result and its entry in evidence-records.jsonl.
        pixel_change_evidence = evidence_from_pixel_change_signal(
            signals, site_id=site_config.site_id, camera_id=site_config.camera_id
        )
        change_score = cast(float, pixel_change_evidence.value)
        quality = pixel_change_evidence.quality or {}
        brightness_score = cast(float, quality["region_brightness_score"])
        evidence_state = pixel_change_evidence.reason_codes[0]
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
        evidence_records.append(pixel_change_evidence)
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
    write_jsonl_records(
        run_dir / "evidence-records.jsonl",
        [evidence_record.to_dict() for evidence_record in evidence_records],
    )
    _write_run_summary(
        run_dir=run_dir,
        report=report,
        site_config=site_config,
        best_filename=best_filename,
        review_images_generated=review_images_generated,
        pixel_change_enabled=pixel_change_enabled,
        pixel_change_adapter_source=pixel_change_adapter_source,
        riverbank_crossing_enabled=riverbank_crossing_enabled,
        riverbank_crossing_adapter_source=riverbank_crossing_adapter_source,
        display_name=read_display_name(sequence_dir),
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
    _write_gauge_evidence(
        run_dir=run_dir,
        sequence_dir=sequence_dir,
        baseline_record=baseline_record,
        records=records,
    )
    _freeze_water_level_selection(run_dir, sequence_dir)

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


def resolve_run_config_snapshot(
    site_dir: Path, run_id: str, *, expected_sequence_id: str | None = None
) -> dict[str, Any]:
    """Load the exact watched-area/waterline-guide config one saved run used.

    A run's own comparison images must always reflect what that run was
    scored against, even after the site's live config is later edited —
    this reads the frozen `site-config.snapshot.json` written at run time
    (`_write_inputs_used`), never the current config.

    `run_id` and a caller-supplied `sequence_id` are independent values
    from the same request; pass `expected_sequence_id` to confirm this run
    actually belongs to that sequence before its config is used — a
    mismatch means the caller named one sequence's images alongside a
    different sequence's run, which must not silently render an image
    using the wrong run's watched-area config.
    """

    if not _RUN_ID_PATTERN.fullmatch(run_id or ""):
        raise ImageSequenceValidationError("Run not found.")
    runs_root = (site_dir / "outputs" / "image-sequence-runs").resolve()
    run_dir = (runs_root / run_id).resolve()
    try:
        run_dir.relative_to(runs_root)
    except ValueError as error:
        raise ImageSequenceValidationError("Run not found.") from error
    if expected_sequence_id is not None:
        summary_path = run_dir / "run-summary.json"
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ImageSequenceValidationError("Run not found.") from error
        if not isinstance(summary, dict) or summary.get("sequence_id") != expected_sequence_id:
            raise ImageSequenceValidationError("run_id does not belong to sequence_id.")
    snapshot_path = (run_dir / "inputs-used" / "site-config.snapshot.json").resolve()
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
    evidence_records_path = run_dir / "evidence-records.jsonl"
    evidence_records = (
        read_jsonl_records(evidence_records_path) if evidence_records_path.is_file() else []
    )
    report_path = run_dir / "image-sequence-report.md"
    report_text = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    pilot_evaluation: dict[str, Any] | None = None
    pilot_evaluation_path = run_dir / "riverbank-pilot-evaluation.json"
    if pilot_evaluation_path.is_file():
        try:
            loaded_pilot_evaluation = json.loads(pilot_evaluation_path.read_text(encoding="utf-8"))
            if (
                isinstance(loaded_pilot_evaluation, dict)
                and loaded_pilot_evaluation.get("plugin_id") == _RIVERBANK_CROSSING_PLUGIN_ID
            ):
                pilot_evaluation = loaded_pilot_evaluation
        except (OSError, ValueError):
            pilot_evaluation = None
    review_images: list[str] = []
    review_images_dir = run_dir / "review-images"
    if review_images_dir.is_dir():
        review_images = sorted(path.name for path in review_images_dir.glob("*.png"))

    gauge_evidence = read_run_gauge_evidence(run_dir)
    event_reviews: dict[str, str] = {}
    sequence_id = summary.get("sequence_id") if isinstance(summary, dict) else None
    if isinstance(sequence_id, str) and sequence_id:
        sequence_dir = site_dir / "inputs" / "image-sequences" / sequence_id
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
        "gauge_evidence": gauge_evidence,
        "gauge_series": legacy_gauge_series(gauge_evidence),
        "water_level_selection": read_run_water_level_selection(run_dir),
        "setup_used": read_run_setup_used(run_dir),
        "event_reviews": event_reviews,
        "evidence_records": evidence_records,
        "pilot_evaluation": pilot_evaluation,
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
    pixel_change_enabled: bool,
    pixel_change_adapter_source: str,
    riverbank_crossing_enabled: bool,
    riverbank_crossing_adapter_source: str,
    display_name: str | None = None,
) -> None:
    summary = {
        "run_id": report.run_id,
        "sequence_id": report.sequence_id,
        "sequence_display_name": display_name,
        "sequence_label": sequence_label(report.sequence_id, display_name),
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
        # The resolved adapter configuration this run actually used, so a
        # historical run stays reproducible/auditable even after Settings
        # change later -- see docs/architecture/plugin-evidence-architecture.md.
        "effective_evidence_adapters": [
            {
                "plugin_id": _PIXEL_CHANGE_PLUGIN_ID,
                "plugin_version": _PIXEL_CHANGE_PLUGIN_VERSION,
                "enabled": pixel_change_enabled,
                "source": pixel_change_adapter_source,
            },
            {
                "plugin_id": _RIVERBANK_CROSSING_PLUGIN_ID,
                "plugin_version": _RIVERBANK_CROSSING_PLUGIN_VERSION,
                "enabled": riverbank_crossing_enabled,
                "source": riverbank_crossing_adapter_source,
            },
        ],
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


def _write_gauge_evidence(
    *,
    run_dir: Path,
    sequence_dir: Path,
    baseline_record: dict[str, Any],
    records: list[ImageSequenceRecord],
) -> None:
    """Freeze this run's per-image gauge matches inside the run folder.

    Matching happens once, here, against the sequence's saved gauge source;
    the source file itself is also copied in (and hashed) so the match can be
    audited later. After this, nothing about the run reads the sequence-level
    gauge files again: a later download, a corrected USGS value, or a
    registry change can only affect a NEW run.
    """

    images: list[dict[str, Any]] = [
        {
            "filename": str(baseline_record["filename"]),
            "captured_at_utc": str(baseline_record.get("captured_at_utc", "")),
            "local_time": str(baseline_record.get("local_time", "")),
            "download_status": "downloaded",
            "is_baseline": True,
            "change_score": None,
        }
    ]
    images.extend(
        {
            "filename": record.filename,
            "captured_at_utc": record.captured_at_utc,
            "local_time": record.local_time,
            "download_status": record.download_status,
            "is_baseline": False,
            # This run's own score for this exact image -- never another's.
            "change_score": record.region_change_score,
        }
        for record in records
    )

    # Read the source once: the bytes that are parsed, hashed, and saved are
    # the same bytes, so a concurrent download cannot make them disagree.
    try:
        source_bytes: bytes | None = (sequence_dir / GAUGE_SOURCE_FILENAME).read_bytes()
    except OSError:
        source_bytes = None
    source = parse_gauge_source(source_bytes) if source_bytes is not None else None
    source_sha256 = (
        hashlib.sha256(source_bytes).hexdigest()
        if source_bytes is not None and source is not None
        else None
    )
    # Matches saved when each image was added are reused as they are, so a later append
    # (which can bring a closer reading into the sequence) never changes an earlier match.
    fixed_matches = load_gauge_matches(sequence_dir)
    evidence = build_run_gauge_evidence(
        source, images, source_sha256=source_sha256, fixed_matches=fixed_matches
    )
    (run_dir / RUN_GAUGE_EVIDENCE_FILENAME).write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
    if source is not None and source_bytes is not None:
        (run_dir / "inputs-used" / "gauge-readings.snapshot.json").write_bytes(source_bytes)
    if fixed_matches:
        used = {str(image["filename"]) for image in images}
        (run_dir / "inputs-used" / "gauge-matches.snapshot.json").write_text(
            json.dumps(
                {"matches": {k: v for k, v in sorted(fixed_matches.items()) if k in used}},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def _freeze_water_level_selection(run_dir: Path, sequence_dir: Path) -> None:
    """Copy the sequence's sampling batches into the run, byte for byte.

    The collection-group badges shown in review come from this frozen copy, so they
    cannot change when a later append adds batches, or if a sequence file is replaced.
    A run sees exactly the batches that existed when it started.
    """

    target = run_dir / "inputs-used" / WATER_LEVEL_SAMPLING_SNAPSHOT_DIR
    legacy = sequence_dir / WATER_LEVEL_SELECTION_FILENAME
    batches = sequence_dir / "sampling-batches"
    copied = False
    if legacy.is_file():
        target.mkdir(parents=True, exist_ok=True)
        (target / WATER_LEVEL_SELECTION_FILENAME).write_bytes(legacy.read_bytes())
        copied = True
    if batches.is_dir():
        for path in sorted(batches.glob("batch-*.json")):
            (target / "sampling-batches").mkdir(parents=True, exist_ok=True)
            (target / "sampling-batches" / path.name).write_bytes(path.read_bytes())
            copied = True
    if not copied:
        return


def read_run_setup_used(run_dir: Path) -> dict[str, Any]:
    """The watched area and human guides this run was made with (its frozen config copy).

    Drawn over overlay comparisons so they always match the saved run, never a guide
    edited afterward. Empty values when the run has no readable snapshot.
    """

    try:
        snapshot = json.loads(
            (run_dir / "inputs-used" / "site-config.snapshot.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        snapshot = {}
    guides = snapshot.get("normal_waterline_guides") if isinstance(snapshot, dict) else None
    return {
        "reference_region": snapshot.get("reference_region")
        if isinstance(snapshot, dict)
        else None,
        "normal_waterline_guides": [
            {"id": g.get("id"), "status": g.get("status"), "points": g.get("points")}
            for g in (guides if isinstance(guides, list) else [])
            if isinstance(g, dict)
        ],
    }


def read_run_water_level_selection(run_dir: Path) -> dict[str, Any] | None:
    """The run's frozen sampling record by file name, or None (a sequence with no batches).

    Reads only the run's own frozen copy: every batch the sequence had when the run
    started, each image attributed to the batch that first added it. Runs made before
    batches existed fall back to their single frozen selection file.
    """

    frozen = run_dir / "inputs-used" / WATER_LEVEL_SAMPLING_SNAPSHOT_DIR
    batches = read_batches(frozen) if frozen.is_dir() else []
    if not batches:
        legacy = run_dir / "inputs-used" / WATER_LEVEL_SELECTION_SNAPSHOT
        try:
            loaded = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(loaded, dict):
            return None
        batches = [{"batch_number": 0, "legacy": True, **loaded}]
    first = batches[0]
    samples = {
        name: {
            "group": sample.get("group"),
            "motivating_reading": sample.get("motivating_reading"),
            "image_reading": sample.get("image_reading"),
            "gap_seconds": sample.get("gap_seconds"),
            "image_reading_gap_seconds": sample.get("image_reading_gap_seconds"),
            "readings_differ": sample.get("readings_differ"),
            "batch_number": sample.get("batch_number"),
        }
        for name, sample in samples_by_filename(batches).items()
    }
    return {
        "policy_version": first.get("policy_version"),
        "selected_at_utc": first.get("selected_at_utc"),
        "note": first.get("note"),
        "request": first.get("request"),
        "association": first.get("association"),
        "gauge": first.get("gauge"),
        "batch_count": len(batches),
        "batches": [
            {
                "batch_number": b.get("batch_number"),
                "selected_at_utc": b.get("selected_at_utc"),
                "request": b.get("request"),
                "policy_version": b.get("policy_version"),
                "thresholds": b.get("thresholds"),
            }
            for b in batches
        ],
        "samples": samples,
    }


def read_run_gauge_evidence(run_dir: Path) -> dict[str, Any]:
    """The run's frozen gauge evidence, or an explicit "not captured" state.

    A run made before gauge evidence was saved with runs has no such file.
    That is reported as exactly that -- never rebuilt from today's sequence
    files or a live fetch, which would rewrite what the run actually showed.
    """

    path = run_dir / RUN_GAUGE_EVIDENCE_FILENAME
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None
        if isinstance(loaded, dict):
            return loaded
    return {
        "schema_version": 1,
        "captured": False,
        "status": "not_captured",
        "reason": (
            "Gauge evidence was not captured for this run. It was made before runs "
            "saved gauge matches, and past runs are not reconstructed from newer data."
        ),
        "images": [],
        "peak_events": None,
    }


def legacy_gauge_series(gauge_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per matched image from the frozen evidence, for older review pages.

    Built only from the run's own saved records. The old date-keyed pages
    still need a `date`; the newer console reads `gauge_evidence` directly.
    """

    rows: list[dict[str, Any]] = []
    for image in gauge_evidence.get("images", []):
        reading = image.get("reading")
        if not isinstance(reading, dict):
            continue
        rows.append(
            {
                "date": str(image.get("captured_at_utc", ""))[:10],
                "local_time": image.get("local_time"),
                "captured_at_utc": image.get("captured_at_utc"),
                "gauge_datetime_utc": reading.get("datetime_utc"),
                "gauge_value": reading.get("value"),
                "time_difference_seconds": image.get("time_difference_seconds"),
                "qualifiers": reading.get("qualifiers"),
                "quality_status": reading.get("quality_status"),
                "parameter_code": reading.get("parameter_code"),
                "parameter_label": reading.get("parameter_label"),
                "unit": reading.get("unit"),
                "used_fallback_discharge": reading.get("used_fallback_discharge"),
            }
        )
    return rows

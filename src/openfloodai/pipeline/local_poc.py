"""Local proof-of-concept pipeline for saved test records."""

from __future__ import annotations

import math
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import cast
from uuid import uuid4

import cv2

from openfloodai.config import ReferenceRegion, load_site_config
from openfloodai.contracts import write_jsonl_records
from openfloodai.evidence.adapters.pixel_change import (
    PLUGIN_ID as _PIXEL_CHANGE_PLUGIN_ID,
)
from openfloodai.evidence.adapters.pixel_change import (
    PLUGIN_VERSION as _PIXEL_CHANGE_PLUGIN_VERSION,
)
from openfloodai.evidence.adapters.pixel_change import evidence_from_pixel_change_signal
from openfloodai.evidence.contract import build_unavailable_evidence
from openfloodai.evidence.settings import (
    EvidenceSettingsError,
    resolve_adapter_setting_source,
    resolve_effective_adapter_settings,
)
from openfloodai.ingestion import check_video_file_health, read_video_metadata
from openfloodai.ingestion.evidence_sampling import (
    SamplingSettings,
    frame_second,
    sample_indices,
    window_evidence,
)
from openfloodai.risk_engine import evaluate_risk_state
from openfloodai.vision import (
    compare_frames,
    compare_region_signals,
)
from openfloodai.vision.simple_signals import FrameArray

PipelineRecord = dict[str, object]


class LocalPocPipelineError(RuntimeError):
    """Raised when the local POC pipeline cannot complete a usable-video run."""


def run_local_poc_pipeline(
    video_path: Path,
    site_id: str,
    camera_id: str,
    output_path: Path,
    *,
    time_windows: list[tuple[float, float]] | None = None,
    sampling: SamplingSettings | None = None,
) -> dict[str, object]:
    """Measure time-spaced full-frame evidence for local review."""

    return _run_pipeline(
        video_path,
        site_id,
        camera_id,
        output_path,
        time_windows=time_windows,
        sampling=sampling,
    )


def run_local_region_poc_pipeline(
    video_path: Path,
    config_path: Path,
    output_path: Path,
    *,
    time_windows: list[tuple[float, float]] | None = None,
    sampling: SamplingSettings | None = None,
) -> dict[str, object]:
    """Measure time-spaced evidence inside the configured reference region."""

    config = load_site_config(config_path)
    if config.input_type != "local_video":
        raise LocalPocPipelineError("Region POC pipeline currently supports local_video input only")
    if config.reference_region is None:
        raise LocalPocPipelineError("Region POC pipeline requires a reference_region")
    # config_path is always <site_dir>/configs/<name>.json (see _find_config_path),
    # and the reference directory is a sibling of the sites directory itself --
    # matching home_server.py's own _reference_dir() and
    # image_sequence_runner.py's identical convention.
    site_dir = config_path.parent.parent
    reference_dir = site_dir.parent.parent / "reference"
    summary = _run_pipeline(
        video_path,
        config.site_id,
        config.camera_id,
        output_path,
        time_windows=time_windows,
        sampling=sampling,
        region=config.reference_region,
        reference_dir=reference_dir,
        site_evidence_adapter_overrides=config.evidence_adapter_overrides,
    )
    summary.update(reference_region_used=True, config_path=str(config_path))
    return summary


def _run_pipeline(
    video_path: Path,
    site_id: str,
    camera_id: str,
    output_path: Path,
    *,
    time_windows: list[tuple[float, float]] | None,
    sampling: SamplingSettings | None,
    region: ReferenceRegion | None = None,
    reference_dir: Path | None = None,
    site_evidence_adapter_overrides: Mapping[str, bool] | None = None,
) -> dict[str, object]:
    settings = sampling or SamplingSettings()
    for start, end in time_windows or []:
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError("Time windows must have finite times with 0 <= start < end")
    health = check_video_file_health(video_path, site_id=site_id, camera_id=camera_id)
    records = [health]
    if health["input_quality_state"] != "USABLE":
        _write_run_records(output_path, records)
        return _build_pipeline_summary(output_path, records, completed=False)

    # Same adapter, same pattern as image_sequence_runner.py: resolved once
    # per run (site override > global setting > catalog default), not
    # per-pair -- it can't change mid-run. Only meaningful when there's a
    # reference region: the whole-frame compare_frames() path (region=None)
    # has no adapter identity yet and is untouched by this.
    pixel_change_enabled = True
    pixel_change_adapter_source = "catalog_default"
    if region is not None and reference_dir is not None:
        try:
            pixel_change_enabled = resolve_effective_adapter_settings(
                reference_dir, site_overrides=site_evidence_adapter_overrides
            )[_PIXEL_CHANGE_PLUGIN_ID]
            pixel_change_adapter_source = resolve_adapter_setting_source(
                reference_dir,
                _PIXEL_CHANGE_PLUGIN_ID,
                site_overrides=site_evidence_adapter_overrides,
            )
        except EvidenceSettingsError as error:
            raise LocalPocPipelineError(
                f"Could not read evidence adapter settings: {error}"
            ) from error

    metadata = read_video_metadata(video_path, site_id=site_id, camera_id=camera_id)
    for record in metadata:
        brightness = cast(float, record["mean_brightness"])
        reasons = []
        if brightness < settings.minimum_brightness:
            reasons.append("IMAGE_TOO_DARK")
        if "frame_rate" not in record:
            reasons.append("VIDEO_TIME_UNKNOWN")
        record["input_quality_state"] = "DEGRADED" if reasons else "USABLE"
        record["reason_codes"] = reasons or ["INPUT_USABLE"]
        record["minimum_brightness"] = settings.minimum_brightness
    records.extend(metadata)
    fps = cast(float, metadata[0].get("frame_rate", 1.0))
    duration = frame_second(metadata[-1]) + 1 / fps
    windows = sorted(set(time_windows or [(0.0, duration)]))
    for window in windows:
        evidence = window_evidence(metadata, window, settings)
        indices = sample_indices(metadata, window, settings)
        times = [frame_second(metadata[i]) for i in indices]
        evidence.update(
            contract_version="v1",
            record_type="evidence_window_output",
            record_id=f"evidence-{uuid4()}",
            site_id=site_id,
            camera_id=camera_id,
            timestamp=health["timestamp"],
            sampled_frame_indices=indices,
            sampled_video_times=times,
            actual_max_sample_gap_seconds=max(
                (b - a for a, b in zip(times, times[1:], strict=False)),
                default=0.0,
            ),
        )
        records.append(evidence)
        if len(indices) < 2:
            continue
        frames = read_selected_frames(video_path, indices)
        pairs = [(indices[i - 1], indices[i]) for i in range(1, len(indices))]
        pairs += [(indices[0], i) for i in indices[2:]]
        for before, after in pairs:
            source_ids = [str(metadata[i]["record_id"]) for i in (before, after)]
            timestamp = str(metadata[after]["timestamp"])
            timing: PipelineRecord = {
                "video_time_seconds": frame_second(metadata[after]),
                "comparison_start_seconds": frame_second(metadata[before]),
                "comparison_end_seconds": frame_second(metadata[after]),
                "baseline_frame_index": before,
                "changed_frame_index": after,
                "evidence_window_seconds": list(window),
                "coverage_sufficient": evidence["coverage_sufficient"],
            }
            pair_health = dict(health)
            if evidence["coverage_sufficient"] is not True:
                pair_health.update(
                    input_quality_state="UNKNOWN",
                    is_usable=False,
                    reason_codes=["INSUFFICIENT_TIME_COVERAGE"],
                )

            if region is not None and not pixel_change_enabled:
                # Disabled means disabled: no comparison is attempted at all, and
                # the risk state is UNKNOWN, never a fabricated NORMAL/WATCH --
                # matching "missing evidence is not normal evidence".
                disabled_evidence = build_unavailable_evidence(
                    plugin_id=_PIXEL_CHANGE_PLUGIN_ID,
                    plugin_version=_PIXEL_CHANGE_PLUGIN_VERSION,
                    plugin_family="observation",
                    site_id=site_id,
                    camera_id=camera_id,
                    evidence_type="region_pixel_change_score",
                    status="disabled",
                    reason_codes=("ADAPTER_DISABLED",),
                    timestamp=timestamp,
                )
                records.append(disabled_evidence.to_dict())
                risk = _disabled_risk_state(
                    site_id=site_id, camera_id=camera_id, timestamp=timestamp
                )
                risk.update(timing)
                risk["source_record_ids"] = [disabled_evidence.record_id]
                records.append(risk)
                continue

            pixel_change_evidence = None
            if region is not None:
                visual = compare_region_signals(
                    frames[before],
                    frames[after],
                    region,
                    site_id=site_id,
                    camera_id=camera_id,
                    timestamp=timestamp,
                    source_record_ids=source_ids,
                )
                # Build the evidence record once, from the same output already
                # computed above -- not a second, independent read of it later.
                pixel_change_evidence = evidence_from_pixel_change_signal(
                    visual, site_id=site_id, camera_id=camera_id
                )
                records.append(pixel_change_evidence.to_dict())
            else:
                visual = compare_frames(
                    frames[before],
                    frames[after],
                    site_id=site_id,
                    camera_id=camera_id,
                    timestamp=timestamp,
                    source_record_ids=source_ids,
                )
            visual.update(timing)
            records.append(visual)
            risk_input = dict(visual)
            if pixel_change_evidence is not None:
                risk_input["risk_signal_score"] = pixel_change_evidence.value
            else:
                risk_input.setdefault("risk_signal_score", visual.get("region_change_score", 0.0))
            risk = evaluate_risk_state(pair_health, risk_input)
            risk.update(timing)
            risk["source_record_ids"] = [visual["record_id"]]
            records.append(risk)
    _write_run_records(output_path, records)
    return _build_pipeline_summary(
        output_path,
        records,
        completed=True,
        effective_evidence_adapters=(
            [
                {
                    "plugin_id": _PIXEL_CHANGE_PLUGIN_ID,
                    "plugin_version": _PIXEL_CHANGE_PLUGIN_VERSION,
                    "enabled": pixel_change_enabled,
                    "source": pixel_change_adapter_source,
                }
            ]
            if region is not None
            else []
        ),
    )


def _disabled_risk_state(*, site_id: str, camera_id: str, timestamp: str) -> PipelineRecord:
    """A risk_state_output record for when the adapter is disabled, not evaluated.

    Matches risk_engine.rule_based._build_result()'s shape without calling
    evaluate_risk_state() at all -- that function has no "signal
    unavailable" path (it either judges from a real score or reports
    UNKNOWN via a health failure, which this isn't), and inventing one
    inside it is a separate, later decision. Building this record directly
    keeps evaluate_risk_state() itself completely unchanged.
    """

    return {
        "contract_version": "v1",
        "record_id": f"risk-state-{uuid4()}",
        "record_type": "risk_state_output",
        "site_id": site_id,
        "camera_id": camera_id,
        "timestamp": timestamp,
        "risk_state": "UNKNOWN",
        "reason_codes": ["ADAPTER_DISABLED"],
        "confidence": 0.0,
        "human_summary": (
            "The pixel-change signal is turned off for this site, so risk cannot be judged."
        ),
    }


def read_selected_frames(video_path: Path, indices: list[int]) -> dict[int, FrameArray]:
    """Decode exact frame indices; retain only the requested images in memory."""

    wanted = set(indices)
    result: dict[int, FrameArray] = {}
    capture = cv2.VideoCapture(str(video_path))
    try:
        index = 0
        while wanted:
            readable, frame = capture.read()
            if not readable:
                raise LocalPocPipelineError(
                    "Video changed or decoding failed while reading evidence"
                )
            if index in wanted:
                result[index] = cast(FrameArray, frame)
                wanted.remove(index)
            index += 1
    finally:
        capture.release()
    return result


def _build_pipeline_summary(
    output_path: Path,
    records: list[PipelineRecord],
    *,
    completed: bool,
    effective_evidence_adapters: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "completed": completed,
        "output_path": str(output_path),
        "records_written": len(records),
        "record_types": [record["record_type"] for record in records],
        # The resolved adapter configuration this run actually used, so a
        # historical run stays reproducible/auditable even after Settings
        # change later -- same field shape as image_sequence_runner.py's
        # run-summary.json.
        "effective_evidence_adapters": effective_evidence_adapters or [],
    }


def _write_run_records(output_path: Path, records: list[PipelineRecord]) -> None:
    """Replace derived run evidence only after all new records can be written."""

    if output_path.suffix != ".jsonl":
        raise ValueError("Pipeline output must end with .jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_path.parent) as temporary:
        pending = Path(temporary) / "records.jsonl"
        write_jsonl_records(pending, records)
        pending.replace(output_path)

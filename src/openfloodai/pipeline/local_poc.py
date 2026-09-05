"""Local proof-of-concept pipeline for saved test records."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import cast
from uuid import uuid4

import cv2

from openfloodai.config import ReferenceRegion, load_site_config
from openfloodai.contracts import write_jsonl_records
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
    summary = _run_pipeline(
        video_path,
        config.site_id,
        config.camera_id,
        output_path,
        time_windows=time_windows,
        sampling=sampling,
        region=config.reference_region,
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
            else:
                visual = compare_frames(
                    frames[before],
                    frames[after],
                    site_id=site_id,
                    camera_id=camera_id,
                    timestamp=timestamp,
                    source_record_ids=source_ids,
                )
            timing: PipelineRecord = {
                "video_time_seconds": frame_second(metadata[after]),
                "comparison_start_seconds": frame_second(metadata[before]),
                "comparison_end_seconds": frame_second(metadata[after]),
                "baseline_frame_index": before,
                "changed_frame_index": after,
                "evidence_window_seconds": list(window),
                "coverage_sufficient": evidence["coverage_sufficient"],
            }
            visual.update(timing)
            records.append(visual)
            risk_input = dict(visual)
            risk_input.setdefault("risk_signal_score", visual.get("region_change_score", 0.0))
            pair_health = dict(health)
            if evidence["coverage_sufficient"] is not True:
                pair_health.update(
                    input_quality_state="UNKNOWN",
                    is_usable=False,
                    reason_codes=["INSUFFICIENT_TIME_COVERAGE"],
                )
            risk = evaluate_risk_state(pair_health, risk_input)
            risk.update(timing)
            risk["source_record_ids"] = [visual["record_id"]]
            records.append(risk)
    _write_run_records(output_path, records)
    return _build_pipeline_summary(output_path, records, completed=True)


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
) -> dict[str, object]:
    return {
        "completed": completed,
        "output_path": str(output_path),
        "records_written": len(records),
        "record_types": [record["record_type"] for record in records],
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

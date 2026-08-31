"""Local proof-of-concept pipeline for saved test records."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import cv2

from openfloodai.config import ReferenceRegion, load_site_config
from openfloodai.contracts import write_jsonl_records
from openfloodai.ingestion import check_video_file_health, read_video_metadata
from openfloodai.risk_engine import evaluate_risk_state
from openfloodai.vision import (
    compare_frames,
    compare_region_signals,
    extract_frame_signals,
    extract_region_signals,
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
) -> dict[str, object]:
    """Run the local POC flow and save output records to a JSON Lines file."""

    records: list[PipelineRecord] = []
    health_record = check_video_file_health(video_path, site_id=site_id, camera_id=camera_id)
    records.append(health_record)

    if health_record["input_quality_state"] != "USABLE":
        write_jsonl_records(output_path, records)
        return _build_pipeline_summary(output_path, records, completed=False)

    frame_metadata_records = read_video_metadata(video_path, site_id=site_id, camera_id=camera_id)
    records.extend(frame_metadata_records)

    frames = _read_first_frames(video_path, count=2)
    if not frames:
        raise LocalPocPipelineError("Usable video produced no readable frames during pipeline run")

    visual_signal_record = _build_visual_signal_record(
        frames=frames,
        site_id=site_id,
        camera_id=camera_id,
        frame_metadata_records=frame_metadata_records,
    )
    records.append(visual_signal_record)

    risk_input_record = dict(visual_signal_record)
    risk_input_record.setdefault("risk_signal_score", 0.0)
    risk_state_record = evaluate_risk_state(health_record, risk_input_record)
    records.append(risk_state_record)

    write_jsonl_records(output_path, records)
    return _build_pipeline_summary(output_path, records, completed=True)


def run_local_region_poc_pipeline(
    video_path: Path,
    config_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Run the local POC flow using the configured reference region."""

    site_config = load_site_config(config_path)
    if site_config.input_type != "local_video":
        raise LocalPocPipelineError("Region POC pipeline currently supports local_video input only")
    if site_config.reference_region is None:
        raise LocalPocPipelineError("Region POC pipeline requires a reference_region in config")

    records: list[PipelineRecord] = []
    health_record = check_video_file_health(
        video_path,
        site_id=site_config.site_id,
        camera_id=site_config.camera_id,
    )
    records.append(health_record)

    if health_record["input_quality_state"] != "USABLE":
        write_jsonl_records(output_path, records)
        return _build_pipeline_summary(output_path, records, completed=False)

    frame_metadata_records = read_video_metadata(
        video_path,
        site_id=site_config.site_id,
        camera_id=site_config.camera_id,
    )
    records.extend(frame_metadata_records)

    frames = _read_first_frames(video_path, count=2)
    if not frames:
        raise LocalPocPipelineError("Usable video produced no readable frames during pipeline run")

    visual_signal_record = _build_region_visual_signal_record(
        frames=frames,
        site_id=site_config.site_id,
        camera_id=site_config.camera_id,
        frame_metadata_records=frame_metadata_records,
        reference_region=site_config.reference_region,
    )
    records.append(visual_signal_record)

    risk_input_record = dict(visual_signal_record)
    risk_input_record.setdefault(
        "risk_signal_score",
        visual_signal_record.get("region_change_score", 0.0),
    )
    risk_state_record = evaluate_risk_state(health_record, risk_input_record)
    records.append(risk_state_record)

    write_jsonl_records(output_path, records)
    summary = _build_pipeline_summary(output_path, records, completed=True)
    summary["reference_region_used"] = True
    summary["config_path"] = str(config_path)
    return summary


def _read_first_frames(video_path: Path, *, count: int) -> list[FrameArray]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise LocalPocPipelineError(f"Video file could not be opened: {video_path}")

    frames: list[FrameArray] = []
    try:
        while len(frames) < count:
            is_readable, frame = capture.read()
            if not is_readable:
                break
            frames.append(cast(FrameArray, frame))
    finally:
        capture.release()

    return frames


def _build_visual_signal_record(
    *,
    frames: list[FrameArray],
    site_id: str,
    camera_id: str,
    frame_metadata_records: list[PipelineRecord],
) -> PipelineRecord:
    source_record_ids = [
        str(record["record_id"])
        for record in frame_metadata_records[: len(frames)]
        if "record_id" in record
    ]
    timestamp = str(
        frame_metadata_records[min(len(frames) - 1, len(frame_metadata_records) - 1)]["timestamp"]
    )

    if len(frames) >= 2:
        return compare_frames(
            frames[0],
            frames[1],
            site_id=site_id,
            camera_id=camera_id,
            timestamp=timestamp,
            source_record_ids=source_record_ids,
        )

    return extract_frame_signals(
        frames[0],
        site_id=site_id,
        camera_id=camera_id,
        timestamp=timestamp,
        source_record_ids=source_record_ids,
    )


def _build_region_visual_signal_record(
    *,
    frames: list[FrameArray],
    site_id: str,
    camera_id: str,
    frame_metadata_records: list[PipelineRecord],
    reference_region: ReferenceRegion,
) -> PipelineRecord:
    source_record_ids = [
        str(record["record_id"])
        for record in frame_metadata_records[: len(frames)]
        if "record_id" in record
    ]
    timestamp = str(
        frame_metadata_records[min(len(frames) - 1, len(frame_metadata_records) - 1)]["timestamp"]
    )

    if len(frames) >= 2:
        return compare_region_signals(
            frames[0],
            frames[1],
            reference_region,
            site_id=site_id,
            camera_id=camera_id,
            timestamp=timestamp,
            source_record_ids=source_record_ids,
        )

    return extract_region_signals(
        frames[0],
        reference_region,
        site_id=site_id,
        camera_id=camera_id,
        timestamp=timestamp,
        source_record_ids=source_record_ids,
    )


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

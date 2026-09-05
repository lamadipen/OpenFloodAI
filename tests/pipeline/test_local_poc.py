from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from openfloodai.contracts import read_jsonl_records
from openfloodai.pipeline import LocalPocPipelineError, run_local_poc_pipeline
from openfloodai.pipeline.local_poc import run_local_region_poc_pipeline


def create_tiny_video(path: Path, *, frame_count: int = 2) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 2.0, (8, 8))
    assert writer.isOpened(), "test video writer should open"

    try:
        for index in range(frame_count):
            frame = np.full((8, 8, 3), 20 + index * 100, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


def write_site_config(path: Path, *, include_reference_region: bool = True) -> None:
    reference_region = """
  "reference_region": {
    "x": 0,
    "y": 50,
    "width": 100,
    "height": 50
  },
"""
    path.write_text(
        f"""{{
  "site_id": "site-demo-01",
  "camera_id": "camera-demo-01",
  "site_name": "Demo River Bridge",
  "public_location": "Demo River near Example Town",
  "input_type": "local_video",
{reference_region if include_reference_region else ""}
  "privacy_notes": "Broad public location only."
}}
""",
        encoding="utf-8",
    )


def test_local_poc_pipeline_writes_records_for_readable_video(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "records.jsonl"
    create_tiny_video(video_path)

    summary = run_local_poc_pipeline(
        video_path=video_path,
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)
    record_types = [record["record_type"] for record in records]

    assert summary["completed"] is True
    assert summary["records_written"] == len(records)
    assert record_types[0] == "camera_health_output"
    assert "video_frame_metadata" in record_types
    assert "visual_signal_output" in record_types
    assert record_types[-1] == "risk_state_output"
    assert all(record["site_id"] == "site-demo-01" for record in records)
    assert all(record["camera_id"] == "camera-demo-01" for record in records)


def test_local_poc_pipeline_preserves_record_order(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "records.jsonl"
    create_tiny_video(video_path, frame_count=3)

    run_local_poc_pipeline(
        video_path=video_path,
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)
    record_types = [record["record_type"] for record in records]

    assert record_types == [
        "camera_health_output",
        "video_frame_metadata",
        "video_frame_metadata",
        "video_frame_metadata",
        "evidence_window_output",
        "visual_signal_output",
        "risk_state_output",
    ]


def test_local_poc_pipeline_writes_only_health_record_for_missing_video(tmp_path: Path) -> None:
    output_path = tmp_path / "records.jsonl"

    summary = run_local_poc_pipeline(
        video_path=tmp_path / "missing.avi",
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)

    assert summary["completed"] is False
    assert summary["records_written"] == 1
    assert records[0]["record_type"] == "camera_health_output"
    assert records[0]["input_quality_state"] == "UNKNOWN"
    assert records[0]["reason_codes"] == ["INPUT_UNKNOWN"]


def test_local_poc_pipeline_writes_only_health_record_for_unreadable_video(tmp_path: Path) -> None:
    video_path = tmp_path / "not-a-video.avi"
    output_path = tmp_path / "records.jsonl"
    video_path.write_text("not real video", encoding="utf-8")

    summary = run_local_poc_pipeline(
        video_path=video_path,
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)

    assert summary["completed"] is False
    assert summary["records_written"] == 1
    assert records[0]["record_type"] == "camera_health_output"
    assert records[0]["input_quality_state"] == "UNKNOWN"
    assert records[0]["failure_detail"] == "video_file_unreadable"


def test_local_region_poc_pipeline_writes_region_signal_records(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    config_path = tmp_path / "site-config.json"
    output_path = tmp_path / "region-records.jsonl"
    create_tiny_video(video_path)
    write_site_config(config_path)

    summary = run_local_region_poc_pipeline(
        video_path=video_path,
        config_path=config_path,
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)
    visual_records = [
        record for record in records if record["record_type"] == "visual_signal_output"
    ]

    assert summary["completed"] is True
    assert summary["reference_region_used"] is True
    assert summary["config_path"] == str(config_path)
    assert len(visual_records) == 1
    assert visual_records[0]["reference_region_used"] is True
    assert visual_records[0]["region_x"] == 0.0
    assert visual_records[0]["region_y"] == 4.0
    assert visual_records[0]["region_width"] == 8.0
    assert visual_records[0]["region_height"] == 4.0
    assert "region_change_score" in visual_records[0]
    assert all(record["site_id"] == "site-demo-01" for record in records)
    assert all(record["camera_id"] == "camera-demo-01" for record in records)


def test_local_region_poc_pipeline_keeps_old_pipeline_shape_separate(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "records.jsonl"
    create_tiny_video(video_path)

    run_local_poc_pipeline(
        video_path=video_path,
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)
    visual_records = [
        record for record in records if record["record_type"] == "visual_signal_output"
    ]

    assert len(visual_records) == 1
    assert "frame_change_score" in visual_records[0]
    assert "region_change_score" not in visual_records[0]


def test_local_region_poc_pipeline_requires_reference_region(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    config_path = tmp_path / "site-config.json"
    output_path = tmp_path / "region-records.jsonl"
    create_tiny_video(video_path)
    write_site_config(config_path, include_reference_region=False)

    with pytest.raises(LocalPocPipelineError, match="requires a reference_region"):
        run_local_region_poc_pipeline(
            video_path=video_path,
            config_path=config_path,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_local_region_poc_pipeline_writes_health_only_for_missing_video(tmp_path: Path) -> None:
    config_path = tmp_path / "site-config.json"
    output_path = tmp_path / "region-records.jsonl"
    write_site_config(config_path)

    summary = run_local_region_poc_pipeline(
        video_path=tmp_path / "missing.avi",
        config_path=config_path,
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)

    assert summary["completed"] is False
    assert summary["records_written"] == 1
    assert records[0]["record_type"] == "camera_health_output"
    assert records[0]["input_quality_state"] == "UNKNOWN"

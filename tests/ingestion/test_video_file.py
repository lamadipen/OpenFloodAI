from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from openfloodai.ingestion.video_file import (
    VideoIngestionError,
    iter_video_frame_metadata,
    read_video_metadata,
)


def create_tiny_video(path: Path, *, frame_count: int = 3, frame_rate: float = 2.0) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(
        str(path),
        fourcc,
        frame_rate,
        (8, 8),
    )
    assert writer.isOpened(), "test video writer should open"

    try:
        for index in range(frame_count):
            frame = np.full((8, 8, 3), index * 40, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


def test_read_video_metadata_returns_frame_records(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    start_time = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    create_tiny_video(video_path)

    records = read_video_metadata(
        video_path,
        site_id="site-bridge-01",
        camera_id="camera-bridge-01-main",
        start_time=start_time,
    )

    assert len(records) == 3
    assert records[0]["contract_version"] == "v1"
    assert records[0]["record_type"] == "video_frame_metadata"
    assert records[0]["site_id"] == "site-bridge-01"
    assert records[0]["camera_id"] == "camera-bridge-01-main"
    assert records[0]["timestamp"] == "2026-08-28T12:00:00+00:00"
    assert records[0]["frame_id"] == "frame-000000"
    assert records[0]["frame_width"] == 8
    assert records[0]["frame_height"] == 8
    assert records[0]["frame_rate"] == 2.0
    assert isinstance(records[0]["frame_hash"], str)
    assert records[0]["dropped_frame_count"] == 0


def test_iter_video_frame_metadata_yields_records(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    create_tiny_video(video_path, frame_count=2)

    records = list(
        iter_video_frame_metadata(
            video_path,
            site_id="site-bridge-01",
            camera_id="camera-bridge-01-main",
            start_time=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        )
    )

    assert [record["frame_id"] for record in records] == ["frame-000000", "frame-000001"]


def test_missing_video_file_fails_clearly(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.avi"

    with pytest.raises(FileNotFoundError, match="Video file does not exist"):
        read_video_metadata(
            missing_path,
            site_id="site-bridge-01",
            camera_id="camera-bridge-01-main",
        )


def test_unreadable_video_file_fails_clearly(tmp_path: Path) -> None:
    unreadable_path = tmp_path / "not-a-video.avi"
    unreadable_path.write_text("not real video", encoding="utf-8")

    with pytest.raises(VideoIngestionError, match="could not be opened|no readable frames"):
        read_video_metadata(
            unreadable_path,
            site_id="site-bridge-01",
            camera_id="camera-bridge-01-main",
        )


def test_empty_site_id_fails_clearly(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    create_tiny_video(video_path)

    with pytest.raises(ValueError, match="site_id must be non-empty"):
        read_video_metadata(video_path, site_id="", camera_id="camera-bridge-01-main")


def test_naive_start_time_fails_clearly(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    create_tiny_video(video_path)

    with pytest.raises(ValueError, match="start_time must include timezone"):
        read_video_metadata(
            video_path,
            site_id="site-bridge-01",
            camera_id="camera-bridge-01-main",
            start_time=datetime(2026, 8, 28, 12, 0),
        )

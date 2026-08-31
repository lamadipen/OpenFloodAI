from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import pytest

from openfloodai.ingestion import FeedHealthError, check_video_file_health


def create_tiny_video(path: Path) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 2.0, (8, 8))
    assert writer.isOpened(), "test video writer should open"

    try:
        writer.write(np.full((8, 8, 3), 80, dtype=np.uint8))
    finally:
        writer.release()


def test_readable_video_produces_usable_health_record(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    timestamp = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    create_tiny_video(video_path)

    record = check_video_file_health(
        video_path,
        site_id="site-bridge-01",
        camera_id="camera-bridge-01-main",
        timestamp=timestamp,
    )

    assert record["contract_version"] == "v1"
    assert str(record["record_id"]).startswith("camera-health-")
    assert record["record_type"] == "camera_health_output"
    assert record["site_id"] == "site-bridge-01"
    assert record["camera_id"] == "camera-bridge-01-main"
    assert record["timestamp"] == "2026-08-31T12:00:00+00:00"
    assert record["input_quality_state"] == "USABLE"
    assert record["is_usable"] is True
    assert record["reason_codes"] == ["INPUT_USABLE"]
    assert "readable frame" in str(record["human_summary"])


def test_missing_video_produces_unknown_health_record(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.avi"

    record = check_video_file_health(
        missing_path,
        site_id="site-bridge-01",
        camera_id="camera-bridge-01-main",
    )

    assert record["record_type"] == "camera_health_output"
    assert record["input_quality_state"] == "UNKNOWN"
    assert record["is_usable"] is False
    assert record["reason_codes"] == ["INPUT_UNKNOWN"]
    assert record["failure_detail"] == "video_file_missing"


def test_unreadable_video_produces_non_ok_health_record(tmp_path: Path) -> None:
    unreadable_path = tmp_path / "not-a-video.avi"
    unreadable_path.write_text("not real video", encoding="utf-8")

    record = check_video_file_health(
        unreadable_path,
        site_id="site-bridge-01",
        camera_id="camera-bridge-01-main",
    )

    assert record["input_quality_state"] == "UNKNOWN"
    assert record["is_usable"] is False
    assert record["reason_codes"] == ["INPUT_UNKNOWN"]
    assert record["failure_detail"] == "video_file_unreadable"


def test_empty_video_produces_unknown_record_if_opened_without_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_path = tmp_path / "empty.avi"
    video_path.write_text("placeholder", encoding="utf-8")

    class EmptyCapture:
        def isOpened(self) -> bool:
            return True

        def read(self) -> tuple[bool, None]:
            return False, None

        def release(self) -> None:
            return None

    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: EmptyCapture())

    record = check_video_file_health(
        video_path,
        site_id="site-bridge-01",
        camera_id="camera-bridge-01-main",
    )

    assert record["input_quality_state"] == "UNKNOWN"
    assert record["is_usable"] is False
    assert record["reason_codes"] == ["MISSING_FRAME"]
    assert record["failure_detail"] == "no_readable_frames"


def test_health_record_confidence_fields_are_plain_json_values(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    create_tiny_video(video_path)

    record = check_video_file_health(video_path, "site-bridge-01", "camera-bridge-01-main")

    reason_codes = cast(list[str], record["reason_codes"])
    assert all(isinstance(reason_code, str) for reason_code in reason_codes)
    assert isinstance(record["human_summary"], str)


def test_empty_site_id_fails_clearly(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    create_tiny_video(video_path)

    with pytest.raises(FeedHealthError, match="site_id must be non-empty"):
        check_video_file_health(video_path, "", "camera-bridge-01-main")


def test_empty_camera_id_fails_clearly(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    create_tiny_video(video_path)

    with pytest.raises(FeedHealthError, match="camera_id must be non-empty"):
        check_video_file_health(video_path, "site-bridge-01", "")


def test_naive_timestamp_fails_clearly(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    create_tiny_video(video_path)

    with pytest.raises(FeedHealthError, match="timestamp must include timezone"):
        check_video_file_health(
            video_path,
            "site-bridge-01",
            "camera-bridge-01-main",
            timestamp=datetime(2026, 8, 31, 12, 0),
        )

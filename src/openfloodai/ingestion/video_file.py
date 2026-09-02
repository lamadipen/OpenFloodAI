"""Read local video files and produce V1 frame metadata records."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2

from openfloodai.common import FrameArray

FrameMetadata = dict[str, object]


class VideoIngestionError(RuntimeError):
    """Raised when a local video file cannot produce readable frame metadata."""


def read_video_metadata(
    video_path: Path,
    site_id: str,
    camera_id: str,
    *,
    start_time: datetime | None = None,
) -> list[FrameMetadata]:
    """Return all frame metadata records for a local video file."""

    return list(
        iter_video_frame_metadata(
            video_path=video_path,
            site_id=site_id,
            camera_id=camera_id,
            start_time=start_time,
        )
    )


def iter_video_frame_metadata(
    video_path: Path,
    site_id: str,
    camera_id: str,
    *,
    start_time: datetime | None = None,
) -> Iterator[FrameMetadata]:
    """Yield V1 video-frame metadata records for a local video file."""

    if not site_id:
        raise ValueError("site_id must be non-empty")
    if not camera_id:
        raise ValueError("camera_id must be non-empty")

    resolved_path = Path(video_path)
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Video file does not exist: {resolved_path}")

    capture = cv2.VideoCapture(str(resolved_path))
    if not capture.isOpened():
        raise VideoIngestionError(f"Video file could not be opened: {resolved_path}")

    try:
        frame_rate = _read_frame_rate(capture)
        frame_width = _read_int_property(capture, cv2.CAP_PROP_FRAME_WIDTH)
        frame_height = _read_int_property(capture, cv2.CAP_PROP_FRAME_HEIGHT)
        base_time = _normalize_start_time(start_time)

        frame_index = 0
        while True:
            is_read, frame = capture.read()
            if not is_read:
                break

            yield _build_frame_metadata(
                site_id=site_id,
                camera_id=camera_id,
                frame_index=frame_index,
                frame=frame,
                frame_rate=frame_rate,
                frame_width=frame_width,
                frame_height=frame_height,
                base_time=base_time,
            )
            frame_index += 1

        if frame_index == 0:
            raise VideoIngestionError(f"Video file has no readable frames: {resolved_path}")
    finally:
        capture.release()


def _build_frame_metadata(
    *,
    site_id: str,
    camera_id: str,
    frame_index: int,
    frame: FrameArray,
    frame_rate: float | None,
    frame_width: int | None,
    frame_height: int | None,
    base_time: datetime,
) -> FrameMetadata:
    timestamp = _frame_timestamp(base_time, frame_index, frame_rate)
    metadata: FrameMetadata = {
        "contract_version": "v1",
        "record_id": f"frame-meta-{uuid4()}",
        "record_type": "video_frame_metadata",
        "site_id": site_id,
        "camera_id": camera_id,
        "timestamp": timestamp.isoformat(),
        "frame_id": f"frame-{frame_index:06d}",
        "frame_hash": _frame_hash(frame),
        "dropped_frame_count": 0,
    }

    _add_optional(metadata, "frame_width", frame_width)
    _add_optional(metadata, "frame_height", frame_height)
    _add_optional(metadata, "frame_rate", frame_rate)
    _add_optional(metadata, "source_timestamp", timestamp.isoformat())

    return metadata


def _frame_timestamp(base_time: datetime, frame_index: int, frame_rate: float | None) -> datetime:
    if frame_rate is None or frame_rate <= 0:
        return base_time
    return base_time + timedelta(seconds=frame_index / frame_rate)


def _frame_hash(frame: FrameArray) -> str:
    return hashlib.sha256(frame.tobytes()).hexdigest()


def _read_frame_rate(capture: cv2.VideoCapture) -> float | None:
    frame_rate = float(capture.get(cv2.CAP_PROP_FPS))
    if frame_rate <= 0:
        return None
    return frame_rate


def _read_int_property(capture: cv2.VideoCapture, property_id: int) -> int | None:
    value = int(capture.get(property_id))
    if value <= 0:
        return None
    return value


def _normalize_start_time(start_time: datetime | None) -> datetime:
    if start_time is None:
        return datetime.now(UTC)
    if start_time.tzinfo is None or start_time.utcoffset() is None:
        raise ValueError("start_time must include timezone information")
    return start_time


def _add_optional(metadata: dict[str, Any], key: str, value: object | None) -> None:
    if value is not None:
        metadata[key] = value

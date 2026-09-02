"""Live camera stream ingestion via RTSP, MJPEG, or HTTP URLs.

OpenCV's VideoCapture supports RTSP and MJPEG natively, so this module
wraps it with reconnection logic, frame-rate limiting, and health
reporting suitable for continuous monitoring of remote cameras -- the
kind deployed along Nepal's river basins.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import cv2
import numpy as np

from openfloodai.common import FrameArray


class StreamError(RuntimeError):
    """Raised when a camera stream cannot be opened or has failed."""


@dataclass
class StreamConfig:
    """Configuration for connecting to one camera stream."""

    url: str
    timeout_seconds: float = 10.0
    max_retries: int = 3
    retry_delay_seconds: float = 5.0
    target_fps: float = 1.0

    def __post_init__(self) -> None:
        if not self.url:
            raise StreamError("Stream URL must not be empty")
        if self.timeout_seconds <= 0:
            raise StreamError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise StreamError("max_retries must be non-negative")
        if self.target_fps <= 0:
            raise StreamError("target_fps must be positive")


@dataclass
class StreamState:
    """Mutable state for an active stream connection."""

    capture: cv2.VideoCapture | None = None
    consecutive_failures: int = 0
    total_frames_read: int = 0
    last_frame_time: float = 0.0
    connected_since: datetime | None = None
    last_error: str = ""
    _closed: bool = field(default=False, repr=False)

    @property
    def is_connected(self) -> bool:
        return self.capture is not None and self.capture.isOpened() and not self._closed


def open_stream(config: StreamConfig) -> StreamState:
    """Open a camera stream, retrying on failure."""

    state = StreamState()
    for attempt in range(config.max_retries + 1):
        cap = cv2.VideoCapture(config.url)
        if cap.isOpened():
            state.capture = cap
            state.consecutive_failures = 0
            state.connected_since = datetime.now(tz=UTC)
            return state

        cap.release()
        state.last_error = f"Failed to open stream (attempt {attempt + 1})"

        if attempt < config.max_retries:
            time.sleep(config.retry_delay_seconds)

    msg = f"Could not open stream after {config.max_retries + 1} attempts: {config.url}"
    raise StreamError(msg)


def read_frame(state: StreamState, config: StreamConfig) -> FrameArray | None:
    """Read one frame from the stream, respecting target FPS.

    Returns ``None`` when the frame interval has not elapsed yet or when
    the read fails (the caller should check ``state.consecutive_failures``
    to decide whether to reconnect).
    """

    if not state.is_connected:
        return None

    now = time.monotonic()
    interval = 1.0 / config.target_fps
    if now - state.last_frame_time < interval:
        return None

    assert state.capture is not None
    ok, frame = state.capture.read()
    if not ok or frame is None:
        state.consecutive_failures += 1
        state.last_error = "Frame read failed"
        return None

    state.consecutive_failures = 0
    state.total_frames_read += 1
    state.last_frame_time = now
    return np.asarray(frame)


def close_stream(state: StreamState) -> None:
    """Release the underlying VideoCapture."""

    if state.capture is not None:
        state.capture.release()
        state.capture = None
    state._closed = True


def reconnect_stream(state: StreamState, config: StreamConfig) -> bool:
    """Close and reopen the stream. Returns True on success."""

    close_stream(state)
    try:
        new_state = open_stream(config)
    except StreamError:
        return False

    state.capture = new_state.capture
    state.consecutive_failures = 0
    state.connected_since = new_state.connected_since
    state._closed = False
    return True


def stream_health_record(
    state: StreamState,
    config: StreamConfig,
    site_id: str,
    camera_id: str,
) -> dict[str, object]:
    """Build a health record for the current stream state."""

    if state.is_connected:
        quality = "USABLE"
        reason_codes = ["INPUT_USABLE"]
        summary = f"Stream connected ({state.total_frames_read} frames read)"
    else:
        quality = "UNKNOWN"
        reason_codes = ["INPUT_UNKNOWN"]
        summary = f"Stream disconnected: {state.last_error}"

    return {
        "contract_version": "v1",
        "record_type": "camera_health_output",
        "site_id": site_id,
        "camera_id": camera_id,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "input_quality_state": quality,
        "is_usable": state.is_connected,
        "reason_codes": reason_codes,
        "human_summary": summary,
        "stream_url": config.url,
        "total_frames_read": state.total_frames_read,
        "consecutive_failures": state.consecutive_failures,
    }

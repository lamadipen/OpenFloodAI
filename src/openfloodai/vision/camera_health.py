"""Camera health detection for continuous monitoring.

Detects frozen frames, overly dark or bright conditions, and camera
shake -- all conditions that make flood detection unreliable and that
operators need to know about immediately.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import cv2
import numpy as np
from numpy.typing import NDArray

from openfloodai.common import FrameArray


class CameraHealthError(ValueError):
    """Raised when camera health analysis input is invalid."""


@dataclass(frozen=True)
class HealthThresholds:
    """Tunable thresholds for camera health checks."""

    dark_brightness: float = 0.08
    bright_brightness: float = 0.95
    frozen_similarity: float = 0.999
    shake_threshold: float = 0.15
    min_history: int = 3


@dataclass
class FrameHistory:
    """Rolling buffer of recent frame statistics for temporal health checks."""

    max_size: int = 30
    _hashes: deque[str] = field(default_factory=deque)
    _brightnesses: deque[float] = field(default_factory=deque)
    _sharpnesses: deque[float] = field(default_factory=deque)

    def add(self, frame_hash: str, brightness: float, sharpness: float) -> None:
        if len(self._hashes) >= self.max_size:
            self._hashes.popleft()
            self._brightnesses.popleft()
            self._sharpnesses.popleft()
        self._hashes.append(frame_hash)
        self._brightnesses.append(brightness)
        self._sharpnesses.append(sharpness)

    @property
    def count(self) -> int:
        return len(self._hashes)

    @property
    def last_hash(self) -> str | None:
        return self._hashes[-1] if self._hashes else None

    @property
    def consecutive_identical(self) -> int:
        if not self._hashes:
            return 0
        last = self._hashes[-1]
        count = 0
        for h in reversed(self._hashes):
            if h != last:
                break
            count += 1
        return count

    @property
    def brightness_variance(self) -> float:
        if len(self._brightnesses) < 2:
            return 0.0
        arr = np.array(list(self._brightnesses))
        return float(np.var(arr))


def analyze_frame_health(
    frame: FrameArray,
    history: FrameHistory,
    site_id: str,
    camera_id: str,
    *,
    thresholds: HealthThresholds | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    """Analyze a single frame for camera health issues.

    Updates ``history`` in place and returns a V1 health record.
    """

    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise CameraHealthError("Frame must be a non-empty NumPy array")
    if not site_id or not camera_id:
        raise CameraHealthError("site_id and camera_id must be non-empty")

    t = thresholds or HealthThresholds()
    issues: list[str] = []

    gray = _to_gray(frame)
    brightness = float(gray.mean()) / 255.0
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 10000.0
    sharpness = min(sharpness, 1.0)
    frame_hash = _quick_hash(gray)

    if brightness < t.dark_brightness:
        issues.append("DARK_FRAME")
    elif brightness > t.bright_brightness:
        issues.append("BRIGHT_FRAME")

    history.add(frame_hash, brightness, sharpness)

    if history.consecutive_identical >= t.min_history:
        issues.append("FROZEN_FRAME")

    if history.count >= t.min_history and history.brightness_variance > t.shake_threshold:
        issues.append("CAMERA_SHAKE")

    if issues:
        quality = "DEGRADED"
        reason_codes = issues
        is_usable = "FROZEN_FRAME" not in issues
        summary = f"Camera health issues: {', '.join(issues)}"
    else:
        quality = "USABLE"
        reason_codes = ["INPUT_USABLE"]
        is_usable = True
        summary = "Camera feed healthy."

    return {
        "contract_version": "v1",
        "record_id": f"camera-health-{uuid4()}",
        "record_type": "camera_health_output",
        "site_id": site_id,
        "camera_id": camera_id,
        "timestamp": timestamp or datetime.now(tz=UTC).isoformat(),
        "input_quality_state": quality,
        "is_usable": is_usable,
        "reason_codes": reason_codes,
        "human_summary": summary,
        "brightness": round(brightness, 4),
        "sharpness": round(sharpness, 4),
        "consecutive_identical_frames": history.consecutive_identical,
    }


def _to_gray(frame: FrameArray) -> NDArray[np.uint8]:
    if frame.ndim == 2:
        return np.asarray(frame, dtype=np.uint8)
    if frame.shape[2] == 1:
        return np.asarray(frame[:, :, 0], dtype=np.uint8)
    converted = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # type: ignore[arg-type]
    return np.asarray(converted, dtype=np.uint8)


def _quick_hash(gray: NDArray[np.uint8]) -> str:
    small = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
    mean_val = small.mean()
    bits = (small > mean_val).flatten()
    return "".join("1" if b else "0" for b in bits)

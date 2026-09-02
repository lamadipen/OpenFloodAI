"""HSV color-space water detection for flood monitoring.

The simple_signals module fires on any pixel change.  This module adds
water-specific detection using HSV color segmentation -- a technique that
works without ML training and can distinguish rising water (blue-brown)
from ordinary scene changes like wind, lighting shifts, or vehicle motion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import cv2
import numpy as np

from openfloodai.common import FrameArray


class WaterDetectionError(ValueError):
    """Raised when water detection input is invalid."""


@dataclass(frozen=True)
class WaterThresholds:
    """Tunable thresholds for HSV-based water detection."""

    hue_low: int = 85
    hue_high: int = 135
    sat_low: int = 30
    sat_high: int = 255
    val_low: int = 30
    val_high: int = 220
    brown_hue_low: int = 5
    brown_hue_high: int = 25
    brown_sat_low: int = 50
    brown_sat_high: int = 255
    brown_val_low: int = 30
    brown_val_high: int = 180
    min_water_ratio: float = 0.05


def detect_water_coverage(
    frame: FrameArray,
    site_id: str,
    camera_id: str,
    *,
    thresholds: WaterThresholds | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    """Detect water coverage in a frame using HSV color segmentation.

    Returns a V1 record with ``water_coverage_ratio`` (0.0-1.0),
    ``muddy_water_ratio``, and ``clear_water_ratio``.
    """

    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise WaterDetectionError("Frame must be a non-empty NumPy array")
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise WaterDetectionError("Frame must be a 3-channel BGR image")
    if not site_id:
        raise WaterDetectionError("site_id must be non-empty")
    if not camera_id:
        raise WaterDetectionError("camera_id must be non-empty")

    t = thresholds or WaterThresholds()
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)  # type: ignore[arg-type]
    total_pixels = float(frame.shape[0] * frame.shape[1])

    clear_mask = cv2.inRange(
        hsv,
        np.array([t.hue_low, t.sat_low, t.val_low], dtype=np.uint8),
        np.array([t.hue_high, t.sat_high, t.val_high], dtype=np.uint8),
    )
    clear_pixels = float(cv2.countNonZero(clear_mask))

    muddy_mask = cv2.inRange(
        hsv,
        np.array([t.brown_hue_low, t.brown_sat_low, t.brown_val_low], dtype=np.uint8),
        np.array([t.brown_hue_high, t.brown_sat_high, t.brown_val_high], dtype=np.uint8),
    )
    muddy_pixels = float(cv2.countNonZero(muddy_mask))

    clear_ratio = clear_pixels / total_pixels
    muddy_ratio = muddy_pixels / total_pixels
    combined = cv2.bitwise_or(clear_mask, muddy_mask)
    water_ratio = float(cv2.countNonZero(combined)) / total_pixels

    return {
        "contract_version": "v1",
        "record_id": f"water-detect-{uuid4()}",
        "record_type": "water_detection_output",
        "site_id": site_id,
        "camera_id": camera_id,
        "timestamp": timestamp or datetime.now(tz=UTC).isoformat(),
        "water_coverage_ratio": round(water_ratio, 6),
        "clear_water_ratio": round(clear_ratio, 6),
        "muddy_water_ratio": round(muddy_ratio, 6),
        "water_detected": water_ratio >= t.min_water_ratio,
        "human_summary": _water_summary(water_ratio, muddy_ratio, t.min_water_ratio),
    }


def compute_water_change(
    previous: dict[str, object],
    current: dict[str, object],
) -> dict[str, object]:
    """Compute the change in water coverage between two detection records.

    Pure computation, no OpenCV calls.
    """

    prev_ratio = _float_field(previous, "water_coverage_ratio")
    curr_ratio = _float_field(current, "water_coverage_ratio")
    delta = curr_ratio - prev_ratio

    return {
        "water_coverage_delta": round(delta, 6),
        "water_rising": delta > 0.02,
        "water_falling": delta < -0.02,
        "water_stable": abs(delta) <= 0.02,
        "previous_ratio": round(prev_ratio, 6),
        "current_ratio": round(curr_ratio, 6),
    }


def _float_field(record: dict[str, object], name: str) -> float:
    val = record.get(name)
    if not isinstance(val, (int, float)):
        raise WaterDetectionError(f"Record missing numeric field '{name}'")
    return float(val)


def _water_summary(
    water_ratio: float,
    muddy_ratio: float,
    threshold: float,
) -> str:
    pct = water_ratio * 100.0
    if water_ratio < threshold:
        return f"Minimal water detected ({pct:.1f}% of frame)."
    if muddy_ratio > water_ratio * 0.5:
        return f"Muddy/flood water covers {pct:.1f}% of frame -- possible flood conditions."
    return f"Water covers {pct:.1f}% of frame."

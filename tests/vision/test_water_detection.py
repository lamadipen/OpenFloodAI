from __future__ import annotations

import numpy as np
import pytest

from openfloodai.vision.water_detection import (
    WaterDetectionError,
    WaterThresholds,
    compute_water_change,
    detect_water_coverage,
)


def _blue_frame(h: int = 100, w: int = 100) -> np.ndarray:
    """Create a frame dominated by blue (water-like) pixels in BGR."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:, :, 0] = 180  # B
    frame[:, :, 1] = 100  # G
    frame[:, :, 2] = 50  # R
    return frame


def _brown_frame(h: int = 100, w: int = 100) -> np.ndarray:
    """Create a frame dominated by brown (muddy water) pixels in BGR."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:, :, 0] = 40  # B
    frame[:, :, 1] = 80  # G
    frame[:, :, 2] = 120  # R
    return frame


def _green_frame(h: int = 100, w: int = 100) -> np.ndarray:
    """Create a frame dominated by green (vegetation) pixels."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:, :, 0] = 30  # B
    frame[:, :, 1] = 180  # G
    frame[:, :, 2] = 30  # R
    return frame


def test_detect_blue_water() -> None:
    result = detect_water_coverage(_blue_frame(), "site1", "cam1")
    assert result["record_type"] == "water_detection_output"
    ratio = result["water_coverage_ratio"]
    assert isinstance(ratio, float)
    assert ratio > 0.5
    assert result["water_detected"] is True


def test_detect_brown_water() -> None:
    result = detect_water_coverage(_brown_frame(), "site1", "cam1")
    muddy = result["muddy_water_ratio"]
    assert isinstance(muddy, float)
    assert muddy > 0.3


def test_no_water_in_vegetation() -> None:
    result = detect_water_coverage(_green_frame(), "site1", "cam1")
    ratio = result["water_coverage_ratio"]
    assert isinstance(ratio, float)
    assert ratio < 0.2


def test_empty_frame_raises() -> None:
    with pytest.raises(WaterDetectionError):
        detect_water_coverage(np.array([]), "site1", "cam1")


def test_grayscale_frame_raises() -> None:
    with pytest.raises(WaterDetectionError):
        detect_water_coverage(np.zeros((10, 10), dtype=np.uint8), "site1", "cam1")


def test_empty_site_id_raises() -> None:
    with pytest.raises(WaterDetectionError):
        detect_water_coverage(_blue_frame(), "", "cam1")


def test_custom_thresholds() -> None:
    t = WaterThresholds(min_water_ratio=0.99)
    result = detect_water_coverage(_green_frame(), "site1", "cam1", thresholds=t)
    assert result["water_detected"] is False


def test_compute_water_change_rising() -> None:
    prev: dict[str, object] = {"water_coverage_ratio": 0.1}
    curr: dict[str, object] = {"water_coverage_ratio": 0.5}
    change = compute_water_change(prev, curr)
    assert change["water_rising"] is True
    assert change["water_falling"] is False


def test_compute_water_change_falling() -> None:
    prev: dict[str, object] = {"water_coverage_ratio": 0.5}
    curr: dict[str, object] = {"water_coverage_ratio": 0.1}
    change = compute_water_change(prev, curr)
    assert change["water_rising"] is False
    assert change["water_falling"] is True


def test_compute_water_change_stable() -> None:
    prev: dict[str, object] = {"water_coverage_ratio": 0.3}
    curr: dict[str, object] = {"water_coverage_ratio": 0.31}
    change = compute_water_change(prev, curr)
    assert change["water_stable"] is True


def test_summary_muddy_flood() -> None:
    frame = _brown_frame()
    result = detect_water_coverage(frame, "site1", "cam1")
    summary = result["human_summary"]
    assert isinstance(summary, str)
    assert len(summary) > 0

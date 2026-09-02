from __future__ import annotations

import numpy as np
import pytest

from openfloodai.vision.camera_health import (
    CameraHealthError,
    FrameHistory,
    HealthThresholds,
    analyze_frame_health,
)


def _normal_frame(seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(60, 200, size=(64, 64, 3), dtype=np.uint8)


def _dark_frame() -> np.ndarray:
    return np.zeros((64, 64, 3), dtype=np.uint8)


def _bright_frame() -> np.ndarray:
    return np.full((64, 64, 3), 250, dtype=np.uint8)


def _static_frame() -> np.ndarray:
    return np.full((64, 64, 3), 128, dtype=np.uint8)


def test_healthy_frame() -> None:
    history = FrameHistory()
    result = analyze_frame_health(_normal_frame(), history, "site1", "cam1")
    assert result["input_quality_state"] == "USABLE"
    assert result["is_usable"] is True
    codes = result["reason_codes"]
    assert isinstance(codes, list) and "INPUT_USABLE" in codes


def test_dark_frame_detected() -> None:
    history = FrameHistory()
    result = analyze_frame_health(_dark_frame(), history, "site1", "cam1")
    codes = result["reason_codes"]
    assert isinstance(codes, list) and "DARK_FRAME" in codes
    assert result["input_quality_state"] == "DEGRADED"


def test_bright_frame_detected() -> None:
    history = FrameHistory()
    result = analyze_frame_health(_bright_frame(), history, "site1", "cam1")
    codes = result["reason_codes"]
    assert isinstance(codes, list) and "BRIGHT_FRAME" in codes


def test_frozen_frame_detected() -> None:
    history = FrameHistory()
    thresholds = HealthThresholds(min_history=3)
    frame = _static_frame()

    for _ in range(4):
        result = analyze_frame_health(frame, history, "site1", "cam1", thresholds=thresholds)

    codes = result["reason_codes"]
    assert isinstance(codes, list) and "FROZEN_FRAME" in codes
    assert result["is_usable"] is False


def test_varied_frames_not_frozen() -> None:
    history = FrameHistory()
    thresholds = HealthThresholds(min_history=3)
    result: dict[str, object] = {}

    for i in range(5):
        result = analyze_frame_health(
            _normal_frame(seed=i), history, "site1", "cam1", thresholds=thresholds
        )

    codes = result["reason_codes"]
    assert isinstance(codes, list) and "FROZEN_FRAME" not in codes


def test_empty_frame_raises() -> None:
    history = FrameHistory()
    with pytest.raises(CameraHealthError):
        analyze_frame_health(np.array([]), history, "site1", "cam1")


def test_empty_site_id_raises() -> None:
    history = FrameHistory()
    with pytest.raises(CameraHealthError):
        analyze_frame_health(_normal_frame(), history, "", "cam1")


def test_frame_history_count() -> None:
    history = FrameHistory(max_size=5)
    for i in range(10):
        history.add(f"hash{i}", 0.5, 0.5)
    assert history.count == 5


def test_frame_history_consecutive() -> None:
    history = FrameHistory()
    history.add("a", 0.5, 0.5)
    history.add("b", 0.5, 0.5)
    history.add("b", 0.5, 0.5)
    history.add("b", 0.5, 0.5)
    assert history.consecutive_identical == 3

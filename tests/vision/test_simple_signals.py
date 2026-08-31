from __future__ import annotations

from typing import cast

import numpy as np
import pytest

from openfloodai.vision import VisualSignalError, compare_frames, extract_frame_signals


def test_bright_frame_has_higher_brightness_score_than_dark_frame() -> None:
    dark_frame = np.zeros((8, 8, 3), dtype=np.uint8)
    bright_frame = np.full((8, 8, 3), 220, dtype=np.uint8)

    dark_result = extract_frame_signals(dark_frame, "site-demo-01", "camera-demo-01")
    bright_result = extract_frame_signals(bright_frame, "site-demo-01", "camera-demo-01")

    assert cast(float, bright_result["brightness_score"]) > cast(
        float, dark_result["brightness_score"]
    )


def test_extract_frame_signals_returns_required_fields() -> None:
    frame = np.full((8, 8, 3), 128, dtype=np.uint8)

    result = extract_frame_signals(
        frame,
        "site-demo-01",
        "camera-demo-01",
        timestamp="2026-08-31T12:00:00+00:00",
        source_record_ids=["frame-meta-001"],
    )

    assert result["contract_version"] == "v1"
    assert result["record_type"] == "visual_signal_output"
    assert str(result["record_id"]).startswith("visual-signal-")
    assert result["site_id"] == "site-demo-01"
    assert result["camera_id"] == "camera-demo-01"
    assert result["timestamp"] == "2026-08-31T12:00:00+00:00"
    assert result["source_record_ids"] == ["frame-meta-001"]
    assert 0.0 <= cast(float, result["brightness_score"]) <= 1.0
    assert 0.0 <= cast(float, result["sharpness_score"]) <= 1.0
    assert "frame" in str(result["human_summary"]).lower()


def test_changed_frame_pair_has_higher_change_score_than_identical_frames() -> None:
    previous_frame = np.zeros((8, 8, 3), dtype=np.uint8)
    unchanged_frame = np.zeros((8, 8, 3), dtype=np.uint8)
    changed_frame = np.full((8, 8, 3), 180, dtype=np.uint8)

    unchanged_result = compare_frames(
        previous_frame,
        unchanged_frame,
        "site-demo-01",
        "camera-demo-01",
    )
    changed_result = compare_frames(
        previous_frame,
        changed_frame,
        "site-demo-01",
        "camera-demo-01",
    )

    assert cast(float, changed_result["frame_change_score"]) > cast(
        float, unchanged_result["frame_change_score"]
    )


def test_compare_frames_preserves_site_camera_and_timestamp() -> None:
    previous_frame = np.zeros((8, 8), dtype=np.uint8)
    current_frame = np.ones((8, 8), dtype=np.uint8)

    result = compare_frames(
        previous_frame,
        current_frame,
        "site-demo-01",
        "camera-demo-01",
        timestamp="2026-08-31T12:00:05+00:00",
    )

    assert result["site_id"] == "site-demo-01"
    assert result["camera_id"] == "camera-demo-01"
    assert result["timestamp"] == "2026-08-31T12:00:05+00:00"
    assert 0.0 <= cast(float, result["frame_change_score"]) <= 1.0


def test_sharp_frame_has_higher_sharpness_score_than_flat_frame() -> None:
    flat_frame = np.full((8, 8), 128, dtype=np.uint8)
    sharp_frame = np.indices((8, 8)).sum(axis=0) % 2
    sharp_frame = (sharp_frame * 255).astype(np.uint8)

    flat_result = extract_frame_signals(flat_frame, "site-demo-01", "camera-demo-01")
    sharp_result = extract_frame_signals(sharp_frame, "site-demo-01", "camera-demo-01")

    assert cast(float, sharp_result["sharpness_score"]) > cast(
        float, flat_result["sharpness_score"]
    )


def test_empty_frame_fails_clearly() -> None:
    empty_frame = np.array([], dtype=np.uint8)

    with pytest.raises(VisualSignalError, match="must not be empty"):
        extract_frame_signals(empty_frame, "site-demo-01", "camera-demo-01")


def test_bad_frame_shape_fails_clearly() -> None:
    bad_frame = np.zeros((2, 2, 2, 2), dtype=np.uint8)

    with pytest.raises(VisualSignalError, match="2D grayscale or 3D color"):
        extract_frame_signals(bad_frame, "site-demo-01", "camera-demo-01")


def test_compare_frames_requires_matching_shapes() -> None:
    previous_frame = np.zeros((8, 8, 3), dtype=np.uint8)
    current_frame = np.zeros((10, 8, 3), dtype=np.uint8)

    with pytest.raises(VisualSignalError, match="same shape"):
        compare_frames(previous_frame, current_frame, "site-demo-01", "camera-demo-01")


def test_empty_site_id_fails_clearly() -> None:
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    with pytest.raises(VisualSignalError, match="site_id must be non-empty"):
        extract_frame_signals(frame, "", "camera-demo-01")

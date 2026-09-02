from __future__ import annotations

from typing import cast

import numpy as np
import pytest

from openfloodai.config import ReferenceRegion
from openfloodai.vision import (
    VisualSignalError,
    compare_frames,
    compare_region_signals,
    extract_frame_signals,
    extract_region_signals,
)


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


def test_extract_region_signals_uses_selected_region_only() -> None:
    frame = np.zeros((10, 10), dtype=np.uint8)
    frame[:5, :] = 255
    lower_half_region = {
        "x": 0,
        "y": 50,
        "width": 100,
        "height": 50,
    }

    full_frame_result = extract_frame_signals(frame, "site-demo-01", "camera-demo-01")
    region_result = extract_region_signals(
        frame,
        lower_half_region,
        "site-demo-01",
        "camera-demo-01",
    )

    assert full_frame_result["brightness_score"] == 0.5
    assert region_result["reference_region_used"] is True
    assert region_result["region_x"] == 0.0
    assert region_result["region_y"] == 5.0
    assert region_result["region_width"] == 10.0
    assert region_result["region_height"] == 5.0
    assert region_result["region_brightness_score"] == 0.0
    assert "reference region" in str(region_result["human_summary"]).lower()


def test_compare_region_signals_scores_change_only_inside_selected_region() -> None:
    previous_frame = np.zeros((10, 10), dtype=np.uint8)
    current_frame = np.zeros((10, 10), dtype=np.uint8)
    current_frame[:5, :] = 255
    lower_half_region = {
        "x": 0,
        "y": 50,
        "width": 100,
        "height": 50,
    }
    upper_half_region = {
        "x": 0,
        "y": 0,
        "width": 100,
        "height": 50,
    }

    lower_result = compare_region_signals(
        previous_frame,
        current_frame,
        lower_half_region,
        "site-demo-01",
        "camera-demo-01",
    )
    upper_result = compare_region_signals(
        previous_frame,
        current_frame,
        upper_half_region,
        "site-demo-01",
        "camera-demo-01",
    )

    assert lower_result["region_change_score"] == 0.0
    assert upper_result["region_change_score"] == 1.0


def test_compare_region_signals_reports_strongest_changed_band() -> None:
    previous_frame = np.zeros((9, 6), dtype=np.uint8)
    current_frame = np.zeros((9, 6), dtype=np.uint8)
    current_frame[6:9, :] = 180
    full_region = {
        "x": 0,
        "y": 0,
        "width": 100,
        "height": 100,
    }

    result = compare_region_signals(
        previous_frame,
        current_frame,
        full_region,
        "site-demo-01",
        "camera-demo-01",
    )

    assert result["upper_region_change_score"] == 0.0
    assert result["middle_region_change_score"] == 0.0
    assert cast(float, result["lower_region_change_score"]) > 0.0
    assert result["strongest_changed_area"] == "lower"
    assert result["water_level_evidence_state"] == "useful_water_level_evidence"
    assert "not proof of flooding" in str(result["human_summary"]).lower()


def test_compare_region_signals_marks_whole_region_change_as_cannot_judge() -> None:
    previous_frame = np.zeros((9, 6), dtype=np.uint8)
    current_frame = np.full((9, 6), 180, dtype=np.uint8)
    full_region = {
        "x": 0,
        "y": 0,
        "width": 100,
        "height": 100,
    }

    result = compare_region_signals(
        previous_frame,
        current_frame,
        full_region,
        "site-demo-01",
        "camera-demo-01",
    )

    assert cast(float, result["upper_region_change_score"]) > 0.0
    assert cast(float, result["middle_region_change_score"]) > 0.0
    assert cast(float, result["lower_region_change_score"]) > 0.0
    assert result["water_level_evidence_state"] == "cannot_judge_whole_region_changed"
    assert "lighting" in str(result["human_summary"]).lower()


def test_compare_region_signals_marks_tiny_region_as_cannot_judge() -> None:
    previous_frame = np.zeros((2, 2), dtype=np.uint8)
    current_frame = np.ones((2, 2), dtype=np.uint8)
    tiny_region = {
        "x": 0,
        "y": 0,
        "width": 50,
        "height": 50,
    }

    result = compare_region_signals(
        previous_frame,
        current_frame,
        tiny_region,
        "site-demo-01",
        "camera-demo-01",
    )

    assert result["region_width"] == 1.0
    assert result["region_height"] == 1.0
    assert result["water_level_evidence_state"] == "cannot_judge_region_too_small"
    assert "too small" in str(result["human_summary"]).lower()


def test_region_signals_accept_config_reference_region_object() -> None:
    frame = np.zeros((10, 10), dtype=np.uint8)
    region = ReferenceRegion(x=0, y=50, width=100, height=50)

    result = extract_region_signals(frame, region, "site-demo-01", "camera-demo-01")

    assert result["reference_region_used"] is True
    assert result["region_width"] == 10.0
    assert result["region_height"] == 5.0


def test_missing_reference_region_field_fails_clearly() -> None:
    frame = np.zeros((10, 10), dtype=np.uint8)
    bad_region = {
        "x": 0,
        "y": 50,
        "width": 100,
    }

    with pytest.raises(VisualSignalError, match="height"):
        extract_region_signals(frame, bad_region, "site-demo-01", "camera-demo-01")


def test_reference_region_outside_image_area_fails_clearly() -> None:
    frame = np.zeros((10, 10), dtype=np.uint8)
    bad_region = {
        "x": 70,
        "y": 50,
        "width": 40,
        "height": 50,
    }

    with pytest.raises(VisualSignalError, match="0-100 image area"):
        extract_region_signals(frame, bad_region, "site-demo-01", "camera-demo-01")

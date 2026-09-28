from __future__ import annotations

import numpy as np
import pytest

from openfloodai.vision.riverbank_crossing import (
    RiverbankCrossingError,
    evaluate_riverbank_crossing,
)

FRAME_SIZE = 100
LAND_VALUE = 200
WATER_VALUE = 50


def two_band_frame(*, changed_band: tuple[int, int] | None = None) -> np.ndarray:
    """Rows 0-49 are 'land', rows 50-99 are 'water', in a 100x100x3 uint8 frame.

    `changed_band`, if given, is a (start_row, end_row) slice set to the
    water value instead -- simulating land turning into water there.
    """

    frame = np.full((FRAME_SIZE, FRAME_SIZE, 3), LAND_VALUE, dtype=np.uint8)
    frame[50:, :, :] = WATER_VALUE
    if changed_band is not None:
        start, end = changed_band
        frame[start:end, :, :] = WATER_VALUE
    return frame


STRAIGHT_GUIDE = [{"x": 0, "y": 50}, {"x": 100, "y": 50}]
WATER_BELOW = {"x": 50, "y": 80}
WATER_ABOVE = {"x": 50, "y": 20}


def test_detects_crossing_when_land_side_changes_and_water_side_does_not() -> None:
    baseline = two_band_frame()
    current = two_band_frame(changed_band=(40, 50))

    result = evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_BELOW)

    assert result.crossed_line_percentage > 0
    assert result.changed_bank_length_percentage > 0
    assert any(sample.crossed for sample in result.samples)


def test_flipping_water_side_point_flips_which_side_counts_as_land() -> None:
    baseline = two_band_frame()
    # Same visual change as above (rows 40-49 turn to the water value), but
    # now water_side_point says water is ABOVE the line, so this change is on
    # the *water* side and must not be reported as land-side crossing.
    current = two_band_frame(changed_band=(40, 50))

    result = evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_ABOVE)

    assert result.crossed_line_percentage == 0
    assert result.changed_bank_length_percentage == 0


def test_no_crossing_reported_when_nothing_changes() -> None:
    baseline = two_band_frame()
    current = two_band_frame()

    result = evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_BELOW)

    assert result.crossed_line_percentage == 0
    assert result.maximum_crossing_pixels == 0


def test_uniform_lighting_change_on_both_sides_is_not_flagged() -> None:
    """A global brightness shift must not read as water crossing the line."""

    baseline = two_band_frame()
    current = np.clip(baseline.astype(np.int16) - 40, 0, 255).astype(np.uint8)

    result = evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_BELOW)

    assert result.crossed_line_percentage == 0


def test_larger_change_produces_a_larger_maximum_crossing_pixels() -> None:
    baseline = two_band_frame()
    small_change = two_band_frame(changed_band=(45, 50))
    large_change = two_band_frame(changed_band=(10, 50))

    small_result = evaluate_riverbank_crossing(baseline, small_change, STRAIGHT_GUIDE, WATER_BELOW)
    large_result = evaluate_riverbank_crossing(baseline, large_change, STRAIGHT_GUIDE, WATER_BELOW)

    assert large_result.maximum_crossing_pixels >= small_result.maximum_crossing_pixels


def test_curved_guide_produces_correctly_oriented_bands() -> None:
    baseline = two_band_frame()
    current = two_band_frame(changed_band=(40, 50))
    curved_guide = [
        {"x": 0, "y": 50},
        {"x": 40, "y": 50},
        {"x": 60, "y": 45},
        {"x": 100, "y": 40},
    ]

    result = evaluate_riverbank_crossing(baseline, current, curved_guide, WATER_BELOW)

    assert 0 <= result.crossed_line_percentage <= 100
    assert 0 <= result.changed_bank_length_percentage <= 100
    assert result.sample_count > 0


def test_guide_near_image_boundary_does_not_crash() -> None:
    baseline = two_band_frame()
    current = two_band_frame(changed_band=(0, 3))
    edge_guide = [{"x": 0, "y": 1}, {"x": 100, "y": 1}]

    result = evaluate_riverbank_crossing(baseline, current, edge_guide, {"x": 50, "y": 0})

    assert result.sample_count > 0


def test_deterministic_output_for_identical_inputs() -> None:
    baseline = two_band_frame()
    current = two_band_frame(changed_band=(40, 50))

    first = evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_BELOW)
    second = evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_BELOW)

    assert first == second


def test_rejects_fewer_than_two_guide_points() -> None:
    baseline = two_band_frame()
    current = two_band_frame()

    with pytest.raises(RiverbankCrossingError, match="at least 2 points"):
        evaluate_riverbank_crossing(baseline, current, [{"x": 50, "y": 50}], WATER_BELOW)


def test_rejects_mismatched_frame_shapes() -> None:
    baseline = two_band_frame()
    current = np.zeros((10, 10, 3), dtype=np.uint8)

    with pytest.raises(RiverbankCrossingError, match="same shape"):
        evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_BELOW)


def test_rejects_guide_points_that_collapse_to_one_pixel() -> None:
    tiny_frame = np.zeros((2, 2, 3), dtype=np.uint8)

    with pytest.raises(RiverbankCrossingError, match="collapse to the same pixel"):
        evaluate_riverbank_crossing(
            tiny_frame,
            tiny_frame,
            [{"x": 50, "y": 50}, {"x": 50.001, "y": 50.001}],
            WATER_BELOW,
        )


def test_rejects_non_positive_band_width() -> None:
    baseline = two_band_frame()
    current = two_band_frame()

    with pytest.raises(RiverbankCrossingError, match="band_width_px"):
        evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_BELOW, band_width_px=0)


def test_rejects_sample_count_below_two() -> None:
    baseline = two_band_frame()
    current = two_band_frame()

    with pytest.raises(RiverbankCrossingError, match="sample_count"):
        evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_BELOW, sample_count=1)

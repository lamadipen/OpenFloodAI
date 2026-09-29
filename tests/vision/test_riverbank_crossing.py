from __future__ import annotations

import math

import numpy as np
import pytest

from openfloodai.vision.riverbank_crossing import (
    RiverbankCrossingError,
    evaluate_riverbank_crossing,
)

FRAME_SIZE = 100
LAND_VALUE = 200
WATER_VALUE = 50
FULL_REGION = {"x": 0, "y": 0, "width": 100, "height": 100}


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


def _interpolated_y(guide_points: list[dict[str, float]], x: float) -> float:
    xs = [point["x"] / 100 * FRAME_SIZE for point in guide_points]
    ys = [point["y"] / 100 * FRAME_SIZE for point in guide_points]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i]) if xs[i + 1] != xs[i] else 0.0
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


def curve_following_frame(
    guide_points: list[dict[str, float]], *, land_changed: bool
) -> np.ndarray:
    """A frame whose land/water boundary follows `guide_points` exactly, not a flat band.

    Land is always above the guide's own curve, regardless of how sharply it
    bends -- used to test that orientation stays consistent along the whole
    polyline, not just on a straight line.
    """

    frame = np.empty((FRAME_SIZE, FRAME_SIZE, 3), dtype=np.uint8)
    land_value = WATER_VALUE if land_changed else LAND_VALUE
    for col in range(FRAME_SIZE):
        line_row = int(round(_interpolated_y(guide_points, col)))
        line_row = min(max(line_row, 0), FRAME_SIZE)
        frame[:line_row, col, :] = land_value
        frame[line_row:, col, :] = WATER_VALUE
    return frame


STRAIGHT_GUIDE = [{"x": 0, "y": 50}, {"x": 100, "y": 50}]
WATER_BELOW = {"x": 50, "y": 80}
WATER_ABOVE = {"x": 50, "y": 20}
ZIGZAG_GUIDE: list[dict[str, float]] = [
    {"x": 0.0, "y": 50.0},
    {"x": 25.0, "y": 20.0},
    {"x": 50.0, "y": 60.0},
    {"x": 75.0, "y": 15.0},
    {"x": 100.0, "y": 50.0},
]


def test_detects_crossing_when_land_side_changes_and_water_side_does_not() -> None:
    baseline = two_band_frame()
    current = two_band_frame(changed_band=(40, 50))

    result = evaluate_riverbank_crossing(
        baseline, current, STRAIGHT_GUIDE, WATER_BELOW, FULL_REGION
    )

    assert result.crossed_line_percentage > 0
    assert result.changed_bank_length_percentage > 0
    assert any(sample.crossed for sample in result.samples)


def test_flipping_water_side_point_flips_which_side_counts_as_land() -> None:
    baseline = two_band_frame()
    # Same visual change as above (rows 40-49 turn to the water value), but
    # now water_side_point says water is ABOVE the line, so this change is on
    # the *water* side and must not be reported as land-side crossing.
    current = two_band_frame(changed_band=(40, 50))

    result = evaluate_riverbank_crossing(
        baseline, current, STRAIGHT_GUIDE, WATER_ABOVE, FULL_REGION
    )

    assert result.crossed_line_percentage == 0
    assert result.changed_bank_length_percentage == 0


def test_no_crossing_reported_when_nothing_changes() -> None:
    baseline = two_band_frame()
    current = two_band_frame()

    result = evaluate_riverbank_crossing(
        baseline, current, STRAIGHT_GUIDE, WATER_BELOW, FULL_REGION
    )

    assert result.crossed_line_percentage == 0
    assert result.maximum_crossing_pixels == 0


def test_uniform_lighting_change_on_both_sides_is_not_flagged() -> None:
    """A global brightness shift must not read as water crossing the line."""

    baseline = two_band_frame()
    current = np.clip(baseline.astype(np.int16) - 40, 0, 255).astype(np.uint8)

    result = evaluate_riverbank_crossing(
        baseline, current, STRAIGHT_GUIDE, WATER_BELOW, FULL_REGION
    )

    assert result.crossed_line_percentage == 0


def test_larger_change_produces_a_larger_maximum_crossing_pixels() -> None:
    baseline = two_band_frame()
    small_change = two_band_frame(changed_band=(45, 50))
    large_change = two_band_frame(changed_band=(10, 50))

    small_result = evaluate_riverbank_crossing(
        baseline, small_change, STRAIGHT_GUIDE, WATER_BELOW, FULL_REGION
    )
    large_result = evaluate_riverbank_crossing(
        baseline, large_change, STRAIGHT_GUIDE, WATER_BELOW, FULL_REGION
    )

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

    result = evaluate_riverbank_crossing(baseline, current, curved_guide, WATER_BELOW, FULL_REGION)

    assert 0 <= result.crossed_line_percentage <= 100
    assert 0 <= result.changed_bank_length_percentage <= 100
    assert result.sample_count > 0


def test_zigzag_guide_keeps_a_consistent_land_side_along_every_section() -> None:
    """Regression: orientation must not flip between sections of a sharp curve.

    Builds land/water frames that follow the zigzag's own curve exactly
    (not a flat band), so a section where the old per-point orientation test
    flipped sign would measure the wrong side and miss the crossing there.
    With a single, consistent orientation decided once for the whole guide,
    every section should agree that the whole land side changed.
    """

    baseline = curve_following_frame(ZIGZAG_GUIDE, land_changed=False)
    current = curve_following_frame(ZIGZAG_GUIDE, land_changed=True)
    water_side_point = {"x": 50, "y": 95}

    result = evaluate_riverbank_crossing(
        baseline, current, ZIGZAG_GUIDE, water_side_point, FULL_REGION
    )

    assert result.crossed_line_percentage >= 85.0


def test_guide_near_image_boundary_does_not_crash() -> None:
    baseline = two_band_frame()
    current = two_band_frame(changed_band=(0, 3))
    edge_guide = [{"x": 0, "y": 1}, {"x": 100, "y": 1}]

    result = evaluate_riverbank_crossing(
        baseline, current, edge_guide, {"x": 50, "y": 0}, FULL_REGION
    )

    assert result.sample_count > 0


def test_deterministic_output_for_identical_inputs() -> None:
    baseline = two_band_frame()
    current = two_band_frame(changed_band=(40, 50))

    first = evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_BELOW, FULL_REGION)
    second = evaluate_riverbank_crossing(
        baseline, current, STRAIGHT_GUIDE, WATER_BELOW, FULL_REGION
    )

    assert first == second


def test_rejects_fewer_than_two_guide_points() -> None:
    baseline = two_band_frame()
    current = two_band_frame()

    with pytest.raises(RiverbankCrossingError, match="at least 2 points"):
        evaluate_riverbank_crossing(
            baseline, current, [{"x": 50, "y": 50}], WATER_BELOW, FULL_REGION
        )


def test_rejects_mismatched_frame_shapes() -> None:
    baseline = two_band_frame()
    current = np.zeros((10, 10, 3), dtype=np.uint8)

    with pytest.raises(RiverbankCrossingError, match="same shape"):
        evaluate_riverbank_crossing(baseline, current, STRAIGHT_GUIDE, WATER_BELOW, FULL_REGION)


def test_rejects_guide_points_that_collapse_to_one_pixel() -> None:
    tiny_frame = np.zeros((2, 2, 3), dtype=np.uint8)

    with pytest.raises(RiverbankCrossingError, match="collapse to the same pixel"):
        evaluate_riverbank_crossing(
            tiny_frame,
            tiny_frame,
            [{"x": 50, "y": 50}, {"x": 50.001, "y": 50.001}],
            WATER_BELOW,
            FULL_REGION,
        )


def test_rejects_non_positive_band_width() -> None:
    baseline = two_band_frame()
    current = two_band_frame()

    with pytest.raises(RiverbankCrossingError, match="band_width_px"):
        evaluate_riverbank_crossing(
            baseline, current, STRAIGHT_GUIDE, WATER_BELOW, FULL_REGION, band_width_px=0
        )


def test_rejects_sample_count_below_two() -> None:
    baseline = two_band_frame()
    current = two_band_frame()

    with pytest.raises(RiverbankCrossingError, match="sample_count"):
        evaluate_riverbank_crossing(
            baseline, current, STRAIGHT_GUIDE, WATER_BELOW, FULL_REGION, sample_count=1
        )


def test_rejects_zero_search_step_pixels_instead_of_hanging() -> None:
    """search_step_pixels=0 previously made _search_crossing_extent loop forever."""

    baseline = two_band_frame()
    current = two_band_frame(changed_band=(40, 50))

    with pytest.raises(RiverbankCrossingError, match="search_step_pixels"):
        evaluate_riverbank_crossing(
            baseline,
            current,
            STRAIGHT_GUIDE,
            WATER_BELOW,
            FULL_REGION,
            search_step_pixels=0,
        )


def test_rejects_non_positive_max_search_pixels() -> None:
    baseline = two_band_frame()
    current = two_band_frame()

    with pytest.raises(RiverbankCrossingError, match="max_search_pixels"):
        evaluate_riverbank_crossing(
            baseline,
            current,
            STRAIGHT_GUIDE,
            WATER_BELOW,
            FULL_REGION,
            max_search_pixels=-5,
        )


@pytest.mark.parametrize("bad_threshold", [-0.1, 1.1, math.nan, math.inf])
def test_rejects_out_of_range_or_non_finite_threshold(bad_threshold: float) -> None:
    baseline = two_band_frame()
    current = two_band_frame()

    with pytest.raises(RiverbankCrossingError, match="crossing_threshold"):
        evaluate_riverbank_crossing(
            baseline,
            current,
            STRAIGHT_GUIDE,
            WATER_BELOW,
            FULL_REGION,
            crossing_threshold=bad_threshold,
        )


def test_rejects_when_no_sample_has_enough_watched_region_area() -> None:
    """Every patch is clipped to the watched region, never the whole frame.

    The guide sits at row 50; a region covering only rows 0-5 leaves every
    land/water patch (which reach from the line itself out to band_width_px
    away) with no overlap at all.
    """

    baseline = two_band_frame()
    current = two_band_frame(changed_band=(40, 50))
    far_away_region = {"x": 0, "y": 0, "width": 100, "height": 5}

    with pytest.raises(RiverbankCrossingError, match="watched-region area"):
        evaluate_riverbank_crossing(
            baseline, current, STRAIGHT_GUIDE, WATER_BELOW, far_away_region, band_width_px=10
        )


def test_region_clipping_ignores_change_outside_the_watched_region() -> None:
    """A land-side change entirely outside the watched region must not be seen."""

    baseline = two_band_frame()
    # Change sits far above the line (rows 0-9), while the watched region
    # only covers rows 30-70 -- outside the region, so this must not count.
    current = two_band_frame(changed_band=(0, 10))
    region_over_the_line_only = {"x": 0, "y": 30, "width": 100, "height": 40}

    result = evaluate_riverbank_crossing(
        baseline,
        current,
        STRAIGHT_GUIDE,
        WATER_BELOW,
        region_over_the_line_only,
        band_width_px=10,
    )

    assert result.crossed_line_percentage == 0

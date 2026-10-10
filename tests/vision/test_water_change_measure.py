"""Synthetic checks of the mask-based water-change arithmetic (Issue #222)."""

from __future__ import annotations

import numpy as np
import pytest

from openfloodai.vision.water_change import (
    Roi,
    WaterChangeInputError,
    change_overlay,
    measure_water_change,
    roi_from_crop,
)

SIZE = (20, 10)  # (width, height)
ROI = Roi(2, 2, 12, 8)  # 10 x 6 = 60 pixels


def mask(*boxes: tuple[int, int, int, int]) -> np.ndarray:
    out = np.zeros((SIZE[1], SIZE[0]), dtype=np.uint8)
    for x0, y0, x1, y1 in boxes:
        out[y0:y1, x0:x1] = 255
    return out


def test_fractions_and_signed_delta_use_the_roi_as_the_denominator() -> None:
    earlier = mask((2, 2, 7, 8))  # 30 px = 50%
    later = mask((2, 2, 10, 8))  # 48 px = 80%
    change = measure_water_change(earlier, later, ROI, SIZE)
    assert change.roi_pixels == 60
    assert change.earlier_fraction == pytest.approx(0.5)
    assert change.later_fraction == pytest.approx(0.8)
    assert change.delta_percentage_points == pytest.approx(30.0)
    assert change.newly_wet_fraction == pytest.approx(0.3)
    assert change.no_longer_wet_fraction == 0.0
    assert change.still_wet_pixels == 30


def test_falling_coverage_is_negative() -> None:
    change = measure_water_change(mask((2, 2, 10, 8)), mask((2, 2, 5, 8)), ROI, SIZE)
    assert change.delta_percentage_points == pytest.approx(-50.0)
    assert change.no_longer_wet_fraction == pytest.approx(0.5)
    assert change.newly_wet_fraction == 0.0


def test_equal_area_different_shape_keeps_the_spatial_change() -> None:
    left = mask((2, 2, 7, 8))
    right = mask((7, 2, 12, 8))
    change = measure_water_change(left, right, ROI, SIZE)
    assert change.delta_percentage_points == 0.0
    assert change.newly_wet_fraction == pytest.approx(0.5)
    assert change.no_longer_wet_fraction == pytest.approx(0.5)
    assert change.changed_fraction == pytest.approx(1.0)
    assert change.still_wet_pixels == 0


def test_net_delta_equals_gain_minus_loss() -> None:
    earlier = mask((2, 2, 8, 5))
    later = mask((4, 3, 11, 8))
    change = measure_water_change(earlier, later, ROI, SIZE)
    assert change.delta_percentage_points == pytest.approx(
        (change.newly_wet_fraction - change.no_longer_wet_fraction) * 100
    )


def test_stable_high_coverage_is_zero_change() -> None:
    high = mask((2, 2, 12, 7))
    change = measure_water_change(high, high.copy(), ROI, SIZE)
    assert change.delta_percentage_points == 0.0
    assert change.changed_fraction == 0.0
    assert change.later_fraction > 0.8


def test_all_zero_mask_is_a_real_zero_but_a_missing_mask_is_refused() -> None:
    empty = mask()
    assert measure_water_change(empty, empty, ROI, SIZE).earlier_fraction == 0.0
    with pytest.raises(WaterChangeInputError) as missing:
        measure_water_change(None, empty, ROI, SIZE)
    assert missing.value.code == "MASK_MISSING"


def test_rate_per_hour_uses_elapsed_time_and_is_none_without_it() -> None:
    earlier, later = mask((2, 2, 7, 8)), mask((2, 2, 10, 8))
    hourly = measure_water_change(earlier, later, ROI, SIZE, elapsed_seconds=1800)
    assert hourly.change_rate_pp_per_hour == pytest.approx(60.0)
    assert measure_water_change(earlier, later, ROI, SIZE).change_rate_pp_per_hour is None
    assert (
        measure_water_change(earlier, later, ROI, SIZE, elapsed_seconds=0).change_rate_pp_per_hour
        is None
    )
    assert (
        measure_water_change(earlier, later, ROI, SIZE, elapsed_seconds=-5).change_rate_pp_per_hour
        is None
    )


def test_pixels_outside_the_roi_are_refused_not_clipped() -> None:
    with pytest.raises(WaterChangeInputError) as caught:
        measure_water_change(mask((0, 0, 4, 4)), mask((2, 2, 4, 4)), ROI, SIZE)
    assert caught.value.code == "MASK_OUTSIDE_WATCHED_AREA"


def test_wrong_size_mask_is_refused() -> None:
    with pytest.raises(WaterChangeInputError) as caught:
        measure_water_change(np.zeros((5, 5), dtype=np.uint8), mask(), ROI, SIZE)
    assert caught.value.code == "MASK_SIZE_MISMATCH"


@pytest.mark.parametrize(
    "crop",
    [None, [1, 2, 3], [5, 5, 5, 8], [0, 0, 99, 5], [-1, 0, 5, 5], [True, 0, 5, 5], "abcd"],
)
def test_invalid_watched_area_is_refused(crop: object) -> None:
    with pytest.raises(WaterChangeInputError) as caught:
        roi_from_crop(crop, SIZE)
    assert caught.value.code == "INVALID_WATCHED_AREA"


def test_overlay_colours_gain_and_loss_and_does_not_touch_the_input() -> None:
    image = np.full((SIZE[1], SIZE[0], 3), 100, dtype=np.uint8)
    before = image.copy()
    left, right = mask((2, 2, 7, 8)), mask((7, 2, 12, 8))
    drawn = change_overlay(image, left, right, ROI)
    assert np.array_equal(image, before)
    assert drawn.shape == image.shape
    assert not np.array_equal(drawn[4, 4], drawn[4, 9])  # lost vs gained pixels differ

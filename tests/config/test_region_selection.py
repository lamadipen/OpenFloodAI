"""Tests for local reference-region selection helpers."""

from __future__ import annotations

import pytest

from openfloodai.config import (
    RegionSelectionError,
    pixel_selection_to_reference_region,
    reference_region_to_dict,
)


def test_pixel_selection_converts_to_reference_region_percentages() -> None:
    region = pixel_selection_to_reference_region(
        image_width=800,
        image_height=600,
        x=100,
        y=120,
        width=400,
        height=240,
    )

    assert reference_region_to_dict(region) == {
        "x": 12.5,
        "y": 20.0,
        "width": 50.0,
        "height": 40.0,
    }


def test_pixel_selection_output_matches_config_reference_region_shape() -> None:
    region = pixel_selection_to_reference_region(
        image_width=1920,
        image_height=1080,
        x=480,
        y=270,
        width=960,
        height=540,
    )

    assert set(reference_region_to_dict(region)) == {"x", "y", "width", "height"}


def test_pixel_selection_rejects_box_outside_image() -> None:
    with pytest.raises(RegionSelectionError, match="fit inside"):
        pixel_selection_to_reference_region(
            image_width=800,
            image_height=600,
            x=700,
            y=100,
            width=150,
            height=100,
        )


def test_pixel_selection_rejects_zero_sized_box() -> None:
    with pytest.raises(RegionSelectionError, match="width must be greater than 0"):
        pixel_selection_to_reference_region(
            image_width=800,
            image_height=600,
            x=100,
            y=100,
            width=0,
            height=100,
        )


def test_pixel_selection_rejects_invalid_image_size() -> None:
    with pytest.raises(RegionSelectionError, match="image_width must be greater than 0"):
        pixel_selection_to_reference_region(
            image_width=0,
            image_height=600,
            x=100,
            y=100,
            width=100,
            height=100,
        )

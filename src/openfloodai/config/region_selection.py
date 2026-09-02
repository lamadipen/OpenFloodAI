"""Helpers for turning a drawn image box into reference-region config."""

from __future__ import annotations

from openfloodai.common.site_config import ReferenceRegion

Number = int | float


class RegionSelectionError(ValueError):
    """Raised when a selected image region is invalid."""


def pixel_selection_to_reference_region(
    *,
    image_width: Number,
    image_height: Number,
    x: Number,
    y: Number,
    width: Number,
    height: Number,
) -> ReferenceRegion:
    """Convert a pixel rectangle into 0-100 percentage reference-region values."""

    image_width_value = _load_positive_number(image_width, "image_width")
    image_height_value = _load_positive_number(image_height, "image_height")
    x_value = _load_number(x, "x")
    y_value = _load_number(y, "y")
    width_value = _load_positive_number(width, "width")
    height_value = _load_positive_number(height, "height")

    if x_value < 0 or y_value < 0:
        raise RegionSelectionError("Selected region x and y must be 0 or greater")
    if x_value + width_value > image_width_value or y_value + height_value > image_height_value:
        raise RegionSelectionError("Selected region must fit inside the image")

    return ReferenceRegion(
        x=_to_percent(x_value, image_width_value),
        y=_to_percent(y_value, image_height_value),
        width=_to_percent(width_value, image_width_value),
        height=_to_percent(height_value, image_height_value),
    )


def reference_region_to_dict(region: ReferenceRegion) -> dict[str, float]:
    """Return a JSON-ready reference_region object for config files."""

    return {
        "x": region.x,
        "y": region.y,
        "width": region.width,
        "height": region.height,
    }


def _load_number(value: Number, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RegionSelectionError(f"{field_name} must be a number")
    return float(value)


def _load_positive_number(value: Number, field_name: str) -> float:
    number = _load_number(value, field_name)
    if number <= 0:
        raise RegionSelectionError(f"{field_name} must be greater than 0")
    return number


def _to_percent(value: float, total: float) -> float:
    return round((value / total) * 100, 6)

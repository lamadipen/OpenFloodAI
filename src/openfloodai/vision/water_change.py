"""Mask-based water-change measurement for one ordered pair of images (Issue #222).

This module reads only two water masks and the fixed watched area (ROI). It never looks at image
brightness, so a lighting change with unchanged masks measures exactly zero change.

Definitions (calculation version ``CALCULATION_VERSION``). All fractions share ONE denominator:
the number of pixels in the ROI, so the pieces add up and can be compared between pairs.

- ``water pixel``: a pixel set in the mask, inside the ROI. If a source result has several
  detections, their masks are first combined with a logical OR (union); overlapping detections
  are counted once.
- ``earlier_fraction`` / ``later_fraction``: water pixels / ROI pixels at each endpoint.
- ``newly_wet_fraction``: pixels dry in the earlier mask and wet in the later one / ROI pixels.
- ``no_longer_wet_fraction``: pixels wet in the earlier mask and dry in the later one / ROI pixels.
- ``delta_percentage_points``: (later_fraction - earlier_fraction) * 100. It always equals
  (newly_wet_fraction - no_longer_wet_fraction) * 100, but unlike the net number the two parts are
  kept, so water that moved without changing the total is still visible.
- ``change_rate_pp_per_hour``: delta_percentage_points / elapsed hours. It is a rate of change of
  the visible area in the image, not a rise in physical water level and not a flow speed. Two
  endpoints cannot show an intermediate peak.

Valid domain: only pixels inside the ROI are measured. A mask pixel outside the ROI means the
mask does not belong to this watched area, so the pair is refused instead of clipped.
Coordinates: masks and the ROI are in ORIGINAL source-image pixels, ``[x0, y0, x1, y1)`` with the
right and bottom edges exclusive, the same convention the hosted segmentation results use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

CALCULATION_VERSION = "water_change_mask_v1.0"

MaskArray = npt.NDArray[Any]


class WaterChangeInputError(ValueError):
    """The inputs cannot be measured; ``code`` is a stable reason for the evidence record."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Roi:
    """The fixed watched area in source pixels; right and bottom edges are exclusive."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def pixels(self) -> int:
        return self.width * self.height

    def to_list(self) -> list[int]:
        return [self.x0, self.y0, self.x1, self.y1]


@dataclass(frozen=True)
class WaterChange:
    roi_pixels: int
    earlier_water_pixels: int
    later_water_pixels: int
    newly_wet_pixels: int
    no_longer_wet_pixels: int
    still_wet_pixels: int
    elapsed_seconds: float | None

    @property
    def earlier_fraction(self) -> float:
        return self.earlier_water_pixels / self.roi_pixels

    @property
    def later_fraction(self) -> float:
        return self.later_water_pixels / self.roi_pixels

    @property
    def newly_wet_fraction(self) -> float:
        return self.newly_wet_pixels / self.roi_pixels

    @property
    def no_longer_wet_fraction(self) -> float:
        return self.no_longer_wet_pixels / self.roi_pixels

    @property
    def delta_percentage_points(self) -> float:
        return (self.later_water_pixels - self.earlier_water_pixels) * 100.0 / self.roi_pixels

    @property
    def changed_fraction(self) -> float:
        """Spatial change regardless of direction: newly wet plus no longer wet."""

        return (self.newly_wet_pixels + self.no_longer_wet_pixels) / self.roi_pixels

    @property
    def change_rate_pp_per_hour(self) -> float | None:
        if self.elapsed_seconds is None or self.elapsed_seconds <= 0:
            return None
        return self.delta_percentage_points / (self.elapsed_seconds / 3600.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calculation_version": CALCULATION_VERSION,
            "denominator": "roi_pixels",
            "roi_pixels": self.roi_pixels,
            "earlier_water_pixels": self.earlier_water_pixels,
            "later_water_pixels": self.later_water_pixels,
            "newly_wet_pixels": self.newly_wet_pixels,
            "no_longer_wet_pixels": self.no_longer_wet_pixels,
            "still_wet_pixels": self.still_wet_pixels,
            "earlier_fraction": self.earlier_fraction,
            "later_fraction": self.later_fraction,
            "delta_percentage_points": self.delta_percentage_points,
            "newly_wet_fraction": self.newly_wet_fraction,
            "no_longer_wet_fraction": self.no_longer_wet_fraction,
            "changed_fraction": self.changed_fraction,
            "elapsed_seconds": self.elapsed_seconds,
            "change_rate_pp_per_hour": self.change_rate_pp_per_hour,
            "rate_note": "Image-space area rate; not physical level rise or flow speed.",
        }


def roi_from_crop(crop_px: Any, image_size: tuple[int, int]) -> Roi:
    """Build the ROI from ``[x0, y0, x1, y1]``, checking it lies inside the ``(w, h)`` image."""

    if (
        not isinstance(crop_px, (list, tuple))
        or len(crop_px) != 4
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in crop_px)
    ):
        raise WaterChangeInputError("INVALID_WATCHED_AREA", "The watched area is not four pixels.")
    roi = Roi(*crop_px)
    width, height = image_size
    if not (0 <= roi.x0 < roi.x1 <= width and 0 <= roi.y0 < roi.y1 <= height):
        raise WaterChangeInputError(
            "INVALID_WATCHED_AREA", "The watched area is empty or outside the image."
        )
    return roi


def _water_inside(mask: MaskArray | None, roi: Roi, image_size: tuple[int, int], which: str) -> Any:
    if mask is None:
        # A missing mask is not "no water": it is unknown, so nothing is measured.
        raise WaterChangeInputError("MASK_MISSING", f"The {which} water mask is missing.")
    array = np.asarray(mask)
    width, height = image_size
    if array.ndim != 2 or array.shape != (height, width):
        raise WaterChangeInputError(
            "MASK_SIZE_MISMATCH",
            f"The {which} mask is {array.shape} but the image is {(height, width)}.",
        )
    wet = array > 0
    inside = np.zeros_like(wet)
    inside[roi.y0 : roi.y1, roi.x0 : roi.x1] = wet[roi.y0 : roi.y1, roi.x0 : roi.x1]
    if int(wet.sum()) != int(inside.sum()):
        raise WaterChangeInputError(
            "MASK_OUTSIDE_WATCHED_AREA",
            f"The {which} mask has water pixels outside the watched area.",
        )
    return inside[roi.y0 : roi.y1, roi.x0 : roi.x1]


def measure_water_change(
    earlier_mask: MaskArray | None,
    later_mask: MaskArray | None,
    roi: Roi,
    image_size: tuple[int, int],
    *,
    elapsed_seconds: float | None = None,
) -> WaterChange:
    """Measure the ordered pair (earlier, later). An all-zero mask is a real 0% mask; a ``None``
    mask is missing evidence and raises ``WaterChangeInputError`` instead of counting as zero."""

    if roi.pixels <= 0:
        raise WaterChangeInputError("INVALID_WATCHED_AREA", "The watched area is empty.")
    earlier = _water_inside(earlier_mask, roi, image_size, "earlier")
    later = _water_inside(later_mask, roi, image_size, "later")
    return WaterChange(
        roi_pixels=roi.pixels,
        earlier_water_pixels=int(earlier.sum()),
        later_water_pixels=int(later.sum()),
        newly_wet_pixels=int((later & ~earlier).sum()),
        no_longer_wet_pixels=int((earlier & ~later).sum()),
        still_wet_pixels=int((earlier & later).sum()),
        elapsed_seconds=elapsed_seconds,
    )


# BGR colors for the spatial overlay.
NEWLY_WET_BGR = (255, 120, 0)  # blue-ish: water arrived
NO_LONGER_WET_BGR = (0, 0, 230)  # red: water left
STILL_WET_BGR = (150, 150, 150)  # grey: water in both


def change_overlay(
    image_bgr: npt.NDArray[Any],
    earlier_mask: MaskArray,
    later_mask: MaskArray,
    roi: Roi,
    *,
    opacity: float = 0.55,
) -> npt.NDArray[Any]:
    """The later image with newly wet, no-longer-wet and still-wet pixels coloured, ROI outlined."""

    out = image_bgr.copy()
    earlier = np.asarray(earlier_mask) > 0
    later = np.asarray(later_mask) > 0
    for selection, color in (
        (earlier & later, STILL_WET_BGR),
        (later & ~earlier, NEWLY_WET_BGR),
        (earlier & ~later, NO_LONGER_WET_BGR),
    ):
        tinted = out.astype(np.float32)
        tinted[selection] = (1 - opacity) * tinted[selection] + opacity * np.array(
            color, dtype=np.float32
        )
        out = tinted.astype(np.uint8)
    out[roi.y0 : roi.y1, roi.x0 : roi.x0 + 1] = (0, 255, 255)
    out[roi.y0 : roi.y1, roi.x1 - 1 : roi.x1] = (0, 255, 255)
    out[roi.y0 : roi.y0 + 1, roi.x0 : roi.x1] = (0, 255, 255)
    out[roi.y1 - 1 : roi.y1, roi.x0 : roi.x1] = (0, 255, 255)
    return out

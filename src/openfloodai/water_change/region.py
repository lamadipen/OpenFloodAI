"""The pixel crop a run's frozen watched area implies, to check masks against.

A segmentation result records the crop it was made with. A mask made from an older, smaller or
otherwise different watched area is the right picture of the wrong region: measured against the
run's frozen area it would still give a number. So every mask is compared with the crop that the
run's own frozen ``reference_region`` produces for that image size, using the same rounding the
segmentation used when it cut the crop.
"""

from __future__ import annotations

from typing import Any

from openfloodai.vision.hosted_sam import crop_transform


def expected_crop_px(region: Any, size: tuple[int, int] | None) -> list[int] | None:
    """``[x0, y0, x1, y1]`` for a percent region on an image of ``(width, height)``, or None.

    None means it cannot be known: no frozen region was recorded, or the region or size is not
    usable. Callers treat that as "cannot verify", never as a match.
    """

    if size is None or not isinstance(region, dict):
        return None
    try:
        transform = crop_transform(size[0], size[1], region, jpeg_quality=0)
    except (KeyError, TypeError, ValueError):
        return None
    return [transform.x0, transform.y0, transform.x1, transform.y1]

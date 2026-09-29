"""Riverbank-crossing evidence geometry (Issue #200 / OF-088).

Given a site's confirmed normal-waterline guide (a human-traced polyline)
and one point marking which side of it is normally water, this measures
visual change in a narrow band along the LAND side of the line that does
NOT also show up on the WATER side of the line. That differential check is
what keeps a uniform lighting/exposure shift (glare, dusk, a passing cloud)
from being misread as water crossing the line -- a global change shows up
on both sides equally and is never flagged.

Every sample/search patch is clipped to the site's configured watched
region, never the whole frame, matching the issue's "operate only inside
the existing watched region" requirement -- a patch near the region's edge
can otherwise reach pixels the reviewer never agreed to have analyzed.

This module does not perform camera alignment between the two frames; see
`openfloodai.evidence.adapters.riverbank_crossing` for how that gap is
surfaced as degraded evidence rather than a silent assumption.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from openfloodai.vision.simple_signals import (
    FrameArray,
    ReferenceRegionInput,
    patch_change_score,
)

DEFAULT_BAND_WIDTH_PX = 10
DEFAULT_CROSSING_THRESHOLD = 0.08
DEFAULT_MAX_SEARCH_PIXELS = 40
DEFAULT_SEARCH_STEP_PIXELS = 4
DEFAULT_SAMPLE_COUNT = 20

_RegionBounds = tuple[int, int, int, int]


class RiverbankCrossingError(ValueError):
    """Raised when riverbank-crossing geometry cannot be evaluated."""


class WaterlinePointLike(Protocol):
    """Shape shared by the config's WaterlinePoint dataclass and raw dicts."""

    @property
    def x(self) -> float: ...

    @property
    def y(self) -> float: ...


type WaterlinePointInput = Mapping[str, object] | WaterlinePointLike


@dataclass(frozen=True)
class SampleResult:
    """One sampled point's crossing evidence, in image-percentage coordinates."""

    point_x: float
    point_y: float
    distance_px: float
    land_change_score: float
    water_change_score: float
    crossed: bool
    crossing_extent_pixels: float


@dataclass(frozen=True)
class RiverbankCrossingResult:
    """Aggregate geometric crossing evidence for one guide, across two frames."""

    crossed_line_percentage: float
    changed_bank_length_percentage: float
    maximum_crossing_pixels: float
    band_width_px: int
    crossing_threshold: float
    sample_count: int
    samples: tuple[SampleResult, ...]


def evaluate_riverbank_crossing(
    baseline_frame: FrameArray,
    current_frame: FrameArray,
    guide_points: Sequence[WaterlinePointInput],
    water_side_point: WaterlinePointInput,
    reference_region: ReferenceRegionInput,
    *,
    band_width_px: int = DEFAULT_BAND_WIDTH_PX,
    crossing_threshold: float = DEFAULT_CROSSING_THRESHOLD,
    max_search_pixels: int = DEFAULT_MAX_SEARCH_PIXELS,
    search_step_pixels: int = DEFAULT_SEARCH_STEP_PIXELS,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
) -> RiverbankCrossingResult:
    """Measure visual change crossing past a confirmed normal-waterline guide.

    Requires at least 2 guide points (a line) and one water-side point.
    Frames must share the same shape -- no alignment is performed here.
    Every sample and search patch is clipped to `reference_region`; a
    guide sitting too close to that region's edge for band_width_px to fit
    raises RiverbankCrossingError rather than silently measuring less area
    than configured. Deterministic: the same inputs always produce the
    same result.
    """

    if len(guide_points) < 2:
        raise RiverbankCrossingError("A riverbank-crossing guide needs at least 2 points")
    if band_width_px <= 0:
        raise RiverbankCrossingError("band_width_px must be greater than 0")
    if search_step_pixels <= 0:
        raise RiverbankCrossingError("search_step_pixels must be greater than 0")
    if max_search_pixels <= 0:
        raise RiverbankCrossingError("max_search_pixels must be greater than 0")
    if sample_count < 2:
        raise RiverbankCrossingError("sample_count must be at least 2")
    if not math.isfinite(crossing_threshold) or not 0.0 <= crossing_threshold <= 1.0:
        raise RiverbankCrossingError("crossing_threshold must be a finite number between 0 and 1")
    if baseline_frame.shape != current_frame.shape:
        raise RiverbankCrossingError("Baseline and current frames must have the same shape")

    frame_height, frame_width = baseline_frame.shape[:2]
    region_bounds = _region_pixel_bounds(frame_width, frame_height, reference_region)
    pixel_points = [_point_pixels(frame_width, frame_height, point) for point in guide_points]
    water_side_pixel = _point_pixels(frame_width, frame_height, water_side_point)

    segments, lengths = _segments_and_lengths(pixel_points)
    total_length = sum(lengths)
    if total_length <= 0:
        raise RiverbankCrossingError("Guide points must not all collapse to the same pixel")

    # Orientation (which normal direction is "land") is decided ONCE, from
    # the guide segment nearest the water-side point, then applied to every
    # sample's own local normal -- deciding it independently per sample
    # (each tested against the same single water_side_point) can flip sign
    # between sections of a strongly curved guide, since a curve can put
    # different segments' normals on opposite sides of that one point.
    nearest_point, nearest_normal = _nearest_point_and_normal(segments, lengths, water_side_pixel)
    flip_to_land = bool(np.dot(nearest_normal, water_side_pixel - nearest_point) > 0)

    samples: list[SampleResult] = []
    for index in range(sample_count):
        distance = total_length * index / (sample_count - 1)
        point, normal = _point_and_normal_at(segments, lengths, distance)
        land_normal = -normal if flip_to_land else normal
        water_normal = -land_normal

        land_score = _patch_change_score_at(
            baseline_frame, current_frame, point, land_normal, band_width_px, region_bounds
        )
        water_score = _patch_change_score_at(
            baseline_frame, current_frame, point, water_normal, band_width_px, region_bounds
        )
        if land_score is None or water_score is None:
            # Not enough watched-region area survived clipping to judge this
            # point at all -- excluded rather than guessed at.
            continue

        crossed = land_score >= crossing_threshold and water_score < crossing_threshold
        extent = (
            _search_crossing_extent(
                baseline_frame,
                current_frame,
                point,
                land_normal,
                band_width_px,
                region_bounds,
                crossing_threshold,
                max_search_pixels,
                search_step_pixels,
            )
            if crossed
            else 0.0
        )

        samples.append(
            SampleResult(
                point_x=round(point[0] / frame_width * 100.0, 4),
                point_y=round(point[1] / frame_height * 100.0, 4),
                distance_px=distance,
                land_change_score=land_score,
                water_change_score=water_score,
                crossed=crossed,
                crossing_extent_pixels=extent,
            )
        )

    if not samples:
        raise RiverbankCrossingError(
            "No sample point along this guide had enough watched-region area to measure"
        )

    crossed_count = sum(1 for sample in samples if sample.crossed)
    crossed_line_percentage = round(100.0 * crossed_count / len(samples), 2)
    changed_bank_length_percentage = round(_crossed_arc_length_percentage(samples, total_length), 2)
    maximum_crossing_pixels = round(
        max((sample.crossing_extent_pixels for sample in samples), default=0.0), 2
    )

    return RiverbankCrossingResult(
        crossed_line_percentage=crossed_line_percentage,
        changed_bank_length_percentage=changed_bank_length_percentage,
        maximum_crossing_pixels=maximum_crossing_pixels,
        band_width_px=band_width_px,
        crossing_threshold=crossing_threshold,
        sample_count=len(samples),
        samples=tuple(samples),
    )


def _region_value(reference_region: ReferenceRegionInput, field_name: str) -> float:
    if isinstance(reference_region, Mapping):
        if field_name not in reference_region:
            raise RiverbankCrossingError(f"Reference region is missing '{field_name}'")
        value = reference_region[field_name]
    else:
        try:
            value = getattr(reference_region, field_name)
        except AttributeError as error:
            raise RiverbankCrossingError(f"Reference region is missing '{field_name}'") from error

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RiverbankCrossingError(f"Reference region field '{field_name}' must be a number")
    return float(value)


def _region_pixel_bounds(
    frame_width: int, frame_height: int, reference_region: ReferenceRegionInput
) -> _RegionBounds:
    region_x = _region_value(reference_region, "x")
    region_y = _region_value(reference_region, "y")
    region_width = _region_value(reference_region, "width")
    region_height = _region_value(reference_region, "height")

    if region_x < 0 or region_y < 0:
        raise RiverbankCrossingError("Reference region x and y must be 0 or greater")
    if region_width <= 0 or region_height <= 0:
        raise RiverbankCrossingError("Reference region width and height must be greater than 0")
    if region_x + region_width > 100 or region_y + region_height > 100:
        raise RiverbankCrossingError("Reference region must fit inside the 0-100 image area")

    left = math.floor(frame_width * region_x / 100.0)
    top = math.floor(frame_height * region_y / 100.0)
    right = math.ceil(frame_width * (region_x + region_width) / 100.0)
    bottom = math.ceil(frame_height * (region_y + region_height) / 100.0)

    left = min(max(left, 0), frame_width - 1)
    top = min(max(top, 0), frame_height - 1)
    right = min(max(right, left + 1), frame_width)
    bottom = min(max(bottom, top + 1), frame_height)
    return left, top, right, bottom


def _point_value(point: WaterlinePointInput, field_name: str) -> float:
    if isinstance(point, Mapping):
        if field_name not in point:
            raise RiverbankCrossingError(f"Waterline point is missing '{field_name}'")
        value = point[field_name]
    else:
        try:
            value = getattr(point, field_name)
        except AttributeError as error:
            raise RiverbankCrossingError(f"Waterline point is missing '{field_name}'") from error

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RiverbankCrossingError(f"Waterline point field '{field_name}' must be a number")
    return float(value)


def _point_pixels(
    frame_width: int, frame_height: int, point: WaterlinePointInput
) -> NDArray[np.float64]:
    x_pct = _point_value(point, "x")
    y_pct = _point_value(point, "y")
    if x_pct < 0 or x_pct > 100 or y_pct < 0 or y_pct > 100:
        raise RiverbankCrossingError("Waterline point must fit inside the 0-100 image area")

    x = min(max(round(frame_width * x_pct / 100.0), 0), frame_width - 1)
    y = min(max(round(frame_height * y_pct / 100.0), 0), frame_height - 1)
    return np.array([float(x), float(y)])


def _segments_and_lengths(
    pixel_points: Sequence[NDArray[np.float64]],
) -> tuple[list[tuple[NDArray[np.float64], NDArray[np.float64]]], list[float]]:
    segments = [(pixel_points[i], pixel_points[i + 1]) for i in range(len(pixel_points) - 1)]
    lengths = [float(np.linalg.norm(end - start)) for start, end in segments]
    return segments, lengths


def _point_and_normal_at(
    segments: Sequence[tuple[NDArray[np.float64], NDArray[np.float64]]],
    lengths: Sequence[float],
    distance: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return the polyline point and its local outward normal at one arc-length distance."""

    remaining = distance
    for (start, end), length in zip(segments, lengths, strict=True):
        if length == 0:
            continue
        if remaining <= length:
            tangent = (end - start) / length
            point = start + (end - start) * (remaining / length)
            return point, np.array([-tangent[1], tangent[0]])
        remaining -= length

    start, end = segments[-1]
    length = lengths[-1]
    tangent = (end - start) / length if length else np.array([0.0, 0.0])
    return end, np.array([-tangent[1], tangent[0]])


def _nearest_point_and_normal(
    segments: Sequence[tuple[NDArray[np.float64], NDArray[np.float64]]],
    lengths: Sequence[float],
    target: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return the polyline point closest to `target`, and that segment's normal.

    Used once per guide to decide a single, consistent land/water orientation
    -- see the "flip_to_land" comment in evaluate_riverbank_crossing.
    """

    best_distance_sq = math.inf
    best_point: NDArray[np.float64] | None = None
    best_normal: NDArray[np.float64] | None = None
    for (start, end), length in zip(segments, lengths, strict=True):
        if length == 0:
            continue
        tangent = (end - start) / length
        t = float(np.dot(target - start, end - start) / (length * length))
        t = min(max(t, 0.0), 1.0)
        candidate = start + (end - start) * t
        distance_sq = float(np.sum((target - candidate) ** 2))
        if distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            best_point = candidate
            best_normal = np.array([-tangent[1], tangent[0]])

    if best_point is None or best_normal is None:
        raise RiverbankCrossingError("Guide points must not all collapse to the same pixel")
    return best_point, best_normal


def _patch_change_score_at(
    baseline_frame: FrameArray,
    current_frame: FrameArray,
    point: NDArray[np.float64],
    direction: NDArray[np.float64],
    band_width_px: int,
    region_bounds: _RegionBounds,
    *,
    distance: float | None = None,
) -> float | None:
    """Compare a small patch offset from `point` along `direction`, on both frames.

    Returns None when the patch, after clipping to `region_bounds` (the
    watched region, never the whole frame), has no valid area left -- e.g.
    a guide traced close to the region's edge, or a search step that has
    marched outside it.
    """

    norm = float(np.linalg.norm(direction))
    unit_direction = direction / norm if norm > 0 else direction
    offset = band_width_px / 2.0 if distance is None else float(distance)
    center = point + unit_direction * offset

    region_left, region_top, region_right, region_bottom = region_bounds
    half = band_width_px / 2.0
    x0 = max(int(round(center[0] - half)), region_left)
    y0 = max(int(round(center[1] - half)), region_top)
    x1 = min(int(round(center[0] + half)), region_right)
    y1 = min(int(round(center[1] + half)), region_bottom)
    if x1 <= x0 or y1 <= y0:
        return None

    baseline_patch = baseline_frame[y0:y1, x0:x1]
    current_patch = current_frame[y0:y1, x0:x1]
    if baseline_patch.size == 0:
        return None
    return patch_change_score(baseline_patch, current_patch)


def _search_crossing_extent(
    baseline_frame: FrameArray,
    current_frame: FrameArray,
    point: NDArray[np.float64],
    land_normal: NDArray[np.float64],
    band_width_px: int,
    region_bounds: _RegionBounds,
    crossing_threshold: float,
    max_search_pixels: int,
    search_step_pixels: int,
) -> float:
    """Find the farthest distance from the line where the land-side change is still elevated."""

    farthest = 0.0
    distance = float(search_step_pixels)
    while distance <= max_search_pixels:
        score = _patch_change_score_at(
            baseline_frame,
            current_frame,
            point,
            land_normal,
            band_width_px,
            region_bounds,
            distance=distance,
        )
        if score is None:
            # Left the watched region going further out along a fixed
            # direction from a rectangle never comes back in, so there is
            # nothing more this search could find.
            break
        if score >= crossing_threshold:
            farthest = distance
        distance += search_step_pixels
    return farthest


def _crossed_arc_length_percentage(samples: Sequence[SampleResult], total_length: float) -> float:
    """Percentage of the guide's arc length covered by crossed sample points.

    A different, length-weighted number from crossed_line_percentage (a
    simple point-count ratio): each sample "owns" the span between the
    midpoints to its neighbors (or the guide's start/end for the first/last
    sample), so this reflects how much of the physical bank is affected, not
    just how many sample points happened to land on it. Uses each sample's
    own recorded distance_px rather than assuming even spacing, since a
    sample excluded for insufficient watched-region area (see
    evaluate_riverbank_crossing) can leave an uneven gap between the ones
    that remain.
    """

    sample_count = len(samples)
    if sample_count < 2 or total_length <= 0:
        return 0.0

    covered = 0.0
    for index, sample in enumerate(samples):
        if not sample.crossed:
            continue
        previous_distance = samples[index - 1].distance_px if index > 0 else 0.0
        next_distance = samples[index + 1].distance_px if index < sample_count - 1 else total_length
        left_midpoint = (previous_distance + sample.distance_px) / 2.0
        right_midpoint = (sample.distance_px + next_distance) / 2.0
        covered += max(right_midpoint - left_midpoint, 0.0)
    return 100.0 * covered / total_length

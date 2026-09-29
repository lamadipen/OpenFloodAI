"""Riverbank-crossing evidence geometry (Issue #200 / OF-088).

Given a site's confirmed normal-waterline guide (a human-traced polyline)
and one point marking which side of it is normally water, this measures
visual change in a narrow band along the LAND side of the line that does
NOT also show up on the WATER side of the line. That differential check is
what keeps a uniform lighting/exposure shift (glare, dusk, a passing cloud)
from being misread as water crossing the line -- a global change shows up
on both sides equally and is never flagged.

This module does not perform camera alignment between the two frames; see
`openfloodai.evidence.adapters.riverbank_crossing` for how that gap is
surfaced as degraded evidence rather than a silent assumption.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from openfloodai.vision.simple_signals import FrameArray, patch_change_score

DEFAULT_BAND_WIDTH_PX = 10
DEFAULT_CROSSING_THRESHOLD = 0.08
DEFAULT_MAX_SEARCH_PIXELS = 40
DEFAULT_SEARCH_STEP_PIXELS = 4
DEFAULT_SAMPLE_COUNT = 20


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
    Deterministic: the same inputs always produce the same result.
    """

    if len(guide_points) < 2:
        raise RiverbankCrossingError("A riverbank-crossing guide needs at least 2 points")
    if band_width_px <= 0:
        raise RiverbankCrossingError("band_width_px must be greater than 0")
    if sample_count < 2:
        raise RiverbankCrossingError("sample_count must be at least 2")
    if baseline_frame.shape != current_frame.shape:
        raise RiverbankCrossingError("Baseline and current frames must have the same shape")

    frame_height, frame_width = baseline_frame.shape[:2]
    pixel_points = [_point_pixels(frame_width, frame_height, point) for point in guide_points]
    water_side_pixel = _point_pixels(frame_width, frame_height, water_side_point)

    segments, lengths = _segments_and_lengths(pixel_points)
    total_length = sum(lengths)
    if total_length <= 0:
        raise RiverbankCrossingError("Guide points must not all collapse to the same pixel")

    samples: list[SampleResult] = []
    for index in range(sample_count):
        distance = total_length * index / (sample_count - 1)
        point, normal = _point_and_normal_at(segments, lengths, distance)
        land_normal = _orient_toward_land(normal, point, water_side_pixel)
        water_normal = -land_normal

        land_score = _patch_change_score_at(
            baseline_frame, current_frame, point, land_normal, band_width_px
        )
        water_score = _patch_change_score_at(
            baseline_frame, current_frame, point, water_normal, band_width_px
        )
        crossed = land_score >= crossing_threshold and water_score < crossing_threshold
        extent = (
            _search_crossing_extent(
                baseline_frame,
                current_frame,
                point,
                land_normal,
                band_width_px,
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
                land_change_score=land_score,
                water_change_score=water_score,
                crossed=crossed,
                crossing_extent_pixels=extent,
            )
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


def _orient_toward_land(
    normal: NDArray[np.float64], point: NDArray[np.float64], water_side_pixel: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Flip `normal` so it points away from the water side, using one reference point.

    Done per sample point (each with its own local normal) rather than once
    for the whole line, so a curved guide still gets a correctly oriented
    land direction at every point along it.
    """

    toward_water_side = water_side_pixel - point
    if np.dot(normal, toward_water_side) > 0:
        return -normal
    return normal


def _patch_change_score_at(
    baseline_frame: FrameArray,
    current_frame: FrameArray,
    point: NDArray[np.float64],
    direction: NDArray[np.float64],
    band_width_px: int,
    *,
    distance: float | None = None,
) -> float:
    """Compare a small patch offset from `point` along `direction`, on both frames."""

    norm = float(np.linalg.norm(direction))
    unit_direction = direction / norm if norm > 0 else direction
    offset = band_width_px / 2.0 if distance is None else float(distance)
    center = point + unit_direction * offset

    frame_height, frame_width = baseline_frame.shape[:2]
    half = band_width_px / 2.0
    x0 = min(max(int(round(center[0] - half)), 0), frame_width - 1)
    y0 = min(max(int(round(center[1] - half)), 0), frame_height - 1)
    x1 = min(max(int(round(center[0] + half)), x0 + 1), frame_width)
    y1 = min(max(int(round(center[1] + half)), y0 + 1), frame_height)

    baseline_patch = baseline_frame[y0:y1, x0:x1]
    current_patch = current_frame[y0:y1, x0:x1]
    if baseline_patch.size == 0:
        return 0.0
    return patch_change_score(baseline_patch, current_patch)


def _search_crossing_extent(
    baseline_frame: FrameArray,
    current_frame: FrameArray,
    point: NDArray[np.float64],
    land_normal: NDArray[np.float64],
    band_width_px: int,
    crossing_threshold: float,
    max_search_pixels: int,
    search_step_pixels: int,
) -> float:
    """Find the farthest distance from the line where the land-side change is still elevated."""

    farthest = 0.0
    distance = float(search_step_pixels)
    while distance <= max_search_pixels:
        score = _patch_change_score_at(
            baseline_frame, current_frame, point, land_normal, band_width_px, distance=distance
        )
        if score >= crossing_threshold:
            farthest = distance
        distance += search_step_pixels
    return farthest


def _crossed_arc_length_percentage(samples: Sequence[SampleResult], total_length: float) -> float:
    """Percentage of the guide's arc length covered by crossed sample points.

    A different, length-weighted number from crossed_line_percentage (a
    simple point-count ratio): each interior sample "owns" the arc length
    between its neighbors' midpoints, and the two endpoint samples own half
    that much, so this reflects how much of the physical bank is affected,
    not just how many sample points happened to land on it.
    """

    sample_count = len(samples)
    if sample_count < 2 or total_length <= 0:
        return 0.0

    spacing = total_length / (sample_count - 1)
    covered = 0.0
    for index, sample in enumerate(samples):
        if not sample.crossed:
            continue
        weight = spacing / 2.0 if index in (0, sample_count - 1) else spacing
        covered += weight
    return 100.0 * covered / total_length

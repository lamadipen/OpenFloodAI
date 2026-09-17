"""Local review images for visual-change POC runs."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from openfloodai.review.sample_quality import is_normal_baseline_confirmed
from openfloodai.vision.simple_signals import FrameArray


class ReviewImageError(ValueError):
    """Raised when local review images cannot be generated."""


class ReferenceRegionLike(Protocol):
    """Shape shared by config reference regions and test helpers."""

    @property
    def x(self) -> float: ...

    @property
    def y(self) -> float: ...

    @property
    def width(self) -> float: ...

    @property
    def height(self) -> float: ...


type ReferenceRegionInput = Mapping[str, object] | ReferenceRegionLike


class WaterlinePointLike(Protocol):
    """Shape shared by config waterline points and test helpers."""

    @property
    def x(self) -> float: ...

    @property
    def y(self) -> float: ...


type WaterlinePointInput = Mapping[str, object] | WaterlinePointLike


class NormalWaterlineGuideLike(Protocol):
    """Shape shared by the config's NormalWaterlineGuide dataclass and raw dicts."""

    @property
    def status(self) -> str: ...

    @property
    def normal_condition(self) -> bool: ...

    @property
    def points(self) -> Sequence[WaterlinePointInput]: ...


type NormalWaterlineGuideInput = Mapping[str, object] | NormalWaterlineGuideLike


@dataclass(frozen=True)
class ReviewImageSet:
    """Paths and metadata for one local visual-change review image set."""

    baseline_frame_index: int
    changed_frame_index: int
    change_score: float
    baseline_image_path: str
    changed_image_path: str
    comparison_image_path: str
    overlay_image_paths: tuple[str, ...]
    reference_region_used: bool


def generate_biggest_change_review_images(
    frames: Sequence[FrameArray],
    output_dir: Path,
    *,
    reference_region: ReferenceRegionInput | None = None,
    normal_waterline_guides: Sequence[NormalWaterlineGuideInput] | None = None,
    evidence_usability_note: str | None = None,
    prefix: str = "review",
    frame_times: tuple[float, float] | None = None,
) -> ReviewImageSet:
    """Save before/after/comparison images for the frame with the biggest change."""

    if len(frames) < 2:
        raise ReviewImageError("At least two frames are required to generate review images")
    if not prefix.strip():
        raise ReviewImageError("Image prefix must be non-empty")
    if output_dir.exists() and not output_dir.is_dir():
        raise ReviewImageError(f"Review image output path is not a directory: {output_dir}")

    prepared_frames = [_prepare_image_frame(frame) for frame in frames]
    baseline_frame = prepared_frames[0]
    changed_frame_index, change_score = _biggest_change_from_baseline(
        prepared_frames,
        reference_region=reference_region,
    )
    changed_frame = prepared_frames[changed_frame_index]
    if frame_times is not None:
        baseline_frame = _with_time_caption(baseline_frame, frame_times[0])
        changed_frame = _with_time_caption(changed_frame, frame_times[1])
    comparison_frame = np.hstack([baseline_frame, changed_frame])

    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = output_dir / f"{prefix}-baseline.png"
    changed_path = output_dir / f"{prefix}-changed.png"
    comparison_path = output_dir / f"{prefix}-comparison.png"
    overlay_paths: tuple[str, ...] = ()

    _write_image(baseline_path, baseline_frame)
    _write_image(changed_path, changed_frame)
    _write_image(comparison_path, comparison_frame)

    if reference_region is not None:
        baseline_overlay_frame = _draw_reference_region_box(prepared_frames[0], reference_region)
        changed_overlay_frame = _draw_reference_region_box(
            prepared_frames[changed_frame_index], reference_region
        )
        if normal_waterline_guides:
            baseline_overlay_frame = _draw_normal_waterline_guides_overlay(
                baseline_overlay_frame, normal_waterline_guides
            )
            changed_overlay_frame = _draw_normal_waterline_guides_overlay(
                changed_overlay_frame, normal_waterline_guides
            )
        if frame_times is not None:
            baseline_overlay_frame = _with_time_caption(
                baseline_overlay_frame, frame_times[0], extra_line=evidence_usability_note
            )
            changed_overlay_frame = _with_time_caption(
                changed_overlay_frame, frame_times[1], extra_line=evidence_usability_note
            )
        comparison_overlay_frame = np.hstack([baseline_overlay_frame, changed_overlay_frame])
        baseline_overlay_path = output_dir / f"{prefix}-baseline-overlay.png"
        changed_overlay_path = output_dir / f"{prefix}-changed-overlay.png"
        comparison_overlay_path = output_dir / f"{prefix}-comparison-overlay.png"

        _write_image(baseline_overlay_path, baseline_overlay_frame)
        _write_image(changed_overlay_path, changed_overlay_frame)
        _write_image(comparison_overlay_path, comparison_overlay_frame)
        overlay_paths = (
            str(baseline_overlay_path),
            str(changed_overlay_path),
            str(comparison_overlay_path),
        )

    return ReviewImageSet(
        baseline_frame_index=0,
        changed_frame_index=changed_frame_index,
        change_score=change_score,
        baseline_image_path=str(baseline_path),
        changed_image_path=str(changed_path),
        comparison_image_path=str(comparison_path),
        overlay_image_paths=overlay_paths,
        reference_region_used=reference_region is not None,
    )


def render_pair_comparison_overlay(
    baseline_frame: FrameArray,
    other_frame: FrameArray,
    *,
    reference_region: ReferenceRegionInput | None = None,
    normal_waterline_guides: Sequence[NormalWaterlineGuideInput] | None = None,
) -> NDArray[np.uint8]:
    """Return a baseline-vs-other frame, side by side, with the watched area boxed.

    Unlike `generate_biggest_change_review_images` (which searches many
    frames for the single biggest change and writes files for it), this
    takes exactly the two frames the caller already chose and returns the
    combined image in memory — used to build an on-demand comparison for
    whichever day a reviewer has selected, not just the run's one
    biggest-change day.
    """

    prepared_baseline = _prepare_image_frame(baseline_frame)
    prepared_other = _prepare_image_frame(other_frame)
    if prepared_baseline.shape[0] != prepared_other.shape[0]:
        raise ReviewImageError("Images must have matching height to compare side by side.")

    if reference_region is not None:
        prepared_baseline = _draw_reference_region_box(prepared_baseline, reference_region)
        prepared_other = _draw_reference_region_box(prepared_other, reference_region)
        if normal_waterline_guides:
            prepared_baseline = _draw_normal_waterline_guides_overlay(
                prepared_baseline, normal_waterline_guides
            )
            prepared_other = _draw_normal_waterline_guides_overlay(
                prepared_other, normal_waterline_guides
            )

    return cast(NDArray[np.uint8], np.hstack([prepared_baseline, prepared_other]))


def encode_png(frame: NDArray[np.uint8]) -> bytes:
    """Encode a frame as PNG bytes, for serving without writing to disk."""

    ok, buffer = cv2.imencode(".png", frame)
    if not ok:
        raise ReviewImageError("Could not encode comparison image as PNG.")
    return bytes(buffer)


def _prepare_image_frame(frame: FrameArray) -> NDArray[np.uint8]:
    if not isinstance(frame, np.ndarray):
        raise ReviewImageError("Frame must be a NumPy array")
    if frame.size == 0:
        raise ReviewImageError("Frame must not be empty")
    if frame.ndim not in {2, 3}:
        raise ReviewImageError("Frame must be a 2D grayscale or 3D color array")
    if frame.ndim == 3 and frame.shape[2] not in {1, 3, 4}:
        raise ReviewImageError("Color frame must have 1, 3, or 4 channels")
    if not np.issubdtype(frame.dtype, np.number):
        raise ReviewImageError("Frame values must be numeric")

    numeric_frame = frame.astype(np.float64)
    if not bool(np.isfinite(numeric_frame).all()):
        raise ReviewImageError("Frame values must be finite")

    if numeric_frame.max() <= 1.0:
        numeric_frame = numeric_frame * 255.0

    clipped_frame = np.clip(numeric_frame, 0, 255).astype(np.uint8)
    if clipped_frame.ndim == 2:
        return cast(NDArray[np.uint8], cv2.cvtColor(clipped_frame, cv2.COLOR_GRAY2BGR))
    if clipped_frame.shape[2] == 1:
        return cast(NDArray[np.uint8], cv2.cvtColor(clipped_frame[:, :, 0], cv2.COLOR_GRAY2BGR))
    if clipped_frame.shape[2] == 4:
        return clipped_frame[:, :, :3]

    return clipped_frame


def _biggest_change_from_baseline(
    frames: Sequence[NDArray[np.uint8]],
    *,
    reference_region: ReferenceRegionInput | None,
) -> tuple[int, float]:
    baseline_frame = frames[0]
    baseline_compare_frame = _comparison_frame(baseline_frame, reference_region)
    biggest_index = 1
    biggest_score = -1.0

    for frame_index, frame in enumerate(frames[1:], start=1):
        if frame.shape != baseline_frame.shape:
            raise ReviewImageError("All frames must have the same shape")

        score = _change_score(baseline_compare_frame, _comparison_frame(frame, reference_region))
        if score > biggest_score:
            biggest_index = frame_index
            biggest_score = score

    return biggest_index, round(biggest_score, 6)


def _comparison_frame(
    frame: NDArray[np.uint8],
    reference_region: ReferenceRegionInput | None,
) -> NDArray[np.float64]:
    if reference_region is None:
        return _to_grayscale(frame)

    left, top, right, bottom = _reference_region_pixels(frame, reference_region)
    return _to_grayscale(frame[top:bottom, left:right])


def _change_score(
    baseline_frame: NDArray[np.float64],
    current_frame: NDArray[np.float64],
) -> float:
    return float(np.abs(current_frame - baseline_frame).mean() / 255.0)


def _to_grayscale(frame: NDArray[np.uint8]) -> NDArray[np.float64]:
    return frame[:, :, :3].mean(axis=2)


def _draw_reference_region_box(
    frame: NDArray[np.uint8],
    reference_region: ReferenceRegionInput,
) -> NDArray[np.uint8]:
    left, top, right, bottom = _reference_region_pixels(frame, reference_region)
    output_frame = frame.copy()
    cv2.rectangle(output_frame, (left, top), (right - 1, bottom - 1), (0, 0, 0), 3)
    cv2.rectangle(output_frame, (left, top), (right - 1, bottom - 1), (0, 255, 255), 1)
    return output_frame


def _guide_field(source: object, field_name: str) -> object:
    if isinstance(source, Mapping):
        return source.get(field_name)
    return getattr(source, field_name, None)


def _is_guide_trusted(guide: NormalWaterlineGuideInput) -> bool:
    """A guide is only trustworthy when truly confirmed, not merely present.

    Mirrors openfloodai.review.sample_quality.is_normal_baseline_confirmed exactly
    (status == "confirmed" AND normal_condition is True), so this drawing code
    can never reintroduce the "draft guide drawn as if trusted" bug fixed
    for PR #171/OF-083.
    """

    return is_normal_baseline_confirmed(
        [
            {
                "status": _guide_field(guide, "status"),
                "normal_condition": _guide_field(guide, "normal_condition"),
            }
        ]
    )


def _point_pixels(frame: NDArray[np.uint8], point: WaterlinePointInput) -> tuple[int, int]:
    point_x = _point_value(point, "x")
    point_y = _point_value(point, "y")
    if point_x < 0 or point_x > 100 or point_y < 0 or point_y > 100:
        raise ReviewImageError("Waterline point must fit inside the 0-100 image area")

    frame_height, frame_width = frame.shape[:2]
    x = min(max(round(frame_width * point_x / 100.0), 0), frame_width - 1)
    y = min(max(round(frame_height * point_y / 100.0), 0), frame_height - 1)
    return x, y


def _point_value(point: WaterlinePointInput, field_name: str) -> float:
    if isinstance(point, Mapping):
        if field_name not in point:
            raise ReviewImageError(f"Waterline point is missing '{field_name}'")
        value = point[field_name]
    else:
        try:
            value = getattr(point, field_name)
        except AttributeError as error:
            raise ReviewImageError(f"Waterline point is missing '{field_name}'") from error

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ReviewImageError(f"Waterline point field '{field_name}' must be a number")
    return float(value)


def _draw_normal_waterline_guides_overlay(
    frame: NDArray[np.uint8],
    normal_waterline_guides: Sequence[NormalWaterlineGuideInput],
) -> NDArray[np.uint8]:
    """Burn each truly confirmed normal-waterline guide onto a frame as a polyline.

    Draws nothing for a guide unless it is truly confirmed, so a draft or
    invalid guide is never shown as if trusted.
    """

    output_frame = frame.copy()
    for guide in normal_waterline_guides:
        if not _is_guide_trusted(guide):
            continue

        points = cast(Sequence[WaterlinePointInput], _guide_field(guide, "points") or ())
        pixel_points = np.array(
            [_point_pixels(output_frame, point) for point in points],
            dtype=np.int32,
        ).reshape((-1, 1, 2))
        if len(pixel_points) < 2:
            continue
        cv2.polylines(output_frame, [pixel_points], False, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.polylines(output_frame, [pixel_points], False, (216, 64, 29), 2, cv2.LINE_AA)

    return output_frame


def _reference_region_pixels(
    frame: NDArray[np.uint8],
    reference_region: ReferenceRegionInput,
) -> tuple[int, int, int, int]:
    region_x = _region_value(reference_region, "x")
    region_y = _region_value(reference_region, "y")
    region_width = _region_value(reference_region, "width")
    region_height = _region_value(reference_region, "height")

    if region_x < 0 or region_y < 0:
        raise ReviewImageError("Reference region x and y must be 0 or greater")
    if region_width <= 0 or region_height <= 0:
        raise ReviewImageError("Reference region width and height must be greater than 0")
    if region_x + region_width > 100 or region_y + region_height > 100:
        raise ReviewImageError("Reference region must fit inside the 0-100 image area")

    frame_height, frame_width = frame.shape[:2]
    left = math.floor(frame_width * region_x / 100.0)
    top = math.floor(frame_height * region_y / 100.0)
    right = math.ceil(frame_width * (region_x + region_width) / 100.0)
    bottom = math.ceil(frame_height * (region_y + region_height) / 100.0)

    left = min(max(left, 0), frame_width - 1)
    top = min(max(top, 0), frame_height - 1)
    right = min(max(right, left + 1), frame_width)
    bottom = min(max(bottom, top + 1), frame_height)
    return left, top, right, bottom


def _region_value(reference_region: ReferenceRegionInput, field_name: str) -> float:
    if isinstance(reference_region, Mapping):
        if field_name not in reference_region:
            raise ReviewImageError(f"Reference region is missing '{field_name}'")
        value = reference_region[field_name]
    else:
        try:
            value = getattr(reference_region, field_name)
        except AttributeError as error:
            raise ReviewImageError(f"Reference region is missing '{field_name}'") from error

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ReviewImageError(f"Reference region field '{field_name}' must be a number")
    return float(value)


def _write_image(path: Path, frame: NDArray[np.uint8]) -> None:
    if not cv2.imwrite(str(path), frame):
        raise ReviewImageError(f"Could not write review image: {path}")


def _with_time_caption(
    frame: NDArray[np.uint8],
    second: float,
    *,
    extra_line: str | None = None,
) -> NDArray[np.uint8]:
    # A separate caption band preserves every pixel of the evidence image.
    band_height = 24 if extra_line is None else 44
    output = cv2.copyMakeBorder(
        frame, band_height, 0, 0, max(0, 180 - frame.shape[1]), cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )
    cv2.putText(
        output,
        f"Video: {second:g}s",
        (4, 17),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    if extra_line is not None:
        cv2.putText(
            output,
            extra_line,
            (4, 37),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 200, 255),
            1,
            cv2.LINE_AA,
        )
    return cast(NDArray[np.uint8], output)

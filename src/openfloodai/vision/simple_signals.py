"""Simple visual signal extraction from synthetic or decoded frames."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

FrameArray = NDArray[np.generic]


class VisualSignalError(ValueError):
    """Raised when a frame cannot be used for simple visual signals."""


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


def extract_frame_signals(
    frame: FrameArray,
    site_id: str,
    camera_id: str,
    *,
    timestamp: str | None = None,
    source_record_ids: list[str] | None = None,
) -> dict[str, object]:
    """Return simple visual measurements for one frame."""

    prepared_frame = _prepare_frame(frame)
    brightness_score = _brightness_score(prepared_frame)
    sharpness_score = _sharpness_score(prepared_frame)

    return _build_signal_record(
        site_id=site_id,
        camera_id=camera_id,
        timestamp=timestamp,
        source_record_ids=source_record_ids,
        signal_values={
            "brightness_score": brightness_score,
            "sharpness_score": sharpness_score,
        },
        human_summary=_frame_summary(brightness_score, sharpness_score),
    )


def extract_region_signals(
    frame: FrameArray,
    reference_region: ReferenceRegionInput,
    site_id: str,
    camera_id: str,
    *,
    timestamp: str | None = None,
    source_record_ids: list[str] | None = None,
) -> dict[str, object]:
    """Return simple visual measurements from one configured frame region."""

    prepared_frame = _prepare_frame(frame)
    crop = _crop_reference_region(prepared_frame, reference_region)
    brightness_score = _brightness_score(crop.frame)
    sharpness_score = _sharpness_score(crop.frame)

    return _build_signal_record(
        site_id=site_id,
        camera_id=camera_id,
        timestamp=timestamp,
        source_record_ids=source_record_ids,
        signal_values={
            "reference_region_used": True,
            "region_x": float(crop.x),
            "region_y": float(crop.y),
            "region_width": float(crop.width),
            "region_height": float(crop.height),
            "region_brightness_score": brightness_score,
            "region_sharpness_score": sharpness_score,
        },
        human_summary=_region_frame_summary(brightness_score, sharpness_score),
    )


def compare_frames(
    previous_frame: FrameArray,
    current_frame: FrameArray,
    site_id: str,
    camera_id: str,
    *,
    timestamp: str | None = None,
    source_record_ids: list[str] | None = None,
) -> dict[str, object]:
    """Return simple visual measurements comparing two frames."""

    previous = _prepare_frame(previous_frame)
    current = _prepare_frame(current_frame)
    if previous.shape != current.shape:
        raise VisualSignalError("Frames must have the same shape for comparison")

    brightness_score = _brightness_score(current)
    sharpness_score = _sharpness_score(current)
    frame_change_score = _frame_change_score(previous, current)

    return _build_signal_record(
        site_id=site_id,
        camera_id=camera_id,
        timestamp=timestamp,
        source_record_ids=source_record_ids,
        signal_values={
            "brightness_score": brightness_score,
            "sharpness_score": sharpness_score,
            "frame_change_score": frame_change_score,
        },
        human_summary=_comparison_summary(frame_change_score),
    )


def compare_region_signals(
    previous_frame: FrameArray,
    current_frame: FrameArray,
    reference_region: ReferenceRegionInput,
    site_id: str,
    camera_id: str,
    *,
    timestamp: str | None = None,
    source_record_ids: list[str] | None = None,
) -> dict[str, object]:
    """Return simple visual measurements comparing a configured region across two frames."""

    previous = _prepare_frame(previous_frame)
    current = _prepare_frame(current_frame)
    if previous.shape != current.shape:
        raise VisualSignalError("Frames must have the same shape for comparison")

    previous_crop = _crop_reference_region(previous, reference_region)
    current_crop = _crop_reference_region(current, reference_region)
    brightness_score = _brightness_score(current_crop.frame)
    sharpness_score = _sharpness_score(current_crop.frame)
    region_change_score = _frame_change_score(previous_crop.frame, current_crop.frame)
    band_scores = _region_band_change_scores(previous_crop.frame, current_crop.frame)
    strongest_changed_area = _strongest_changed_area(band_scores)
    evidence_state = _water_level_evidence_state(
        crop=current_crop,
        region_change_score=region_change_score,
        band_scores=band_scores,
    )

    return _build_signal_record(
        site_id=site_id,
        camera_id=camera_id,
        timestamp=timestamp,
        source_record_ids=source_record_ids,
        signal_values={
            "reference_region_used": True,
            "region_x": float(current_crop.x),
            "region_y": float(current_crop.y),
            "region_width": float(current_crop.width),
            "region_height": float(current_crop.height),
            "region_brightness_score": brightness_score,
            "region_sharpness_score": sharpness_score,
            "region_change_score": region_change_score,
            "upper_region_change_score": band_scores["upper"],
            "middle_region_change_score": band_scores["middle"],
            "lower_region_change_score": band_scores["lower"],
            "strongest_changed_area": strongest_changed_area,
            "water_level_evidence_state": evidence_state,
        },
        human_summary=_region_comparison_summary(
            region_change_score=region_change_score,
            strongest_changed_area=strongest_changed_area,
            evidence_state=evidence_state,
        ),
    )


def _build_signal_record(
    *,
    site_id: str,
    camera_id: str,
    timestamp: str | None,
    source_record_ids: list[str] | None,
    signal_values: Mapping[str, object],
    human_summary: str,
) -> dict[str, object]:
    if not site_id:
        raise VisualSignalError("site_id must be non-empty")
    if not camera_id:
        raise VisualSignalError("camera_id must be non-empty")

    record: dict[str, object] = {
        "contract_version": "v1",
        "record_id": f"visual-signal-{uuid4()}",
        "record_type": "visual_signal_output",
        "site_id": site_id,
        "camera_id": camera_id,
        "timestamp": timestamp or datetime.now(tz=UTC).isoformat(),
        "human_summary": human_summary,
    }
    record.update(signal_values)
    if source_record_ids is not None:
        record["source_record_ids"] = source_record_ids

    return record


@dataclass(frozen=True)
class RegionCrop:
    """Prepared pixel crop from a percentage-based reference region."""

    frame: NDArray[np.float64]
    x: int
    y: int
    width: int
    height: int


def _prepare_frame(frame: FrameArray) -> NDArray[np.float64]:
    if not isinstance(frame, np.ndarray):
        raise VisualSignalError("Frame must be a NumPy array")
    if frame.size == 0:
        raise VisualSignalError("Frame must not be empty")
    if frame.ndim not in {2, 3}:
        raise VisualSignalError("Frame must be a 2D grayscale or 3D color array")
    if frame.ndim == 3 and frame.shape[2] not in {1, 3, 4}:
        raise VisualSignalError("Color frame must have 1, 3, or 4 channels")
    if not np.issubdtype(frame.dtype, np.number):
        raise VisualSignalError("Frame values must be numeric")

    numeric_frame = frame.astype(np.float64)
    if not bool(np.isfinite(numeric_frame).all()):
        raise VisualSignalError("Frame values must be finite")

    if numeric_frame.max() > 1.0:
        numeric_frame = numeric_frame / 255.0

    return np.clip(numeric_frame, 0.0, 1.0)


def _crop_reference_region(
    frame: NDArray[np.float64],
    reference_region: ReferenceRegionInput,
) -> RegionCrop:
    region_x = _region_value(reference_region, "x")
    region_y = _region_value(reference_region, "y")
    region_width = _region_value(reference_region, "width")
    region_height = _region_value(reference_region, "height")

    if region_x < 0 or region_y < 0:
        raise VisualSignalError("Reference region x and y must be 0 or greater")
    if region_width <= 0 or region_height <= 0:
        raise VisualSignalError("Reference region width and height must be greater than 0")
    if region_x + region_width > 100 or region_y + region_height > 100:
        raise VisualSignalError("Reference region must fit inside the 0-100 image area")

    frame_height, frame_width = frame.shape[:2]
    left = math.floor(frame_width * region_x / 100.0)
    top = math.floor(frame_height * region_y / 100.0)
    right = math.ceil(frame_width * (region_x + region_width) / 100.0)
    bottom = math.ceil(frame_height * (region_y + region_height) / 100.0)

    left = min(max(left, 0), frame_width - 1)
    top = min(max(top, 0), frame_height - 1)
    right = min(max(right, left + 1), frame_width)
    bottom = min(max(bottom, top + 1), frame_height)

    return RegionCrop(
        frame=frame[top:bottom, left:right],
        x=left,
        y=top,
        width=right - left,
        height=bottom - top,
    )


def _region_value(reference_region: ReferenceRegionInput, field_name: str) -> float:
    if isinstance(reference_region, Mapping):
        if field_name not in reference_region:
            raise VisualSignalError(f"Reference region is missing '{field_name}'")
        value = reference_region[field_name]
    else:
        try:
            value = getattr(reference_region, field_name)
        except AttributeError as error:
            raise VisualSignalError(f"Reference region is missing '{field_name}'") from error

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise VisualSignalError(f"Reference region field '{field_name}' must be a number")
    return float(value)


def _brightness_score(frame: NDArray[np.float64]) -> float:
    return _rounded_score(float(frame.mean()))


def _sharpness_score(frame: NDArray[np.float64]) -> float:
    grayscale = _to_grayscale(frame)
    vertical_change = np.abs(np.diff(grayscale, axis=0)).mean() if grayscale.shape[0] > 1 else 0.0
    horizontal_change = np.abs(np.diff(grayscale, axis=1)).mean() if grayscale.shape[1] > 1 else 0.0
    return _rounded_score(float(min((vertical_change + horizontal_change) * 2.0, 1.0)))


def _frame_change_score(
    previous_frame: NDArray[np.float64],
    current_frame: NDArray[np.float64],
) -> float:
    if previous_frame.size == 0 or current_frame.size == 0:
        return 0.0
    return _rounded_score(float(np.abs(current_frame - previous_frame).mean()))


def _region_band_change_scores(
    previous_region: NDArray[np.float64],
    current_region: NDArray[np.float64],
) -> dict[str, float]:
    previous_bands = np.array_split(previous_region, 3, axis=0)
    current_bands = np.array_split(current_region, 3, axis=0)
    return {
        band_name: _frame_change_score(previous_band, current_band)
        for band_name, previous_band, current_band in zip(
            ("upper", "middle", "lower"),
            previous_bands,
            current_bands,
            strict=True,
        )
    }


def _strongest_changed_area(band_scores: Mapping[str, float]) -> str:
    return max(("upper", "middle", "lower"), key=lambda name: band_scores[name])


def _water_level_evidence_state(
    *,
    crop: RegionCrop,
    region_change_score: float,
    band_scores: Mapping[str, float],
) -> str:
    upper_change = band_scores["upper"]
    middle_change = band_scores["middle"]
    lower_change = band_scores["lower"]
    max_change = max(band_scores.values())
    min_change = min(band_scores.values())

    if crop.width < 2 or crop.height < 3:
        return "cannot_judge_region_too_small"
    if region_change_score <= 0.02:
        return "weak_visual_evidence"
    if min_change >= 0.08 and max_change - min_change <= 0.05:
        return "cannot_judge_whole_region_changed"
    if lower_change >= 0.05 and upper_change <= 0.05:
        return "useful_water_level_evidence"
    if middle_change >= 0.05 and upper_change <= 0.05:
        return "useful_water_level_evidence"
    return "weak_visual_evidence"


def _to_grayscale(frame: NDArray[np.float64]) -> NDArray[np.float64]:
    if frame.ndim == 2:
        return frame
    return frame[..., :3].mean(axis=2)


def _rounded_score(score: float) -> float:
    return round(min(max(score, 0.0), 1.0), 6)


def _frame_summary(brightness_score: float, sharpness_score: float) -> str:
    brightness_label = "bright" if brightness_score >= 0.5 else "dark"
    sharpness_label = "sharp" if sharpness_score >= 0.2 else "low-detail"
    return f"The frame is {brightness_label} with {sharpness_label} visual detail."


def _comparison_summary(frame_change_score: float) -> str:
    if frame_change_score >= 0.25:
        return "The current frame changed clearly compared to the previous frame."
    if frame_change_score > 0.0:
        return "The current frame changed slightly compared to the previous frame."
    return "The current frame looks unchanged compared to the previous frame."


def _region_frame_summary(brightness_score: float, sharpness_score: float) -> str:
    brightness_label = "bright" if brightness_score >= 0.5 else "dark"
    sharpness_label = "sharp" if sharpness_score >= 0.2 else "low-detail"
    return (
        "The configured reference region is "
        f"{brightness_label} with {sharpness_label} visual detail."
    )


def _region_comparison_summary(
    *,
    region_change_score: float,
    strongest_changed_area: str,
    evidence_state: str,
) -> str:
    if evidence_state == "cannot_judge_region_too_small":
        return "The watched region is too small to judge water-level evidence safely."
    if evidence_state == "cannot_judge_whole_region_changed":
        return (
            "The whole watched region changed, so this may be lighting, blur, "
            "or camera movement and needs human review."
        )
    if evidence_state == "useful_water_level_evidence":
        return (
            "The watched region changed most in the "
            f"{strongest_changed_area} part, which may be useful water-level evidence. "
            "This is not proof of flooding."
        )
    if region_change_score > 0.0:
        return (
            "The watched region changed only a little, so the water-level evidence "
            "is weak and needs human review."
        )
    return "The watched region looks unchanged compared to the previous frame."

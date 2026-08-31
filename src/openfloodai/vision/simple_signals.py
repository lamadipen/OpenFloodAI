"""Simple visual signal extraction from synthetic or decoded frames."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

FrameArray = NDArray[np.generic]


class VisualSignalError(ValueError):
    """Raised when a frame cannot be used for simple visual signals."""


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


def _build_signal_record(
    *,
    site_id: str,
    camera_id: str,
    timestamp: str | None,
    source_record_ids: list[str] | None,
    signal_values: Mapping[str, float],
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
    return _rounded_score(float(np.abs(current_frame - previous_frame).mean()))


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

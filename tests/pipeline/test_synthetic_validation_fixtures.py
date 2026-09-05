from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np
import pytest

from openfloodai.contracts import read_jsonl_records
from openfloodai.pipeline import run_local_poc_pipeline
from openfloodai.review import compare_label_records


class SyntheticVideoKind(StrEnum):
    RISING = "rising"
    FALLING = "falling"
    NO_CHANGE = "no_change"


def write_synthetic_validation_video(
    path: Path,
    kind: SyntheticVideoKind,
    *,
    frame_count: int = 60,
    frame_rate: float = 2.0,
) -> None:
    """Write a tiny deterministic waterline video for tests."""

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),  # type: ignore[attr-defined]
        frame_rate,
        (96, 64),
    )
    assert writer.isOpened(), f"Could not create synthetic video: {path}"
    try:
        for frame_index in range(frame_count):
            frame = np.zeros((64, 96, 3), dtype=np.uint8)
            frame[:32, :] = (200, 180, 150)
            frame[32:, :] = (60, 80, 95)
            if kind is SyntheticVideoKind.NO_CHANGE:
                water_top = 54
            else:
                progress = frame_index / max(frame_count - 1, 1)
                if kind is SyntheticVideoKind.FALLING:
                    progress = 1.0 - progress
                water_top = int(round(62 - progress * 40))
            frame[water_top:, :] = (130, 90, 40)
            frame[:, 44:52] = (150, 150, 140)
            frame[water_top:, 44:52] = (120, 95, 70)
            writer.write(frame)
    finally:
        writer.release()


def write_unreadable_video(path: Path) -> None:
    """Write a deterministic non-video file for unreadable-input tests."""

    path.write_text("not a video", encoding="utf-8")


@pytest.mark.parametrize(
    ("kind", "human_label"),
    [
        (SyntheticVideoKind.RISING, "water_rising"),
        (SyntheticVideoKind.FALLING, "water_falling"),
        (SyntheticVideoKind.NO_CHANGE, "no_clear_change"),
    ],
)
def test_synthetic_video_has_known_validation_result(
    tmp_path: Path,
    kind: SyntheticVideoKind,
    human_label: str,
) -> None:
    video_path = tmp_path / f"{kind.value}.avi"
    output_path = tmp_path / f"{kind.value}.jsonl"
    write_synthetic_validation_video(video_path, kind)

    run_local_poc_pipeline(
        video_path=video_path,
        site_id="synthetic-site",
        camera_id="synthetic-camera",
        output_path=output_path,
        time_windows=[(0, 30)],
    )
    records = read_jsonl_records(output_path)
    report = compare_label_records(
        system_records=records,
        human_labels=[
            {
                "video_id": video_path.stem,
                "time_window_seconds": [0, 30],
                "human_label": human_label,
            }
        ],
        video_id=video_path.stem,
    )

    assert report.agree_count == 1
    assert report.comparisons[0].result == "agree"


def test_synthetic_unreadable_video_returns_safe_health_output(tmp_path: Path) -> None:
    video_path = tmp_path / "unreadable.avi"
    output_path = tmp_path / "unreadable.jsonl"
    write_unreadable_video(video_path)

    summary = run_local_poc_pipeline(
        video_path=video_path,
        site_id="synthetic-site",
        camera_id="synthetic-camera",
        output_path=output_path,
        time_windows=[(0, 30)],
    )
    records = read_jsonl_records(output_path)

    assert summary["completed"] is False
    assert len(records) == 1
    assert records[0]["record_type"] == "camera_health_output"
    assert records[0]["input_quality_state"] == "UNKNOWN"

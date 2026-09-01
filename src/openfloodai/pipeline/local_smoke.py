"""End-to-end local smoke workflow for the OpenFloodAI POC."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from openfloodai.config import load_site_config
from openfloodai.contracts import read_jsonl_records
from openfloodai.contracts.local_store import JsonObject
from openfloodai.pipeline.local_poc import run_local_region_poc_pipeline
from openfloodai.replay import render_summary_markdown, summarize_jsonl_records
from openfloodai.review import build_operator_note, generate_biggest_change_review_images

DemoFrame = NDArray[np.uint8]


class LocalPocSmokeError(RuntimeError):
    """Raised when the local POC smoke workflow cannot complete."""


@dataclass(frozen=True)
class LocalPocSmokeResult:
    """Files created by one local POC smoke workflow run."""

    output_dir: str
    config_path: str
    video_path: str
    records_path: str
    summary_path: str
    operator_notes_path: str
    review_image_paths: tuple[str, str, str]
    records_written: int
    reference_region_used: bool


def run_local_poc_smoke(output_dir: Path) -> LocalPocSmokeResult:
    """Run a safe synthetic end-to-end local POC smoke workflow."""

    output_dir.mkdir(parents=True, exist_ok=True)

    frames = _demo_frames()
    video_path = output_dir / "demo-video.avi"
    config_path = output_dir / "demo-site-config.json"
    records_path = output_dir / "records.jsonl"
    summary_path = output_dir / "summary.md"
    operator_notes_path = output_dir / "operator-notes.txt"
    review_images_dir = output_dir / "review-images"

    _write_demo_video(video_path, frames)
    _write_demo_config(config_path)

    pipeline_summary = run_local_region_poc_pipeline(
        video_path=video_path,
        config_path=config_path,
        output_path=records_path,
    )
    if pipeline_summary.get("completed") is not True:
        raise LocalPocSmokeError("Local POC smoke workflow did not complete")
    records_written = pipeline_summary.get("records_written")
    if isinstance(records_written, bool) or not isinstance(records_written, int):
        raise LocalPocSmokeError("Local POC smoke workflow returned an invalid record count")

    site_config = load_site_config(config_path)
    if site_config.reference_region is None:
        raise LocalPocSmokeError("Local POC smoke workflow requires a reference_region")

    replay_summary = summarize_jsonl_records(records_path)
    summary_path.write_text(render_summary_markdown(replay_summary), encoding="utf-8")

    records = read_jsonl_records(records_path)
    operator_notes = _operator_notes(records)
    operator_notes_path.write_text("\n\n".join(operator_notes) + "\n", encoding="utf-8")

    review_image_set = generate_biggest_change_review_images(
        frames,
        review_images_dir,
        reference_region=site_config.reference_region,
        prefix="smoke",
    )

    return LocalPocSmokeResult(
        output_dir=str(output_dir),
        config_path=str(config_path),
        video_path=str(video_path),
        records_path=str(records_path),
        summary_path=str(summary_path),
        operator_notes_path=str(operator_notes_path),
        review_image_paths=(
            review_image_set.baseline_image_path,
            review_image_set.changed_image_path,
            review_image_set.comparison_image_path,
        ),
        records_written=records_written,
        reference_region_used=bool(pipeline_summary.get("reference_region_used")),
    )


def _demo_frames() -> list[DemoFrame]:
    frames: list[DemoFrame] = []
    for lower_half_value in (20, 90, 180):
        frame = np.zeros((64, 96, 3), dtype=np.uint8)
        frame[:32, :] = (170, 210, 230)
        frame[32:, :] = (20, 60, lower_half_value)
        frame[:, 44:52] = (140, 150, 150)
        frames.append(frame)
    return frames


def _write_demo_video(path: Path, frames: list[DemoFrame]) -> None:
    if not frames:
        raise LocalPocSmokeError("Demo video needs at least one frame")

    first_frame = frames[0]
    frame_height, frame_width = first_frame.shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 2.0, (frame_width, frame_height))
    if not writer.isOpened():
        raise LocalPocSmokeError(f"Could not create demo video: {path}")

    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()


def _write_demo_config(path: Path) -> None:
    config = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo River Bridge",
        "public_location": "Demo River near Example Town",
        "input_type": "local_video",
        "reference_region": {
            "x": 0,
            "y": 50,
            "width": 100,
            "height": 50,
        },
        "privacy_notes": "Synthetic smoke-test config. No real location or camera URL.",
    }
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _operator_notes(records: list[JsonObject]) -> list[str]:
    notes: list[str] = []
    for record in records:
        if record.get("record_type") in {"camera_health_output", "risk_state_output"}:
            notes.append(build_operator_note(record))
    return notes

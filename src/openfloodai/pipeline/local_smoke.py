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
from openfloodai.ingestion.evidence_sampling import SamplingSettings
from openfloodai.pipeline.local_poc import read_selected_frames, run_local_region_poc_pipeline
from openfloodai.replay import render_summary_markdown, summarize_jsonl_records
from openfloodai.review import build_operator_note, generate_biggest_change_review_images

DemoFrame = NDArray[np.uint8]


class LocalPocSmokeError(RuntimeError):
    """Raised when the local POC smoke workflow cannot complete."""


@dataclass(frozen=True)
class LocalPocSmokeResult:
    """Files created by one local POC review workflow run."""

    output_dir: str
    config_path: str
    video_path: str
    records_path: str
    summary_path: str
    operator_notes_path: str
    review_image_paths: tuple[str, ...]
    records_written: int
    reference_region_used: bool


def run_local_poc_smoke(output_dir: Path) -> LocalPocSmokeResult:
    """Run a safe synthetic end-to-end local POC smoke workflow."""

    output_dir.mkdir(parents=True, exist_ok=True)

    frames = _demo_frames()
    video_path = output_dir / "demo-video.avi"
    config_path = output_dir / "demo-site-config.json"

    _write_demo_video(video_path, frames)
    _write_demo_config(config_path)

    return run_local_video_review(
        video_path=video_path,
        config_path=config_path,
        output_dir=output_dir,
        image_prefix="smoke",
    )


def run_local_video_review(
    *,
    video_path: Path,
    config_path: Path,
    output_dir: Path,
    image_prefix: str = "review",
    time_windows: list[tuple[float, float]] | None = None,
    sampling: SamplingSettings | None = None,
) -> LocalPocSmokeResult:
    """Run the local POC review workflow for a real local video file."""

    if not image_prefix.strip() or Path(image_prefix).name != image_prefix:
        raise ValueError("Image prefix must be a non-empty filename without directories")
    output_dir.mkdir(parents=True, exist_ok=True)

    records_path = output_dir / "records.jsonl"
    summary_path = output_dir / "summary.md"
    operator_notes_path = output_dir / "operator-notes.txt"
    review_images_dir = output_dir / "review-images"

    pipeline_summary = run_local_region_poc_pipeline(
        video_path=video_path,
        config_path=config_path,
        output_path=records_path,
        time_windows=time_windows,
        sampling=sampling,
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

    review_image_paths: list[str] = []
    evidence_lines = ["", "## Sampled video evidence", ""]
    windows = [r for r in records if r.get("record_type") == "evidence_window_output"]
    # Remove only this workflow's previous images, so a failed window has no stale evidence.
    if review_images_dir.exists():
        for old in review_images_dir.iterdir():
            if old.is_file() and old.name.startswith(f"{image_prefix}-") and old.suffix == ".png":
                old.unlink()
    for index, window in enumerate(windows, start=1):
        bounds = window["time_window_seconds"]
        evidence_lines.extend(
            [
                f"### Period {bounds}",
                f"- Usable frames: {window['usable_frame_count']}",
                f"- Unusable frames: {window['unusable_frame_count']}",
                f"- Unusable reasons: {window['unusable_reasons']}",
                f"- Requested interval: {window['sample_interval_seconds']} seconds",
                f"- Actual largest sample gap: {window['actual_max_sample_gap_seconds']} seconds",
                f"- Sample times: {window['sampled_video_times']}",
                f"- Usable fraction of period: {window['usable_coverage_fraction']}",
                f"- Coverage sufficient: {window['coverage_sufficient']}",
                f"- Coverage note: {window['coverage_reason']}",
            ]
        )
        signals = [
            r
            for r in records
            if r.get("record_type") == "visual_signal_output"
            and r.get("evidence_window_seconds") == bounds
        ]
        if not signals:
            evidence_lines.append("- No usable comparison images. Result: cannot_compare.")
            continue
        signal = max(signals, key=lambda r: float(str(r.get("region_change_score", 0))))
        before, after = (
            int(str(signal["baseline_frame_index"])),
            int(str(signal["changed_frame_index"])),
        )
        frames = read_selected_frames(video_path, [before, after])
        image_set = generate_biggest_change_review_images(
            [frames[before], frames[after]],
            review_images_dir,
            reference_region=site_config.reference_region,
            prefix=_window_image_prefix(image_prefix, bounds, index, len(windows)),
            frame_times=(
                float(str(signal["comparison_start_seconds"])),
                float(str(signal["comparison_end_seconds"])),
            ),
        )
        paths = [
            image_set.baseline_image_path,
            image_set.changed_image_path,
            image_set.comparison_image_path,
            *image_set.overlay_image_paths,
        ]
        review_image_paths.extend(paths)
        evidence_lines.append(f"- Review images: {review_images_dir}")
        evidence_lines.append(
            f"- Images use signal {signal['record_id']}: "
            f"frame {before} at {signal['comparison_start_seconds']}s and "
            f"frame {after} at {signal['comparison_end_seconds']}s."
        )
        if window["coverage_sufficient"] is not True:
            evidence_lines.append("- These images cover only part of the period: cannot_compare.")
    evidence_lines.append(
        "\nVisual change does not establish water direction or flood safety. "
        "Dark periods remain unjudged. Image-quality settings are prototype settings."
    )
    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(evidence_lines) + "\n")

    return LocalPocSmokeResult(
        output_dir=str(output_dir),
        config_path=str(config_path),
        video_path=str(video_path),
        records_path=str(records_path),
        summary_path=str(summary_path),
        operator_notes_path=str(operator_notes_path),
        review_image_paths=tuple(review_image_paths),
        records_written=records_written,
        reference_region_used=bool(pipeline_summary.get("reference_region_used")),
    )


def _window_image_prefix(
    image_prefix: str,
    bounds: object,
    index: int,
    window_count: int,
) -> str:
    if not isinstance(bounds, list) or len(bounds) != 2:
        return image_prefix if window_count == 1 else f"{image_prefix}-window-{index}"
    start, end = bounds
    if not isinstance(start, int | float) or not isinstance(end, int | float):
        return image_prefix if window_count == 1 else f"{image_prefix}-window-{index}"
    start_text = _time_for_filename(float(start))
    end_text = _time_for_filename(float(end))
    return f"{image_prefix}-window-{start_text}-{end_text}s"


def _time_for_filename(second: float) -> str:
    text = f"{second:g}"
    return text.replace(".", "p").replace("-", "m")


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

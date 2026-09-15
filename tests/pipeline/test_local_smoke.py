from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from openfloodai.contracts import read_jsonl_records
from openfloodai.pipeline import run_local_poc_smoke, run_local_video_review


def create_tiny_video(path: Path, *, frame_count: int = 2) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 2.0, (8, 8))
    assert writer.isOpened(), "test video writer should open"

    try:
        for index in range(frame_count):
            frame = np.full((8, 8, 3), index * 120, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


def write_site_config(
    path: Path, *, normal_waterline_guides: list[dict[str, object]] | None = None
) -> None:
    config: dict[str, object] = {
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
        "privacy_notes": "Broad public location only.",
    }
    if normal_waterline_guides is not None:
        config["normal_waterline_guides"] = normal_waterline_guides
    path.write_text(json.dumps(config), encoding="utf-8")


def test_local_poc_smoke_creates_end_to_end_review_outputs(tmp_path: Path) -> None:
    result = run_local_poc_smoke(tmp_path / "smoke")

    records_path = Path(result.records_path)
    summary_path = Path(result.summary_path)
    operator_notes_path = Path(result.operator_notes_path)
    review_image_paths = [Path(path) for path in result.review_image_paths]

    records = read_jsonl_records(records_path)
    record_types = [record["record_type"] for record in records]
    visual_records = [
        record for record in records if record["record_type"] == "visual_signal_output"
    ]

    assert result.reference_region_used is True
    assert result.records_written == len(records)
    assert "camera_health_output" in record_types
    assert "video_frame_metadata" in record_types
    assert "visual_signal_output" in record_types
    assert "risk_state_output" in record_types
    assert len(visual_records) == 1
    assert visual_records[0]["reference_region_used"] is True
    assert "region_change_score" in visual_records[0]
    assert records_path.exists()
    assert summary_path.exists()
    assert operator_notes_path.exists()
    assert len(review_image_paths) == 6
    assert all(path.exists() for path in review_image_paths)
    assert any(path.name.endswith("-overlay.png") for path in review_image_paths)
    assert "visual_signal_output" in summary_path.read_text(encoding="utf-8")
    assert "not an official public warning" in operator_notes_path.read_text(encoding="utf-8")


def test_local_video_review_creates_outputs_from_local_video_and_config(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    config_path = tmp_path / "site-config.json"
    create_tiny_video(video_path, frame_count=3)
    write_site_config(config_path)

    result = run_local_video_review(
        video_path=video_path,
        config_path=config_path,
        output_dir=tmp_path / "video-review",
    )

    records = read_jsonl_records(Path(result.records_path))
    visual_record = next(
        record for record in records if record["record_type"] == "visual_signal_output"
    )

    assert result.reference_region_used is True
    assert visual_record["reference_region_used"] is True
    assert Path(result.summary_path).exists()
    assert Path(result.operator_notes_path).exists()
    assert len(result.review_image_paths) == 6
    assert all(Path(path).exists() for path in result.review_image_paths)


def _sample_guide(**overrides: object) -> dict[str, object]:
    guide: dict[str, object] = {
        "id": "left_bank_normal_waterline",
        "label": "left bank normal waterline",
        "points": [{"x": 0, "y": 60}, {"x": 50, "y": 80}],
        "status": "confirmed",
        "video_id": "sample",
        "video_time_seconds": 1,
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "normal_condition": True,
        "notes": "",
        "confirmed_at": "2026-01-01T00:00:00Z",
        "invalidated_at": None,
        "invalidation_reason": None,
    }
    guide.update(overrides)
    return guide


def test_local_video_review_burns_normal_waterline_guide_into_overlay_images(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "sample.avi"
    create_tiny_video(video_path, frame_count=3)

    plain_config_path = tmp_path / "plain-site-config.json"
    write_site_config(plain_config_path)
    plain_result = run_local_video_review(
        video_path=video_path,
        config_path=plain_config_path,
        output_dir=tmp_path / "plain-review",
    )

    confirmed_config_path = tmp_path / "confirmed-site-config.json"
    write_site_config(
        confirmed_config_path,
        normal_waterline_guides=[_sample_guide()],
    )
    confirmed_result = run_local_video_review(
        video_path=video_path,
        config_path=confirmed_config_path,
        output_dir=tmp_path / "confirmed-review",
    )

    plain_overlay = next(
        path for path in plain_result.review_image_paths if path.endswith("-baseline-overlay.png")
    )
    confirmed_overlay = next(
        path
        for path in confirmed_result.review_image_paths
        if path.endswith("-baseline-overlay.png")
    )

    plain_image = cv2.imread(plain_overlay)
    confirmed_image = cv2.imread(confirmed_overlay)
    assert plain_image is not None
    assert confirmed_image is not None
    assert not np.array_equal(plain_image, confirmed_image)


def test_local_video_review_flags_unusable_evidence_in_overlay_caption(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    create_tiny_video(video_path, frame_count=3)

    confirmed_config_path = tmp_path / "confirmed-site-config.json"
    write_site_config(
        confirmed_config_path,
        normal_waterline_guides=[_sample_guide()],
    )

    baseline_result = run_local_video_review(
        video_path=video_path,
        config_path=confirmed_config_path,
        output_dir=tmp_path / "baseline-review",
    )
    records = read_jsonl_records(Path(baseline_result.records_path))
    window = next(r for r in records if r["record_type"] == "evidence_window_output")
    bounds = window["time_window_seconds"]

    labels = [
        {
            "video_id": "sample",
            "time_window_seconds": bounds,
            "human_label": "cannot_judge",
            "riverbank_visible": "no",
        }
    ]
    flagged_result = run_local_video_review(
        video_path=video_path,
        config_path=confirmed_config_path,
        output_dir=tmp_path / "flagged-review",
        labels=labels,
    )

    baseline_overlay = next(
        path
        for path in baseline_result.review_image_paths
        if path.endswith("-baseline-overlay.png")
    )
    flagged_overlay = next(
        path for path in flagged_result.review_image_paths if path.endswith("-baseline-overlay.png")
    )

    baseline_image = cv2.imread(baseline_overlay)
    flagged_image = cv2.imread(flagged_overlay)
    assert baseline_image is not None
    assert flagged_image is not None
    assert flagged_image.shape[0] > baseline_image.shape[0]

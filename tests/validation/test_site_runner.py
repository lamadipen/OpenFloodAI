from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from openfloodai.validation import render_site_validation_report, run_site_validation


def create_tiny_video(path: Path, *, frame_values: tuple[int, ...]) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 2.0, (8, 8))
    assert writer.isOpened(), "test video writer should open"

    try:
        for value in frame_values:
            frame = np.full((8, 8, 3), value, dtype=np.uint8)
            # Match the 30-second labels with 30 seconds of actual footage.
            for _ in range(60 // len(frame_values)):
                writer.write(frame)
    finally:
        writer.release()


def write_site_config(path: Path) -> None:
    config = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo River Bridge",
        "public_location": "Demo River near Example Town",
        "input_type": "local_video",
        "reference_region": {
            "x": 0,
            "y": 0,
            "width": 100,
            "height": 100,
        },
        "privacy_notes": "Synthetic test config only.",
    }
    path.write_text(json.dumps(config), encoding="utf-8")


def write_labels(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "video_id": "rising-001",
                        "time_window_seconds": [0, 30],
                        "human_label": "water_rising",
                    }
                ),
                json.dumps(
                    {
                        "video_id": "rising-001",
                        "time_window_seconds": [30, 60],
                        "human_label": "cannot_judge",
                    }
                ),
                json.dumps(
                    {
                        "video_id": "normal-001",
                        "time_window_seconds": [0, 30],
                        "human_label": "water_rising",
                    }
                ),
                json.dumps(
                    {
                        "video_id": "unclear-001",
                        "time_window_seconds": [0, 30],
                        "human_label": "cannot_judge",
                    }
                ),
                json.dumps(
                    {
                        "video_id": "missing-001",
                        "time_window_seconds": [0, 30],
                        "human_label": "water_rising",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def make_site_dir(tmp_path: Path) -> Path:
    site_dir = tmp_path / "example-site"
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    write_site_config(site_dir / "configs" / "site-config.json")
    write_labels(site_dir / "labels" / "labels.jsonl")
    return site_dir


def test_run_site_validation_reports_multiple_video_results(tmp_path: Path) -> None:
    site_dir = make_site_dir(tmp_path)
    create_tiny_video(
        site_dir / "inputs" / "videos" / "rising-001.avi",
        frame_values=(20, 255, 255),
    )
    create_tiny_video(
        site_dir / "inputs" / "videos" / "normal-001.avi",
        frame_values=(10, 10, 10),
    )
    create_tiny_video(
        site_dir / "inputs" / "videos" / "unclear-001.avi",
        frame_values=(20, 255, 255),
    )
    (site_dir / "inputs" / "videos" / "bad-001.mp4").write_text(
        "not a video",
        encoding="utf-8",
    )

    report = run_site_validation(site_dir)
    rendered = render_site_validation_report(report)
    results_by_video_id = {result.video_id: result for result in report.results}

    assert report.processed_count == 3
    assert report.failed_count == 2
    assert report.label_window_count == 5
    assert report.agree_count == 0
    assert report.disagree_count == 0
    assert report.cannot_compare_count == 6
    assert report.scorecard.videos_reviewed == 5
    assert report.scorecard.label_windows == 5
    assert report.scorecard.agree_count == 0
    assert report.scorecard.disagree_count == 0
    assert report.scorecard.cannot_compare_count == 6
    assert report.scorecard.top_reasons
    assert report.scorecard.top_reasons[0] == ("UNCLEAR_CASE", 3)
    assert results_by_video_id["rising-001"].result == "cannot_compare"
    assert results_by_video_id["rising-001"].human_label == "multiple"
    assert len(results_by_video_id["rising-001"].comparisons) == 2
    assert {comparison.result for comparison in results_by_video_id["rising-001"].comparisons} == {
        "cannot_compare",
    }
    assert results_by_video_id["normal-001"].result == "cannot_compare"
    assert results_by_video_id["unclear-001"].result == "cannot_compare"
    assert results_by_video_id["bad-001"].system_result == "processing_failed"
    assert results_by_video_id["missing-001"].system_result == "missing_video"
    assert (site_dir / "outputs" / "validation-report.md").exists()
    assert (site_dir / "outputs" / "rising-001" / "records.jsonl").exists()
    assert (site_dir / "outputs" / "rising-001" / "label-comparison.md").exists()
    table_header = "| Video | Processed | Human label | System result | Result | Windows | Note |"
    rising_row = "| rising-001.avi | yes | multiple | cannot_judge | cannot_compare | 2 |"
    assert table_header in rendered
    assert rising_row in rendered
    assert "- Label windows compared: 5" in rendered
    assert "## Validation Scorecard" in rendered
    assert "- Cannot compare: 6" in rendered
    assert "not proof of flood detection accuracy" in rendered
    assert "- Top issues:" in rendered
    assert "The case is unclear: 3 case(s)" in rendered
    assert "LABEL_AND_SYSTEM_DIFFER" not in rendered
    assert "Time window: 0s to 30s" in rendered
    assert "Time window: 30s to 60s" in rendered
    assert "Cases marked `cannot_compare` are not counted as success." in rendered


def test_run_site_validation_handles_missing_human_label(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    write_site_config(site_dir / "configs" / "site-config.json")
    create_tiny_video(
        site_dir / "inputs" / "videos" / "unlabeled-001.avi",
        frame_values=(20, 255),
    )

    report = run_site_validation(site_dir)

    assert report.results[0].video_id == "unlabeled-001"
    assert report.results[0].human_label == "missing"
    assert report.results[0].result == "cannot_compare"
    assert report.label_window_count == 0


def test_run_site_validation_without_videos_still_reports_label_only_cases(
    tmp_path: Path,
) -> None:
    site_dir = tmp_path / "example-site"
    (site_dir / "labels").mkdir(parents=True)
    write_labels(site_dir / "labels" / "labels.jsonl")

    report = run_site_validation(site_dir)

    assert report.processed_count == 0
    assert report.failed_count == 4
    assert report.label_window_count == 5
    assert report.scorecard.videos_reviewed == 4
    assert report.scorecard.summary.startswith("Reviewed 4 video(s)")
    assert {result.system_result for result in report.results} == {"missing_video"}
    rising_result = next(result for result in report.results if result.video_id == "rising-001")
    assert len(rising_result.comparisons) == 2


def test_combined_report_output_is_stable_and_simple(tmp_path: Path) -> None:
    site_dir = make_site_dir(tmp_path)
    create_tiny_video(
        site_dir / "inputs" / "videos" / "rising-001.avi",
        frame_values=(20, 255),
    )

    report = run_site_validation(site_dir)
    rendered = render_site_validation_report(report)

    assert "# Site Validation Report" in rendered
    assert "Validation Site: example-site" in rendered
    assert "## Summary Table" in rendered
    rising_row = "| rising-001.avi | yes | multiple | cannot_judge | cannot_compare | 2 |"
    assert rising_row in rendered
    assert "## Detailed Results" in rendered
    assert "### rising-001" in rendered
    assert "- Video: rising-001.avi" in rendered
    assert "- Human label: multiple" in rendered
    assert "- Result: cannot_compare" in rendered
    assert "- Label windows compared: 2" in rendered
    assert "Window 1:" in rendered
    assert "Window 2:" in rendered
    assert "Time window: 0s to 30s" in rendered
    assert "Time window: 30s to 60s" in rendered
    assert "does not prove flood detection accuracy" in rendered


def test_empty_validation_scorecard_stays_clear_and_safe(tmp_path: Path) -> None:
    site_dir = tmp_path / "empty-site"
    site_dir.mkdir()

    report = run_site_validation(site_dir)
    rendered = render_site_validation_report(report)

    assert report.scorecard.videos_reviewed == 0
    assert report.scorecard.label_windows == 0
    assert report.scorecard.top_reasons == []
    assert report.scorecard.summary == "No labelled windows were available for comparison yet."
    assert "Cannot compare: 0" in rendered
    assert "not proof of flood detection accuracy" in rendered

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
    assert Path(report.output_path) == Path(report.run_dir) / "validation-report.md"
    assert Path(report.output_path).exists()
    assert (Path(report.run_dir) / "records" / "rising-001.jsonl").exists()
    assert (Path(report.run_dir) / "videos" / "rising-001" / "label-comparison.md").exists()
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
    assert report.scorecard.baseline_ready_count == 0
    assert report.scorecard.practice_only_count == 0
    assert "Cannot compare: 0" in rendered
    assert "not proof of flood detection accuracy" in rendered


def test_scorecard_reports_baseline_ready_and_practice_only_counts(tmp_path: Path) -> None:
    site_dir = tmp_path / "quality-site"
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    config = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo River Bridge",
        "public_location": "Demo River near Example Town",
        "input_type": "local_video",
        "reference_region": {"x": 0, "y": 0, "width": 100, "height": 100},
        "privacy_notes": "Synthetic test config only.",
        "normal_waterline_guides": [
            {
                "id": "left_bank_normal_waterline",
                "label": "left bank normal waterline",
                "points": [{"x": 10, "y": 10}, {"x": 30, "y": 30}],
                "status": "confirmed",
                "video_id": "rising-001",
                "video_time_seconds": 5,
                "site_id": "site-demo-01",
                "camera_id": "camera-demo-01",
                "normal_condition": True,
                "notes": "",
                "confirmed_at": None,
                "invalidated_at": None,
                "invalidation_reason": None,
            }
        ],
    }
    (site_dir / "configs" / "site-config.json").write_text(json.dumps(config), encoding="utf-8")
    (site_dir / "labels" / "labels.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "video_id": "rising-001",
                        "time_window_seconds": [0, 30],
                        "human_label": "water_rising",
                        "riverbank_visible": "yes",
                        "water_boundary_visible": "yes",
                    }
                ),
                json.dumps(
                    {
                        "video_id": "rising-001",
                        "time_window_seconds": [30, 60],
                        "human_label": "cannot_judge",
                        "riverbank_visible": "no",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_site_validation(site_dir)

    assert report.scorecard.baseline_ready_count == 1
    assert report.scorecard.practice_only_count == 1
    assert report.scorecard.quality_reasons == [("riverbank_not_visible", 1)]


def test_scorecard_treats_unconfirmed_baseline_as_practice_only(tmp_path: Path) -> None:
    site_dir = tmp_path / "unconfirmed-site"
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    write_site_config(site_dir / "configs" / "site-config.json")
    (site_dir / "labels" / "labels.jsonl").write_text(
        json.dumps(
            {
                "video_id": "rising-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_rising",
                "riverbank_visible": "yes",
                "water_boundary_visible": "yes",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_site_validation(site_dir)

    assert report.scorecard.baseline_ready_count == 0
    assert report.scorecard.practice_only_count == 1
    assert report.scorecard.quality_reasons == [("baseline_not_confirmed", 1)]


def test_render_site_validation_report_includes_baseline_ready_section(tmp_path: Path) -> None:
    site_dir = make_site_dir(tmp_path)
    create_tiny_video(
        site_dir / "inputs" / "videos" / "rising-001.avi",
        frame_values=(20, 255),
    )

    report = run_site_validation(site_dir)
    rendered = render_site_validation_report(report)

    assert "- Baseline-ready samples:" in rendered
    assert "- Practice-only samples:" in rendered
    assert "- Reference-quality issues:" in rendered


def test_rendered_report_shows_normal_waterline_guides_section_once(tmp_path: Path) -> None:
    site_dir = tmp_path / "quality-site"
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    config = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo River Bridge",
        "public_location": "Demo River near Example Town",
        "input_type": "local_video",
        "reference_region": {"x": 0, "y": 0, "width": 100, "height": 100},
        "privacy_notes": "Synthetic test config only.",
        "normal_waterline_guides": [
            {
                "id": "left_bank_normal_waterline",
                "label": "left bank normal waterline",
                "points": [{"x": 10, "y": 10}, {"x": 30, "y": 30}],
                "status": "confirmed",
                "video_id": "rising-001",
                "video_time_seconds": 5,
                "site_id": "site-demo-01",
                "camera_id": "camera-demo-01",
                "normal_condition": True,
                "notes": "",
                "confirmed_at": None,
                "invalidated_at": None,
                "invalidation_reason": None,
            }
        ],
    }
    (site_dir / "configs" / "site-config.json").write_text(json.dumps(config), encoding="utf-8")
    (site_dir / "labels" / "labels.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "video_id": "rising-001",
                        "time_window_seconds": [0, 30],
                        "human_label": "water_rising",
                        "riverbank_visible": "yes",
                        "water_boundary_visible": "yes",
                    }
                ),
                json.dumps(
                    {
                        "video_id": "rising-001",
                        "time_window_seconds": [30, 60],
                        "human_label": "cannot_judge",
                        "riverbank_visible": "no",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_site_validation(site_dir)
    rendered = render_site_validation_report(report)

    assert rendered.count("## Normal Waterline Guides") == 1
    assert rendered.count("1 of 1 normal waterline guide") == 1
    assert "Riverbank/reference visibility" in rendered
    assert "The riverbank/reference area was visible to the reviewer" in rendered
    assert "The riverbank/reference area was not visible to the reviewer" in rendered
    assert "Reference evidence usable" in rendered
    assert "not usable for comparison: The riverbank or stable reference is not visible" in rendered


def test_rendered_report_without_normal_waterline_guides_still_renders(tmp_path: Path) -> None:
    site_dir = tmp_path / "unconfirmed-site"
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    write_site_config(site_dir / "configs" / "site-config.json")
    (site_dir / "labels" / "labels.jsonl").write_text(
        json.dumps(
            {
                "video_id": "rising-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_rising",
                "riverbank_visible": "yes",
                "water_boundary_visible": "yes",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_site_validation(site_dir)
    rendered = render_site_validation_report(report)

    assert "## Normal Waterline Guides" in rendered
    assert "No normal waterline guide yet." in rendered
    assert "not usable for comparison: The site does not yet have a confirmed" in rendered


def test_missing_human_label_and_quality_failure_both_shown(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    write_site_config(site_dir / "configs" / "site-config.json")
    create_tiny_video(
        site_dir / "inputs" / "videos" / "unlabeled-001.avi",
        frame_values=(20, 255),
    )
    (site_dir / "labels" / "labels.jsonl").write_text(
        json.dumps(
            {
                "video_id": "other-001",
                "time_window_seconds": [0, 30],
                "human_label": "cannot_judge",
                "riverbank_visible": "no",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_site_validation(site_dir)
    rendered = render_site_validation_report(report)

    assert "No human label for comparison." in rendered
    assert "not usable for comparison: The riverbank or stable reference is not visible" in rendered


def test_each_validation_run_gets_its_own_snapshot(tmp_path: Path) -> None:
    site_dir = make_site_dir(tmp_path)
    create_tiny_video(
        site_dir / "inputs" / "videos" / "rising-001.avi",
        frame_values=(20, 255),
    )

    first = run_site_validation(site_dir)
    first_records = Path(first.run_dir, "records", "rising-001.jsonl").read_bytes()
    second = run_site_validation(site_dir)
    assert Path(first.run_dir, "records", "rising-001.jsonl").read_bytes() == first_records
    assert {p.name for p in (site_dir / "outputs").iterdir()} == {"runs"}
    for report in (first, second):
        assert Path(report.output_path).is_relative_to(Path(report.run_dir))
        for result in report.results:
            if result.output_dir:
                assert Path(result.output_dir).is_relative_to(Path(report.run_dir))

    runs_dir = site_dir / "outputs" / "runs"
    run_dirs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    assert len(run_dirs) == 2
    assert first.run_id != second.run_id
    for run_dir in run_dirs:
        assert (run_dir / "validation-report.md").exists()
        assert (run_dir / "scorecard.json").exists()
        assert (run_dir / "run-metadata.json").exists()
        assert (run_dir / "records" / "rising-001.jsonl").exists()


def test_failed_video_is_reflected_in_run_metadata(tmp_path: Path) -> None:
    site_dir = make_site_dir(tmp_path)
    (site_dir / "inputs" / "videos" / "broken.mp4").write_text(
        "not a video",
        encoding="utf-8",
    )

    report = run_site_validation(site_dir)
    metadata = json.loads(Path(report.run_dir, "run-metadata.json").read_text())

    assert report.failed_count == len(report.results)
    assert metadata["status"] == "failed"


def test_runs_preserve_input_receipts_across_site_edits(tmp_path: Path) -> None:
    from openfloodai.validation.input_snapshot import read_input_snapshot

    site = make_site_dir(tmp_path)
    labels = site / "labels/labels.jsonl"
    labels.write_text("")
    video = site / "inputs/videos/rising-001.avi"
    create_tiny_video(video, frame_values=(80, 80))
    manifest = site / "manifest.jsonl"
    manifest.write_text('{"video_id":"rising-001","notes":"first"}\n')
    first = run_site_validation(site)
    first_dir = Path(first.run_dir)
    original_files = {
        str(p.relative_to(first_dir)): p.read_bytes() for p in first_dir.rglob("*") if p.is_file()
    }
    first_inputs = read_input_snapshot(first_dir)
    assert first_inputs["labels"] == []
    assert first_inputs["receipt"]["mode"] == "machine_only"
    assert "No human label" in first.results[0].note
    assert len(first_inputs["videos"]) == 1
    assert len(first_inputs["videos"][0]["sha256"]) == 64

    config_path = site / "configs/site-config.json"
    config = json.loads(config_path.read_text())
    config["reference_region"]["height"] = 50
    config_path.write_text(json.dumps(config))
    manifest.write_text('{"video_id":"rising-001","notes":"second"}\n')
    label = {
        "video_id": "rising-001",
        "time_window_seconds": [0, 30],
        "human_label": "water_rising",
    }
    labels.write_text(json.dumps(label) + "\n")
    second = run_site_validation(site)
    assert read_input_snapshot(Path(second.run_dir))["labels"] == [label]
    label2 = dict(label, human_label="water_falling")
    labels.write_text(json.dumps(label) + "\n" + json.dumps(label2) + "\n")
    create_tiny_video(site / "inputs/videos/new-video.avi", frame_values=(80, 80))
    third = run_site_validation(site)
    third_inputs = read_input_snapshot(Path(third.run_dir))
    assert third_inputs["labels"] == [label, label2]
    assert len(third_inputs["videos"]) == 2
    assert third_inputs["watched_area"]["height"] == 50
    assert "second" in third_inputs["manifest_text"]
    duplicate_result = next(result for result in third.results if result.video_id == "rising-001")
    assert all(
        c.result == "cannot_compare" and "Duplicate human labels" in c.note
        for c in duplicate_result.comparisons
    )
    assert third_inputs["receipt"]["status"] == "completed_with_warnings"
    assert read_input_snapshot(first_dir) == first_inputs
    assert {
        str(p.relative_to(first_dir)): p.read_bytes() for p in first_dir.rglob("*") if p.is_file()
    } == original_files
    # A future export reads the saved receipt even if the live manifest and labels disappear.
    manifest.unlink()
    labels.unlink()
    assert read_input_snapshot(first_dir) == first_inputs

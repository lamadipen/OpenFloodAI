from __future__ import annotations

from pathlib import Path

from openfloodai.review import (
    compare_label_files,
    compare_label_records,
    render_label_comparison_report,
)


def test_compare_label_records_reports_agree_for_change_label_and_change_signal() -> None:
    report = compare_label_records(
        video_id="demo-river-001",
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_rising",
            }
        ],
        system_records=[
            {
                "record_type": "visual_signal_output",
                "region_change_score": 0.42,
            }
        ],
    )

    assert report.agree_count == 1
    assert report.comparisons[0].result == "agree"
    assert report.comparisons[0].system_result == "water_change_seen"


def test_compare_label_records_reports_disagree_for_change_label_and_low_signal() -> None:
    report = compare_label_records(
        video_id="demo-river-001",
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_rising",
            }
        ],
        system_records=[
            {
                "record_type": "visual_signal_output",
                "region_change_score": 0.01,
            }
        ],
    )

    assert report.disagree_count == 1
    assert report.comparisons[0].result == "disagree"
    assert report.comparisons[0].system_result == "no_clear_change"


def test_compare_label_records_reports_missing_human_label() -> None:
    report = compare_label_records(
        video_id="missing-video",
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_rising",
            }
        ],
        system_records=[
            {
                "record_type": "visual_signal_output",
                "region_change_score": 0.42,
            }
        ],
    )

    assert report.cannot_compare_count == 1
    assert report.comparisons[0].human_label == "missing"
    assert report.comparisons[0].note == "No human label was found for this video."


def test_compare_label_records_reports_missing_system_output() -> None:
    report = compare_label_records(
        video_id="demo-river-001",
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_rising",
            }
        ],
        system_records=[
            {
                "record_type": "video_frame_metadata",
            }
        ],
    )

    assert report.cannot_compare_count == 1
    assert report.comparisons[0].system_result == "missing_system_output"


def test_compare_label_records_reports_cannot_compare_for_unclear_case() -> None:
    report = compare_label_records(
        video_id="demo-river-001",
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [0, 30],
                "human_label": "cannot_judge",
            }
        ],
        system_records=[
            {
                "record_type": "risk_state_output",
                "risk_state": "UNKNOWN",
            }
        ],
    )

    assert report.cannot_compare_count == 1
    assert report.comparisons[0].result == "cannot_compare"
    assert report.comparisons[0].system_result == "cannot_judge"


def test_compare_label_files_reads_jsonl_and_renders_report(tmp_path: Path) -> None:
    system_path = tmp_path / "records.jsonl"
    label_path = tmp_path / "labels.jsonl"
    system_path.write_text(
        '{"record_type":"visual_signal_output","region_change_score":0.42}\n',
        encoding="utf-8",
    )
    label_path.write_text(
        (
            '{"video_id":"demo-river-001","time_window_seconds":[0,30],'
            '"human_label":"water_rising"}\n'
        ),
        encoding="utf-8",
    )

    report = compare_label_files(
        system_records_path=system_path,
        human_labels_path=label_path,
        video_id="demo-river-001",
    )

    rendered_report = render_label_comparison_report(report)

    assert report.agree_count == 1
    assert "Human label: water_rising" in rendered_report
    assert "Result: agree" in rendered_report

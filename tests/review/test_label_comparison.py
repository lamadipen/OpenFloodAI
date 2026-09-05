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
                "video_time_seconds": 10,
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
                "video_time_seconds": 10,
                "region_change_score": 0.01,
            }
        ],
    )

    assert report.disagree_count == 1
    assert report.comparisons[0].result == "disagree"
    assert report.comparisons[0].system_result == "no_clear_change"


def test_compare_label_records_filters_system_records_by_video_id() -> None:
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
                "video_id": "demo-river-001",
                "record_type": "visual_signal_output",
                "video_time_seconds": 10,
                "region_change_score": 0.01,
            },
            {
                "video_id": "demo-river-999",
                "record_type": "visual_signal_output",
                "video_time_seconds": 10,
                "region_change_score": 0.95,
            },
        ],
    )

    assert report.disagree_count == 1
    assert report.comparisons[0].system_result == "no_clear_change"


def test_compare_label_records_does_not_use_other_video_system_records() -> None:
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
                "video_id": "demo-river-999",
                "record_type": "visual_signal_output",
                "video_time_seconds": 10,
                "region_change_score": 0.95,
            },
        ],
    )

    assert report.cannot_compare_count == 1
    assert report.comparisons[0].system_result == "missing_system_output"


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
                "video_time_seconds": 10,
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
                "video_time_seconds": 10,
                "risk_state": "UNKNOWN",
            }
        ],
    )

    assert report.cannot_compare_count == 1
    assert report.comparisons[0].result == "cannot_compare"
    assert report.comparisons[0].system_result == "cannot_judge"


def test_compare_label_records_uses_only_matching_time_window_records() -> None:
    report = compare_label_records(
        video_id="demo-river-001",
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [30, 60],
                "human_label": "water_rising",
            }
        ],
        system_records=[
            {
                "record_type": "visual_signal_output",
                "video_time_seconds": 10,
                "region_change_score": 0.95,
            },
            {
                "record_type": "visual_signal_output",
                "video_time_seconds": 40,
                "region_change_score": 0.01,
            },
        ],
    )

    assert report.disagree_count == 1
    assert report.comparisons[0].system_result == "no_clear_change"
    assert report.comparisons[0].time_window_seconds == (30.0, 60.0)


def test_compare_label_records_reports_cannot_compare_when_window_has_no_records() -> None:
    report = compare_label_records(
        video_id="demo-river-001",
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [30, 60],
                "human_label": "water_rising",
            }
        ],
        system_records=[
            {
                "record_type": "visual_signal_output",
                "video_time_seconds": 10,
                "region_change_score": 0.95,
            }
        ],
    )

    assert report.cannot_compare_count == 1
    assert report.comparisons[0].system_result == "missing_system_output"
    assert "30s to 60s" in report.comparisons[0].note


def test_compare_label_records_handles_multiple_windows_for_one_video() -> None:
    report = compare_label_records(
        video_id="demo-river-001",
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_rising",
            },
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [30, 60],
                "human_label": "water_rising",
            },
        ],
        system_records=[
            {
                "record_type": "visual_signal_output",
                "video_time_seconds": 10,
                "region_change_score": 0.42,
            },
            {
                "record_type": "visual_signal_output",
                "video_time_seconds": 40,
                "region_change_score": 0.01,
            },
        ],
    )

    assert report.agree_count == 1
    assert report.disagree_count == 1
    assert [comparison.time_window_seconds for comparison in report.comparisons] == [
        (0.0, 30.0),
        (30.0, 60.0),
    ]


def test_compare_label_records_uses_half_open_time_windows() -> None:
    report = compare_label_records(
        video_id="demo-river-001",
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_rising",
            },
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [30, 60],
                "human_label": "water_rising",
            },
        ],
        system_records=[
            {
                "record_type": "visual_signal_output",
                "video_time_seconds": 30,
                "region_change_score": 0.42,
            },
        ],
    )

    assert report.comparisons[0].system_result == "missing_system_output"
    assert report.comparisons[0].result == "cannot_compare"
    assert report.comparisons[1].system_result == "water_change_seen"
    assert report.comparisons[1].result == "agree"


def test_compare_label_records_uses_visual_records_linked_to_frame_metadata() -> None:
    report = compare_label_records(
        video_id="demo-river-001",
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [30, 60],
                "human_label": "water_rising",
            }
        ],
        system_records=[
            {
                "record_id": "frame-meta-001",
                "record_type": "video_frame_metadata",
                "timestamp": "2026-09-03T00:00:10+00:00",
            },
            {
                "record_id": "frame-meta-002",
                "record_type": "video_frame_metadata",
                "timestamp": "2026-09-03T00:00:40+00:00",
            },
            {
                "record_type": "visual_signal_output",
                "source_record_ids": ["frame-meta-002"],
                "region_change_score": 0.42,
            },
        ],
    )

    assert report.agree_count == 1
    assert report.comparisons[0].system_result == "water_change_seen"


def test_compare_label_files_reads_jsonl_and_renders_report(tmp_path: Path) -> None:
    system_path = tmp_path / "records.jsonl"
    label_path = tmp_path / "labels.jsonl"
    system_path.write_text(
        (
            '{"record_type":"visual_signal_output","video_time_seconds":10,'
            '"region_change_score":0.42}\n'
        ),
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
    assert "Time window: 0s to 30s" in rendered_report
    assert "Result: agree" in rendered_report


def test_pair_crossing_label_boundary_cannot_enter_through_source_id() -> None:
    records: list[dict[str, object]] = [
        {"record_id": "inside", "record_type": "video_frame_metadata", "video_time_seconds": 12},
        {
            "record_id": "pair",
            "record_type": "visual_signal_output",
            "video_time_seconds": 12,
            "comparison_start_seconds": 8,
            "comparison_end_seconds": 12,
            "source_record_ids": ["inside"],
            "region_change_score": 0.9,
        },
        {
            "record_id": "risk",
            "record_type": "risk_state_output",
            "video_time_seconds": 12,
            "comparison_start_seconds": 8,
            "comparison_end_seconds": 12,
            "source_record_ids": ["pair"],
            "risk_state": "NORMAL",
        },
    ]
    report = compare_label_records(
        system_records=records,
        human_labels=[
            {"video_id": "test", "time_window_seconds": [10, 20], "human_label": "water_rising"}
        ],
        video_id="test",
    )
    assert report.cannot_compare_count == 1
    assert report.comparisons[0].system_result == "missing_system_output"


def test_pair_at_exclusive_end_is_not_counted() -> None:
    report = compare_label_records(
        system_records=[
            {
                "record_type": "visual_signal_output",
                "video_time_seconds": 20,
                "comparison_start_seconds": 15,
                "comparison_end_seconds": 20,
                "region_change_score": 0.9,
            }
        ],
        human_labels=[
            {"video_id": "test", "time_window_seconds": [10, 20], "human_label": "water_rising"}
        ],
        video_id="test",
    )
    assert report.cannot_compare_count == 1

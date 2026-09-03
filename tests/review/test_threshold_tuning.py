from __future__ import annotations

from pathlib import Path

import pytest

from openfloodai.review import (
    ThresholdTuningError,
    render_threshold_tuning_report,
    tune_threshold_files,
    tune_threshold_records,
)


def test_tune_threshold_records_shows_how_thresholds_change_agreement() -> None:
    report = tune_threshold_records(
        video_id="demo-river-001",
        candidate_thresholds=[0.05, 0.2],
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
                "region_change_score": 0.1,
            }
        ],
    )

    assert [result.threshold for result in report.results] == [0.05, 0.2]
    assert report.results[0].agree_count == 1
    assert report.results[1].disagree_count == 1


def test_tune_threshold_records_keeps_cannot_compare_separate() -> None:
    report = tune_threshold_records(
        video_id="demo-river-001",
        candidate_thresholds=[0.05],
        human_labels=[
            {
                "video_id": "demo-river-001",
                "time_window_seconds": [0, 30],
                "human_label": "cannot_judge",
            }
        ],
        system_records=[
            {
                "video_id": "demo-river-001",
                "record_type": "risk_state_output",
                "video_time_seconds": 10,
                "risk_state": "UNKNOWN",
            }
        ],
    )

    assert report.results[0].agree_count == 0
    assert report.results[0].disagree_count == 0
    assert report.results[0].cannot_compare_count == 1
    assert report.results[0].compared_count == 0


def test_tune_threshold_records_rejects_invalid_thresholds() -> None:
    with pytest.raises(ThresholdTuningError, match="between 0.0 and 1.0"):
        tune_threshold_records(
            video_id="demo-river-001",
            candidate_thresholds=[-0.1],
            human_labels=[],
            system_records=[],
        )


def test_render_threshold_tuning_report_is_stable() -> None:
    report = tune_threshold_records(
        video_id="demo-river-001",
        candidate_thresholds=[0.05],
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
                "region_change_score": 0.1,
            }
        ],
    )

    rendered = render_threshold_tuning_report(report)

    assert "| 0.050 | 1 | 0 | 0 | 1 |" in rendered
    assert "does not prove flood detection accuracy" in rendered


def test_tune_threshold_files_reads_local_jsonl_inputs(tmp_path: Path) -> None:
    system_path = tmp_path / "records.jsonl"
    labels_path = tmp_path / "labels.jsonl"
    system_path.write_text(
        '{"video_id":"demo-river-001","record_type":"visual_signal_output",'
        '"video_time_seconds":10,"region_change_score":0.1}\n',
        encoding="utf-8",
    )
    labels_path.write_text(
        (
            '{"video_id":"demo-river-001","time_window_seconds":[0,30],'
            '"human_label":"water_rising"}\n'
        ),
        encoding="utf-8",
    )

    report = tune_threshold_files(
        system_records_path=system_path,
        human_labels_path=labels_path,
        video_id="demo-river-001",
        candidate_thresholds=[0.05],
    )

    assert report.results[0].agree_count == 1

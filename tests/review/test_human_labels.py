from __future__ import annotations

from pathlib import Path

import pytest

from openfloodai.review import (
    HumanLabelError,
    is_valid_human_label_record,
    load_human_label_records,
    validate_human_label_record,
)


def test_valid_human_label_record_passes() -> None:
    record = {
        "video_id": "demo-river-001",
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "time_window_seconds": [0, 30],
        "human_label": "water_rising",
        "confidence": "medium",
        "note": "Water appears higher against the bridge pillar.",
    }

    assert validate_human_label_record(record) == []
    assert is_valid_human_label_record(record) is True


def test_invalid_human_label_fails_clearly() -> None:
    errors = validate_human_label_record(
        {
            "video_id": "demo-river-001",
            "time_window_seconds": [0, 30],
            "human_label": "danger",
        }
    )

    assert errors == [
        (
            "human_label must be one of: camera_video_problem, cannot_judge, "
            "no_clear_change, water_falling, water_rising"
        )
    ]


def test_invalid_time_window_fails_clearly() -> None:
    errors = validate_human_label_record(
        {
            "video_id": "demo-river-001",
            "time_window_seconds": [30, 10],
            "human_label": "water_falling",
        }
    )

    assert errors == ["time_window_seconds end must be greater than start"]


def test_missing_required_fields_fail() -> None:
    errors = validate_human_label_record({})

    assert "Missing required field(s): human_label, time_window_seconds, video_id" in errors


def test_load_human_label_records_reads_valid_jsonl(tmp_path: Path) -> None:
    label_path = tmp_path / "labels.jsonl"
    label_path.write_text(
        (
            '{"video_id":"demo-river-001","time_window_seconds":[0,30],'
            '"human_label":"no_clear_change","confidence":"high"}\n'
        ),
        encoding="utf-8",
    )

    records = load_human_label_records(label_path)

    assert len(records) == 1
    assert records[0]["human_label"] == "no_clear_change"


def test_load_human_label_records_reports_record_number(tmp_path: Path) -> None:
    label_path = tmp_path / "labels.jsonl"
    label_path.write_text(
        '{"video_id":"demo-river-001","time_window_seconds":[0,30],"human_label":"bad"}\n',
        encoding="utf-8",
    )

    with pytest.raises(HumanLabelError, match="Record 1: human_label must be one of"):
        load_human_label_records(label_path)

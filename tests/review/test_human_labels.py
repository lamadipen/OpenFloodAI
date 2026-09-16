from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.review import (
    HumanLabelError,
    compare_label_records,
    create_human_label_record,
    is_valid_human_label_record,
    load_human_label_records,
    load_manifest_records,
    validate_human_label_record,
)


@pytest.mark.parametrize(
    ("legacy", "current", "score", "expected"),
    [
        ("water_rising", "water_level_rising", 0.42, "agree"),
        ("water_falling", "water_level_falling", 0.42, "agree"),
        ("no_clear_change", "no_water_level_change", 0.0, "agree"),
        ("cannot_judge", "cannot_judge_water_level", 0.0, "cannot_compare"),
    ],
)
def test_legacy_labels_remain_readable_and_new_records_use_current_names(
    tmp_path: Path, legacy: str, current: str, score: float, expected: str
) -> None:
    old_path = tmp_path / "old-labels.jsonl"
    old_text = (
        json.dumps({"video_id": "test", "time_window_seconds": [0, 30], "human_label": legacy})
        + "\n"
    )
    old_path.write_text(old_text, encoding="utf-8")
    report = compare_label_records(
        video_id="test",
        human_labels=load_human_label_records(old_path),
        system_records=[
            {
                "record_type": "visual_signal_output",
                "video_time_seconds": 10,
                "region_change_score": score,
            }
        ],
    )
    assert report.comparisons[0].human_label == current
    assert report.comparisons[0].result == expected
    assert old_path.read_text(encoding="utf-8") == old_text

    result = create_human_label_record(
        site_dir=tmp_path,
        video_id="test",
        start_second=0,
        end_second=30,
        human_label=legacy,
    )
    assert result.created
    assert load_human_label_records(result.labels_path)[0]["human_label"] == current


def test_valid_human_label_record_passes() -> None:
    record = {
        "video_id": "demo-river-001",
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "time_window_seconds": [0, 30],
        "human_label": "water_level_rising",
        "confidence": "medium",
        "note": "Water appears higher against the bridge pillar.",
    }

    assert validate_human_label_record(record) == []
    assert is_valid_human_label_record(record) is True


def test_valid_human_label_record_with_quality_fields_passes() -> None:
    record = {
        "video_id": "demo-river-001",
        "time_window_seconds": [0, 30],
        "human_label": "water_level_rising",
        "riverbank_visible": "yes",
        "stable_marker_visible": "unsure",
        "water_boundary_visible": "yes",
        "camera_stable": "no",
        "visibility_condition": "glare",
    }

    assert validate_human_label_record(record) == []
    assert is_valid_human_label_record(record) is True


def test_human_label_record_rejects_invalid_tristate_value() -> None:
    errors = validate_human_label_record(
        {
            "video_id": "demo-river-001",
            "time_window_seconds": [0, 30],
            "human_label": "water_level_rising",
            "riverbank_visible": "maybe",
        }
    )

    assert "riverbank_visible must be one of: no, unsure, yes" in errors


def test_human_label_record_rejects_invalid_visibility_condition() -> None:
    errors = validate_human_label_record(
        {
            "video_id": "demo-river-001",
            "time_window_seconds": [0, 30],
            "human_label": "water_level_rising",
            "visibility_condition": "sunny",
        }
    )

    assert any(error.startswith("visibility_condition must be one of:") for error in errors)


def test_custom_human_label_record_passes() -> None:
    record = {
        "video_id": "demo-river-001",
        "time_window_seconds": [0, 30],
        "human_label": "bridge_pillar_covered",
    }

    assert validate_human_label_record(record) == []
    assert is_valid_human_label_record(record) is True


def test_invalid_human_label_text_fails_clearly() -> None:
    errors = validate_human_label_record(
        {
            "video_id": "demo-river-001",
            "time_window_seconds": [0, 30],
            "human_label": "bridge pillar covered",
        }
    )

    assert errors == ["human_label may use only letters, numbers, dash, and underscore"]


def test_invalid_time_window_fails_clearly() -> None:
    errors = validate_human_label_record(
        {
            "video_id": "demo-river-001",
            "time_window_seconds": [30, 10],
            "human_label": "water_level_falling",
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
            '"human_label":"no_water_level_change","confidence":"high"}\n'
        ),
        encoding="utf-8",
    )

    records = load_human_label_records(label_path)

    assert len(records) == 1
    assert records[0]["human_label"] == "no_water_level_change"


def test_load_human_label_records_reports_record_number(tmp_path: Path) -> None:
    label_path = tmp_path / "labels.jsonl"
    label_path.write_text(
        ('{"video_id":"demo-river-001","time_window_seconds":[0,30],"human_label":"bad label"}\n'),
        encoding="utf-8",
    )

    with pytest.raises(HumanLabelError, match="Record 1: human_label may use only"):
        load_human_label_records(label_path)


def test_create_valid_human_label_record_creates_file_and_record(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    result = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=30,
        end_second=60,
        human_label="water_level_rising",
        confidence="medium",
        note="water appears higher near the bridge pillar",
    )

    assert result.created is True
    assert "Added label record" in result.message
    assert result.labels_path == site_dir / "labels" / "labels.jsonl"
    assert result.labels_path.exists()

    records = load_human_label_records(result.labels_path)
    assert len(records) == 1
    assert records[0]["video_id"] == "rising-001"
    assert records[0]["time_window_seconds"] == [30, 60]
    assert records[0]["human_label"] == "water_level_rising"
    assert records[0]["confidence"] == "medium"
    assert records[0]["note"] == "water appears higher near the bridge pillar"


def test_create_human_label_record_rejects_invalid_time_windows(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    # end <= start
    res1 = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=60,
        end_second=30,
        human_label="water_level_rising",
    )
    assert res1.created is False
    assert "end must be greater than start" in res1.message

    # end == start
    res2 = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=30,
        end_second=30,
        human_label="water_level_rising",
    )
    assert res2.created is False
    assert "end must be greater than start" in res2.message

    # negative start
    res3 = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=-5,
        end_second=30,
        human_label="water_level_rising",
    )
    assert res3.created is False
    assert "0 or greater" in res3.message


def test_create_human_label_record_accepts_custom_label_values(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    result = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=0,
        end_second=30,
        human_label="bridge_pillar_covered",
    )

    assert result.created is True
    records = load_human_label_records(site_dir / "labels" / "labels.jsonl")
    assert records[0]["human_label"] == "bridge_pillar_covered"


def test_create_human_label_record_rejects_unsafe_custom_label_text(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    result = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=0,
        end_second=30,
        human_label="flood danger",
    )

    assert result.created is False
    assert "human_label may use only letters, numbers, dash, and underscore" in result.message


def test_create_human_label_record_rejects_unknown_confidence_values(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    result = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=0,
        end_second=30,
        human_label="water_level_rising",
        confidence="extremely_high",
    )

    assert result.created is False
    assert "confidence must be one of:" in result.message


def test_create_human_label_record_accepts_quality_fields(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    result = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=0,
        end_second=30,
        human_label="water_level_rising",
        riverbank_visible="yes",
        water_boundary_visible="unsure",
        visibility_condition="glare",
    )

    assert result.created is True
    records = load_human_label_records(site_dir / "labels" / "labels.jsonl")
    assert records[0]["riverbank_visible"] == "yes"
    assert records[0]["water_boundary_visible"] == "unsure"
    assert records[0]["visibility_condition"] == "glare"
    assert "stable_marker_visible" not in records[0]
    assert "camera_stable" not in records[0]


def test_create_human_label_record_rejects_unknown_tristate_value(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    result = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=0,
        end_second=30,
        human_label="water_level_rising",
        camera_stable="maybe",
    )

    assert result.created is False
    assert "camera_stable must be one of:" in result.message


def test_create_human_label_record_rejects_unsafe_video_ids(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    result = create_human_label_record(
        site_dir=site_dir,
        video_id="../bad_path",
        start_second=0,
        end_second=30,
        human_label="water_level_rising",
    )

    assert result.created is False
    assert "Invalid video_id" in result.message


def test_create_human_label_record_appends_to_existing_file_safely(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    res1 = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=0,
        end_second=30,
        human_label="no_water_level_change",
    )
    assert res1.created is True

    res2 = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=30,
        end_second=60,
        human_label="water_level_rising",
    )
    assert res2.created is True

    records = load_human_label_records(site_dir / "labels" / "labels.jsonl")
    assert len(records) == 2
    assert records[0]["time_window_seconds"] == [0, 30]
    assert records[0]["human_label"] == "no_water_level_change"
    assert records[1]["time_window_seconds"] == [30, 60]
    assert records[1]["human_label"] == "water_level_rising"


def test_create_human_label_record_handles_missing_trailing_newline(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    labels_dir = site_dir / "labels"
    labels_dir.mkdir(parents=True)
    (labels_dir / "labels.jsonl").write_bytes(
        b'{"human_label":"cannot_judge_water_level","time_window_seconds":[0,10],"video_id":"v1"}'
    )

    result = create_human_label_record(
        site_dir=site_dir,
        video_id="v1",
        start_second=10,
        end_second=20,
        human_label="water_level_rising",
    )

    assert result.created is True
    records = load_human_label_records(labels_dir / "labels.jsonl")
    assert len(records) == 2
    assert records[0]["time_window_seconds"] == [0, 10]
    assert records[1]["time_window_seconds"] == [10, 20]


def test_create_human_label_record_avoids_accidental_overwrite(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    res1 = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=30,
        end_second=60,
        human_label="water_level_rising",
        note="Initial label",
    )
    assert res1.created is True

    # Attempt to add same video_id and same window without overwrite=True
    res2 = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=30,
        end_second=60,
        human_label="cannot_judge_water_level",
        note="Accidental duplicate attempt",
        overwrite=False,
    )
    assert res2.created is False
    assert "already exists" in res2.message
    assert "overwrite=True" in res2.message

    records = load_human_label_records(site_dir / "labels" / "labels.jsonl")
    assert len(records) == 1
    assert records[0]["human_label"] == "water_level_rising"
    assert records[0]["note"] == "Initial label"


def test_create_human_label_record_overwrites_when_requested(tmp_path: Path) -> None:
    site_dir = tmp_path / "test-site"
    site_dir.mkdir()

    create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=0,
        end_second=30,
        human_label="no_water_level_change",
    )
    create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=30,
        end_second=60,
        human_label="water_level_rising",
        confidence="low",
    )

    # Overwrite the [30, 60] record
    res = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=30,
        end_second=60,
        human_label="water_level_rising",
        confidence="high",
        note="Confirmed higher on second review",
        overwrite=True,
    )
    assert res.created is True
    assert "Replaced label record" in res.message

    records = load_human_label_records(site_dir / "labels" / "labels.jsonl")
    assert len(records) == 2
    assert records[0]["human_label"] == "no_water_level_change"
    assert records[1]["confidence"] == "high"
    assert records[1]["note"] == "Confirmed higher on second review"


def test_create_human_label_record_no_private_footage_required(tmp_path: Path) -> None:
    site_dir = tmp_path / "empty-site"
    site_dir.mkdir()

    result = create_human_label_record(
        site_dir=site_dir,
        video_id="remote-review-001",
        start_second=10,
        end_second=40,
        human_label="water_level_falling",
    )

    assert result.created is True
    assert not (site_dir / "inputs" / "videos").exists()


def test_create_human_label_record_updates_manifest_if_present(tmp_path: Path) -> None:
    site_dir = tmp_path / "site-with-manifest"
    site_dir.mkdir()
    manifest_file = site_dir / "manifest.jsonl"
    manifest_file.write_text(
        (
            '{"approved_for_repo":false,"filename":"rising-001.mp4","has_human_label":false,'
            '"notes":"Test video","purpose":"possible_rising_water","split":"practice",'
            '"video_id":"rising-001"}\n'
        ),
        encoding="utf-8",
    )

    result = create_human_label_record(
        site_dir=site_dir,
        video_id="rising-001",
        start_second=0,
        end_second=30,
        human_label="water_level_rising",
    )

    assert result.created is True
    manifest_records = load_manifest_records(manifest_file)
    assert len(manifest_records) == 1
    assert manifest_records[0]["has_human_label"] is True

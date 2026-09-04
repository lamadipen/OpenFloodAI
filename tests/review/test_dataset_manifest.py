from __future__ import annotations

from pathlib import Path

import pytest

from openfloodai.review import (
    DatasetManifestError,
    is_valid_manifest_record,
    load_manifest_records,
    validate_manifest_record,
)


def valid_manifest_record() -> dict[str, object]:
    return {
        "video_id": "demo-river-001",
        "filename": "demo-river-001.mp4",
        "purpose": "practice_normal_water",
        "split": "practice",
        "approved_for_repo": False,
        "has_human_label": True,
        "hard_case_type": "none",
        "notes": "Safe demo record. No real video is committed.",
    }


def test_valid_manifest_record_passes() -> None:
    record = valid_manifest_record()

    assert validate_manifest_record(record) == []
    assert is_valid_manifest_record(record) is True


def test_missing_required_fields_fail() -> None:
    errors = validate_manifest_record({})

    assert "Missing required field(s):" in errors[0]
    assert "video_id" in errors[0]
    assert "approved_for_repo" in errors[0]


def test_invalid_split_fails_clearly() -> None:
    record = valid_manifest_record()
    record["split"] = "training"

    assert validate_manifest_record(record) == ["split must be one of: locked_validation, practice"]


def test_approved_for_repo_must_be_boolean() -> None:
    record = valid_manifest_record()
    record["approved_for_repo"] = "false"

    assert "approved_for_repo must be true or false" in validate_manifest_record(record)


def test_has_human_label_must_be_boolean() -> None:
    record = valid_manifest_record()
    record["has_human_label"] = "yes"

    assert "has_human_label must be true or false" in validate_manifest_record(record)


def test_hard_case_type_is_optional() -> None:
    record = valid_manifest_record()
    del record["hard_case_type"]

    assert validate_manifest_record(record) == []


def test_hard_case_type_must_be_text_when_present() -> None:
    record = valid_manifest_record()
    record["hard_case_type"] = ""

    assert "hard_case_type must be a non-empty string" in validate_manifest_record(record)


def test_load_manifest_records_reads_valid_jsonl(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.jsonl"
    manifest_path.write_text(
        (
            '{"video_id":"demo-river-001","filename":"demo-river-001.mp4",'
            '"purpose":"practice_normal_water","split":"practice",'
            '"approved_for_repo":false,"has_human_label":true,'
            '"notes":"Safe demo record."}\n'
        ),
        encoding="utf-8",
    )

    records = load_manifest_records(manifest_path)

    assert len(records) == 1
    assert records[0]["video_id"] == "demo-river-001"


def test_load_manifest_records_reports_record_number(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.jsonl"
    manifest_path.write_text(
        (
            '{"video_id":"demo-river-001","filename":"demo-river-001.mp4",'
            '"purpose":"practice_normal_water","split":"bad",'
            '"approved_for_repo":false,"has_human_label":true,'
            '"notes":"Safe demo record."}\n'
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatasetManifestError, match="Record 1: split must be one of"):
        load_manifest_records(manifest_path)


def test_example_site_manifest_loads_successfully() -> None:
    records = load_manifest_records(Path("data/sites/example-site/manifest.jsonl"))

    assert records[0]["video_id"] == "demo-river-001"
    assert records[0]["approved_for_repo"] is False

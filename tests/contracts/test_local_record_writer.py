from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from openfloodai.contracts import (
    InvalidRecordError,
    InvalidRecordPathError,
    read_jsonl_records,
    write_jsonl_record,
    write_jsonl_records,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_PATH = ROOT / "examples" / "events"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as file:
        return cast(dict[str, object], json.load(file))


def test_writes_one_record_and_reads_it_back(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    record: dict[str, object] = {
        "contract_version": "v1",
        "record_id": "health-001",
        "record_type": "camera_health_output",
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "timestamp": "2026-08-30T12:00:00+00:00",
        "input_quality_state": "USABLE",
    }

    write_jsonl_record(path, record)

    assert read_jsonl_records(path) == [record]


def test_writes_multiple_records_and_reads_them_back_in_order(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    first: dict[str, object] = {"record_id": "signal-001", "record_type": "vision_signal_output"}
    second: dict[str, object] = {"record_id": "risk-001", "record_type": "risk_engine_output"}

    write_jsonl_records(path, [first, second])

    assert read_jsonl_records(path) == [first, second]


def test_appends_records_without_overwriting_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    first: dict[str, object] = {"record_id": "first", "record_type": "camera_health_output"}
    second: dict[str, object] = {"record_id": "second", "record_type": "camera_health_output"}

    write_jsonl_record(path, first)
    write_jsonl_record(path, second)

    assert read_jsonl_records(path) == [first, second]


def test_creates_parent_folders_intentionally(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "records" / "events.jsonl"
    record: dict[str, object] = {"record_id": "health-001", "record_type": "camera_health_output"}

    write_jsonl_record(path, record)

    assert path.is_file()
    assert read_jsonl_records(path) == [record]


def test_rejects_non_jsonl_output_path(tmp_path: Path) -> None:
    path = tmp_path / "records.json"
    record: dict[str, object] = {"record_id": "health-001", "record_type": "camera_health_output"}

    with pytest.raises(InvalidRecordPathError, match="must end with .jsonl"):
        write_jsonl_record(path, record)


def test_rejects_directory_output_path(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.mkdir()
    record: dict[str, object] = {"record_id": "health-001", "record_type": "camera_health_output"}

    with pytest.raises(InvalidRecordPathError, match="is a directory"):
        write_jsonl_record(path, record)


def test_rejects_non_json_values(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    record: dict[str, object] = {
        "record_id": "health-001",
        "record_type": "camera_health_output",
        "bad_value": object(),
    }

    with pytest.raises(InvalidRecordError, match="non-JSON value"):
        write_jsonl_record(path, record)


def test_rejects_non_string_keys(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    record: dict[Any, object] = {
        1: "bad-key",
        "record_id": "health-001",
        "record_type": "camera_health_output",
    }

    with pytest.raises(InvalidRecordError, match="keys must be strings"):
        write_jsonl_record(path, record)


def test_validates_event_audit_records_before_writing(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    valid_record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")

    write_jsonl_record(path, valid_record)

    assert read_jsonl_records(path) == [valid_record]


def test_rejects_invalid_event_audit_record_before_writing(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    invalid_record = load_json(EXAMPLES_PATH / "invalid-missing-reason-codes.json")

    with pytest.raises(InvalidRecordError, match="Event/audit record failed validation"):
        write_jsonl_record(path, invalid_record)

    assert not path.exists()


def test_read_rejects_invalid_json_line(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text('{"record_id": "ok"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(InvalidRecordError, match="Line 2 is not valid JSON"):
        read_jsonl_records(path)


def test_read_rejects_non_object_json_line(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text('["not", "an", "object"]\n', encoding="utf-8")

    with pytest.raises(InvalidRecordError, match="Line 1 must contain a JSON object"):
        read_jsonl_records(path)

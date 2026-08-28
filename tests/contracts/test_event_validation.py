from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from openfloodai.contracts import is_valid_event_record, validate_event_record
from openfloodai.contracts.event_validation import event_schema_path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_PATH = ROOT / "examples" / "events"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as file:
        return cast(dict[str, object], json.load(file))


def test_event_schema_path_uses_repository_schema() -> None:
    assert event_schema_path() == ROOT / "schemas" / "event.schema.json"


def test_valid_high_example_passes_shared_validator() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")

    assert validate_event_record(record) == []
    assert is_valid_event_record(record)


def test_valid_unknown_degraded_example_passes_shared_validator() -> None:
    record = load_json(EXAMPLES_PATH / "valid-unknown-degraded-camera-offline.json")

    assert validate_event_record(record) == []
    assert is_valid_event_record(record)


def test_invalid_missing_reason_codes_returns_clear_error() -> None:
    record = load_json(EXAMPLES_PATH / "invalid-missing-reason-codes.json")

    errors = validate_event_record(record)

    assert not is_valid_event_record(record)
    assert "reason_codes: 'reason_codes' is a required property" in errors


def test_invalid_normal_with_camera_offline_returns_error() -> None:
    record = load_json(EXAMPLES_PATH / "invalid-normal-with-camera-offline.json")

    errors = validate_event_record(record)

    assert not is_valid_event_record(record)
    assert any("should not be valid" in error for error in errors)


def test_invalid_bad_reason_code_format_returns_error() -> None:
    record = load_json(EXAMPLES_PATH / "invalid-bad-reason-code-format.json")

    errors = validate_event_record(record)

    assert not is_valid_event_record(record)
    assert "reason_codes.0: 'camera offline' does not match" in errors[0]


def test_invalid_sensitive_field_returns_error() -> None:
    record = load_json(EXAMPLES_PATH / "invalid-sensitive-public-field.json")

    errors = validate_event_record(record)

    assert not is_valid_event_record(record)
    assert any("should not be valid" in error for error in errors)


def test_bad_risk_state_returns_clear_error() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    record["risk_state"] = "VERY_BAD"

    errors = validate_event_record(record)

    assert not is_valid_event_record(record)
    assert any("risk_state: 'VERY_BAD' is not one of" in error for error in errors)


def test_bad_timestamp_returns_clear_error() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    record["timestamp"] = "not-a-date"

    errors = validate_event_record(record)

    assert not is_valid_event_record(record)
    assert "timestamp: 'not-a-date' is not a 'date-time'" in errors


def test_missing_evidence_window_returns_clear_error() -> None:
    record: dict[str, Any] = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    del record["evidence_window"]

    errors = validate_event_record(record)

    assert not is_valid_event_record(record)
    assert "evidence_window: 'evidence_window' is a required property" in errors

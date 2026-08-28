from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "event.schema.json"
EXAMPLES_PATH = ROOT / "examples" / "events"

REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
ALLOWED_INPUT_QUALITY_STATES = {"USABLE", "DEGRADED", "UNKNOWN"}
ALLOWED_RISK_STATES = {"NORMAL", "ELEVATED", "HIGH", "CRITICAL", "UNKNOWN_DEGRADED"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return cast(dict[str, Any], json.load(file))


def build_validator() -> Draft202012Validator:
    schema = load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def collect_schema_errors(record: dict[str, Any]) -> list[ValidationError]:
    return sorted(build_validator().iter_errors(record), key=lambda error: error.json_path)


def assert_schema_valid(record: dict[str, Any]) -> None:
    errors = collect_schema_errors(record)
    assert errors == []


def test_schema_file_contains_required_validation_rules() -> None:
    schema = load_json(SCHEMA_PATH)

    assert schema["properties"]["contract_version"]["const"] == "v1"
    assert schema["properties"]["record_type"]["const"] == "event_audit_record"
    assert set(schema["properties"]["input_quality_state"]["enum"]) == ALLOWED_INPUT_QUALITY_STATES
    assert set(schema["properties"]["risk_state"]["enum"]) == ALLOWED_RISK_STATES
    assert schema["properties"]["reason_codes"]["minItems"] == 1
    assert schema["properties"]["reason_codes"]["items"]["pattern"] == REASON_CODE_PATTERN.pattern
    assert schema["properties"]["evidence_window"]["required"] == [
        "start",
        "end",
        "duration_seconds",
    ]
    assert schema["allOf"], "schema should include safety and privacy validation rules"


@pytest.mark.parametrize(
    "example_file",
    [
        "valid-high-event-audit-record.json",
        "valid-unknown-degraded-camera-offline.json",
    ],
)
def test_valid_event_examples_pass_validation(example_file: str) -> None:
    record = load_json(EXAMPLES_PATH / example_file)

    assert_schema_valid(record)


@pytest.mark.parametrize(
    ("example_file", "expected_validator"),
    [
        ("invalid-missing-reason-codes.json", "required"),
        (
            "invalid-normal-with-camera-offline.json",
            "not",
        ),
        ("invalid-bad-reason-code-format.json", "pattern"),
        (
            "invalid-sensitive-public-field.json",
            "not",
        ),
    ],
)
def test_invalid_event_examples_fail_schema_validation(
    example_file: str, expected_validator: str
) -> None:
    record = load_json(EXAMPLES_PATH / example_file)

    errors = collect_schema_errors(record)
    assert errors, f"{example_file} should fail schema validation"
    assert expected_validator in {error.validator for error in errors}


def test_bad_timestamp_fails_validation() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    record["timestamp"] = "not-a-date"

    errors = collect_schema_errors(record)
    assert "format" in {error.validator for error in errors}


def test_timestamp_without_timezone_fails_validation() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    record["timestamp"] = "2026-08-27T14:05:00"

    errors = collect_schema_errors(record)
    assert "format" in {error.validator for error in errors}


def test_missing_evidence_window_fails_validation() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    del record["evidence_window"]

    errors = collect_schema_errors(record)
    assert "required" in {error.validator for error in errors}


def test_negative_evidence_window_duration_fails_validation() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    record["evidence_window"]["duration_seconds"] = -1

    errors = collect_schema_errors(record)
    assert "minimum" in {error.validator for error in errors}


def test_bad_risk_state_fails_schema_validation() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    record["risk_state"] = "VERY_BAD"

    errors = collect_schema_errors(record)
    assert "enum" in {error.validator for error in errors}


def test_bad_input_quality_state_fails_schema_validation() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    record["input_quality_state"] = "PERFECT"

    errors = collect_schema_errors(record)
    assert "enum" in {error.validator for error in errors}

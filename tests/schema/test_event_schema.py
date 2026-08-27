from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "event.schema.json"
EXAMPLES_PATH = ROOT / "examples" / "events"

REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
ALLOWED_INPUT_QUALITY_STATES = {"USABLE", "DEGRADED", "UNKNOWN"}
ALLOWED_RISK_STATES = {"NORMAL", "ELEVATED", "HIGH", "CRITICAL", "UNKNOWN_DEGRADED"}
NORMAL_BLOCKING_REASON_CODES = {"CAMERA_OFFLINE", "STALE_FRAMES"}
SENSITIVE_FIELD_NAMES = {
    "camera_password",
    "camera_stream_url",
    "private_contact_details",
    "exact_private_gps",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return cast(dict[str, Any], json.load(file))


def assert_datetime_with_timezone(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")


def find_sensitive_fields(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if key in SENSITIVE_FIELD_NAMES:
                found.add(key)
            found.update(find_sensitive_fields(nested_value))
    elif isinstance(value, list):
        for item in value:
            found.update(find_sensitive_fields(item))
    return found


def validate_event_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_fields = [
        "contract_version",
        "record_id",
        "record_type",
        "site_id",
        "camera_id",
        "timestamp",
        "event_type",
        "software_version",
        "config_version",
        "input_quality_state",
        "risk_state",
        "reason_codes",
        "evidence_window",
    ]

    for field in required_fields:
        if field not in record:
            errors.append(f"missing required field: {field}")

    for field in [
        "record_id",
        "site_id",
        "camera_id",
        "event_type",
        "software_version",
        "config_version",
    ]:
        if field in record and not record[field]:
            errors.append(f"{field} must be non-empty")

    if record.get("contract_version") != "v1":
        errors.append("contract_version must be v1")

    if record.get("record_type") != "event_audit_record":
        errors.append("record_type must be event_audit_record")

    if record.get("input_quality_state") not in ALLOWED_INPUT_QUALITY_STATES:
        errors.append("input_quality_state must be an allowed V1 value")

    if record.get("risk_state") not in ALLOWED_RISK_STATES:
        errors.append("risk_state must be an allowed V1 value")

    try:
        assert_datetime_with_timezone(record.get("timestamp"), "timestamp")
    except (AssertionError, ValueError) as error:
        errors.append(str(error))

    reason_codes = record.get("reason_codes")
    if not isinstance(reason_codes, list) or not reason_codes:
        errors.append("reason_codes must contain at least one reason code")
    else:
        for reason_code in reason_codes:
            if not isinstance(reason_code, str) or not REASON_CODE_PATTERN.fullmatch(reason_code):
                errors.append(f"reason code has bad format: {reason_code}")

        if record.get("risk_state") == "NORMAL" and NORMAL_BLOCKING_REASON_CODES.intersection(
            reason_codes
        ):
            errors.append("camera/feed failure evidence must not be treated as NORMAL")

    evidence_window = record.get("evidence_window")
    if not isinstance(evidence_window, dict):
        errors.append("evidence_window must be present")
    else:
        for field in ["start", "end", "duration_seconds"]:
            if field not in evidence_window:
                errors.append(f"evidence_window missing field: {field}")

        for field in ["start", "end"]:
            if field in evidence_window:
                try:
                    assert_datetime_with_timezone(
                        evidence_window[field], f"evidence_window.{field}"
                    )
                except (AssertionError, ValueError) as error:
                    errors.append(str(error))

        duration_seconds = evidence_window.get("duration_seconds")
        if not isinstance(duration_seconds, int | float) or duration_seconds < 0:
            errors.append("evidence_window.duration_seconds must be zero or greater")

    sensitive_fields = find_sensitive_fields(record)
    if sensitive_fields:
        field_list = ", ".join(sorted(sensitive_fields))
        errors.append(f"sensitive fields are not allowed in event records: {field_list}")

    return errors


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


@pytest.mark.parametrize(
    "example_file",
    [
        "valid-high-event-audit-record.json",
        "valid-unknown-degraded-camera-offline.json",
    ],
)
def test_valid_event_examples_pass_validation(example_file: str) -> None:
    record = load_json(EXAMPLES_PATH / example_file)

    assert validate_event_record(record) == []


@pytest.mark.parametrize(
    ("example_file", "expected_error"),
    [
        ("invalid-missing-reason-codes.json", "missing required field: reason_codes"),
        (
            "invalid-normal-with-camera-offline.json",
            "camera/feed failure evidence must not be treated as NORMAL",
        ),
        ("invalid-bad-reason-code-format.json", "reason code has bad format: camera offline"),
        (
            "invalid-sensitive-public-field.json",
            "sensitive fields are not allowed in event records: camera_password",
        ),
    ],
)
def test_invalid_event_examples_fail_validation(example_file: str, expected_error: str) -> None:
    record = load_json(EXAMPLES_PATH / example_file)

    assert expected_error in validate_event_record(record)


def test_bad_timestamp_fails_validation() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    record["timestamp"] = "not-a-date"

    assert "Invalid isoformat string: 'not-a-date'" in validate_event_record(record)


def test_timestamp_without_timezone_fails_validation() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    record["timestamp"] = "2026-08-27T14:05:00"

    assert "timestamp must include timezone information" in validate_event_record(record)


def test_missing_evidence_window_fails_validation() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    del record["evidence_window"]

    errors = validate_event_record(record)
    assert "missing required field: evidence_window" in errors
    assert "evidence_window must be present" in errors


def test_negative_evidence_window_duration_fails_validation() -> None:
    record = load_json(EXAMPLES_PATH / "valid-high-event-audit-record.json")
    record["evidence_window"]["duration_seconds"] = -1

    assert "evidence_window.duration_seconds must be zero or greater" in validate_event_record(
        record
    )

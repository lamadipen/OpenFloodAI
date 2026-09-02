"""Human label validation for local video review."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from openfloodai.contracts import read_jsonl_records
from openfloodai.contracts.local_store import JsonObject

ALLOWED_HUMAN_LABELS = {
    "water_rising",
    "water_falling",
    "no_clear_change",
    "camera_video_problem",
    "cannot_judge",
}
ALLOWED_CONFIDENCE_LEVELS = {"low", "medium", "high"}
REQUIRED_FIELDS = {
    "video_id",
    "time_window_seconds",
    "human_label",
}
OPTIONAL_FIELDS = {
    "site_id",
    "camera_id",
    "confidence",
    "note",
    "reviewer_id",
}
ALLOWED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS


class HumanLabelError(ValueError):
    """Raised when a human label file or record is invalid."""


def validate_human_label_record(record: Mapping[str, object]) -> list[str]:
    """Return validation errors for one human label record."""

    errors: list[str] = []
    fields = set(record.keys())

    missing_fields = sorted(REQUIRED_FIELDS - fields)
    if missing_fields:
        errors.append(f"Missing required field(s): {', '.join(missing_fields)}")

    extra_fields = sorted(fields - ALLOWED_FIELDS)
    if extra_fields:
        errors.append(f"Unsupported field(s): {', '.join(extra_fields)}")

    _validate_text_field(record, "video_id", errors, required=True)
    _validate_text_field(record, "site_id", errors, required=False)
    _validate_text_field(record, "camera_id", errors, required=False)
    _validate_text_field(record, "note", errors, required=False)
    _validate_text_field(record, "reviewer_id", errors, required=False)
    _validate_time_window(record.get("time_window_seconds"), errors)
    _validate_allowed_value(
        record.get("human_label"),
        "human_label",
        ALLOWED_HUMAN_LABELS,
        errors,
        required=True,
    )
    _validate_allowed_value(
        record.get("confidence"),
        "confidence",
        ALLOWED_CONFIDENCE_LEVELS,
        errors,
        required=False,
    )

    return errors


def is_valid_human_label_record(record: Mapping[str, object]) -> bool:
    """Return whether one human label record is valid."""

    return not validate_human_label_record(record)


def load_human_label_records(path: Path) -> list[JsonObject]:
    """Load and validate human label records from a JSON Lines file."""

    try:
        records = read_jsonl_records(path)
    except ValueError as error:
        raise HumanLabelError(f"Could not read human label file: {error}") from error

    all_errors: list[str] = []
    for index, record in enumerate(records, start=1):
        for validation_error in validate_human_label_record(record):
            all_errors.append(f"Record {index}: {validation_error}")

    if all_errors:
        raise HumanLabelError("; ".join(all_errors))

    return records


def _validate_text_field(
    record: Mapping[str, object],
    field_name: str,
    errors: list[str],
    *,
    required: bool,
) -> None:
    value = record.get(field_name)
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field_name} must be a non-empty string")
    elif required and field_name not in record:
        errors.append(f"{field_name} is required")


def _validate_time_window(value: object, errors: list[str]) -> None:
    if not isinstance(value, list) or len(value) != 2:
        errors.append("time_window_seconds must be a list with start and end seconds")
        return

    start, end = value
    if not _is_number(start) or not _is_number(end):
        errors.append("time_window_seconds values must be numbers")
        return

    start_value = float(start)
    end_value = float(end)
    if start_value < 0 or end_value < 0:
        errors.append("time_window_seconds values must be 0 or greater")
    if end_value <= start_value:
        errors.append("time_window_seconds end must be greater than start")


def _validate_allowed_value(
    value: object,
    field_name: str,
    allowed_values: set[str],
    errors: list[str],
    *,
    required: bool,
) -> None:
    if value is None:
        if required:
            errors.append(f"{field_name} is required")
        return
    if not isinstance(value, str) or value not in allowed_values:
        joined_values = ", ".join(sorted(allowed_values))
        errors.append(f"{field_name} must be one of: {joined_values}")


def _is_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float)

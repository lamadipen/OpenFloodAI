"""Validation dataset manifest helpers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from openfloodai.contracts import read_jsonl_records
from openfloodai.contracts.local_store import JsonObject

ALLOWED_MANIFEST_SPLITS = {"practice", "locked_validation"}
REQUIRED_MANIFEST_FIELDS = {
    "video_id",
    "filename",
    "purpose",
    "split",
    "approved_for_repo",
    "has_human_label",
    "notes",
}
OPTIONAL_MANIFEST_FIELDS = {
    "hard_case_type",
}
ALLOWED_MANIFEST_FIELDS = REQUIRED_MANIFEST_FIELDS | OPTIONAL_MANIFEST_FIELDS


class DatasetManifestError(ValueError):
    """Raised when a validation dataset manifest is invalid."""


def validate_manifest_record(record: Mapping[str, object]) -> list[str]:
    """Return validation errors for one validation dataset manifest record."""

    errors: list[str] = []
    fields = set(record.keys())

    missing_fields = sorted(REQUIRED_MANIFEST_FIELDS - fields)
    if missing_fields:
        errors.append(f"Missing required field(s): {', '.join(missing_fields)}")

    extra_fields = sorted(fields - ALLOWED_MANIFEST_FIELDS)
    if extra_fields:
        errors.append(f"Unsupported field(s): {', '.join(extra_fields)}")

    _validate_text_field(record, "video_id", errors)
    _validate_text_field(record, "filename", errors)
    _validate_text_field(record, "purpose", errors)
    _validate_text_field(record, "notes", errors)
    _validate_text_field(record, "hard_case_type", errors, required=False)
    _validate_split(record.get("split"), errors)
    _validate_bool_field(record, "approved_for_repo", errors)
    _validate_bool_field(record, "has_human_label", errors)

    return errors


def is_valid_manifest_record(record: Mapping[str, object]) -> bool:
    """Return whether one validation dataset manifest record is valid."""

    return not validate_manifest_record(record)


def load_manifest_records(path: Path) -> list[JsonObject]:
    """Load and validate validation dataset manifest records from JSON Lines."""

    try:
        records = read_jsonl_records(path)
    except ValueError as error:
        raise DatasetManifestError(f"Could not read dataset manifest file: {error}") from error

    all_errors: list[str] = []
    for index, record in enumerate(records, start=1):
        for validation_error in validate_manifest_record(record):
            all_errors.append(f"Record {index}: {validation_error}")

    if all_errors:
        raise DatasetManifestError("; ".join(all_errors))

    return records


def _validate_text_field(
    record: Mapping[str, object],
    field_name: str,
    errors: list[str],
    *,
    required: bool = True,
) -> None:
    value = record.get(field_name)
    if value is None:
        if required:
            errors.append(f"{field_name} is required")
        return
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field_name} must be a non-empty string")


def _validate_split(value: object, errors: list[str]) -> None:
    if value is None:
        errors.append("split is required")
        return
    if not isinstance(value, str) or value not in ALLOWED_MANIFEST_SPLITS:
        joined_values = ", ".join(sorted(ALLOWED_MANIFEST_SPLITS))
        errors.append(f"split must be one of: {joined_values}")


def _validate_bool_field(
    record: Mapping[str, object],
    field_name: str,
    errors: list[str],
) -> None:
    value = record.get(field_name)
    if value is None:
        errors.append(f"{field_name} is required")
        return
    if not isinstance(value, bool):
        errors.append(f"{field_name} must be true or false")

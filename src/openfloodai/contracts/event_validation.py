"""Validation helpers for OpenFloodAI V1 event/audit records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

EVENT_SCHEMA_RELATIVE_PATH = Path("schemas") / "event.schema.json"


def validate_event_record(record: Mapping[str, object]) -> list[str]:
    """Return readable validation errors for an event/audit record."""

    errors = sorted(
        _event_validator().iter_errors(record),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.validator),
    )
    return [_format_error(error) for error in errors]


def is_valid_event_record(record: Mapping[str, object]) -> bool:
    """Return True when an event/audit record passes V1 schema validation."""

    return validate_event_record(record) == []


def event_schema_path() -> Path:
    """Return the repository path to the V1 event/audit JSON Schema."""

    return _find_repo_root() / EVENT_SCHEMA_RELATIVE_PATH


@lru_cache(maxsize=1)
def _event_validator() -> Draft202012Validator:
    schema = _load_event_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _load_event_schema() -> dict[str, Any]:
    try:
        resource = files("openfloodai").joinpath("schemas", "event.schema.json")
        schema_text = resource.read_text(encoding="utf-8")
        return cast(dict[str, Any], json.loads(schema_text))
    except (FileNotFoundError, TypeError, ModuleNotFoundError):
        pass

    with event_schema_path().open(encoding="utf-8") as schema_file:
        return cast(dict[str, Any], json.load(schema_file))


def _find_repo_root() -> Path:
    for directory in Path(__file__).resolve().parents:
        if (directory / EVENT_SCHEMA_RELATIVE_PATH).is_file():
            return directory
    raise FileNotFoundError(f"Could not find {EVENT_SCHEMA_RELATIVE_PATH}")


def _format_error(error: ValidationError) -> str:
    path = _error_path(error)
    return f"{path}: {error.message}"


def _error_path(error: ValidationError) -> str:
    path_parts = [str(part) for part in error.absolute_path]
    if path_parts:
        return ".".join(path_parts)

    if error.validator == "required":
        missing_field = _missing_required_field(error)
        if missing_field is not None:
            return missing_field

    return "<record>"


def _missing_required_field(error: ValidationError) -> str | None:
    if not error.message.startswith("'"):
        return None
    return error.message.split("'", maxsplit=2)[1]

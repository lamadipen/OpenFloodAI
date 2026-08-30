"""Local JSON Lines record storage helpers for OpenFloodAI."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import cast

from openfloodai.contracts.event_validation import validate_event_record

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


class LocalRecordStoreError(ValueError):
    """Base error for local record storage failures."""


class InvalidRecordPathError(LocalRecordStoreError):
    """Raised when a JSONL record path is not usable."""


class InvalidRecordError(LocalRecordStoreError):
    """Raised when a record cannot be safely written or read."""


def write_jsonl_record(path: Path, record: Mapping[str, object]) -> None:
    """Append one JSON object record to a local JSON Lines file."""

    write_jsonl_records(path, [record])


def write_jsonl_records(path: Path, records: Iterable[Mapping[str, object]]) -> None:
    """Append multiple JSON object records to a local JSON Lines file."""

    json_records = [_prepare_record(record) for record in records]
    _prepare_output_path(path)

    with path.open("a", encoding="utf-8") as file:
        for record in json_records:
            file.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            file.write("\n")


def read_jsonl_records(path: Path) -> list[JsonObject]:
    """Read JSON object records from a local JSON Lines file."""

    _ensure_jsonl_path(path)
    if not path.exists():
        raise FileNotFoundError(f"JSONL record file does not exist: {path}")
    if path.is_dir():
        raise InvalidRecordPathError(f"JSONL record path is a directory: {path}")

    records: list[JsonObject] = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped_line = line.strip()
            if not stripped_line:
                continue

            try:
                parsed = cast(object, json.loads(stripped_line))
            except json.JSONDecodeError as error:
                raise InvalidRecordError(
                    f"Line {line_number} is not valid JSON: {error.msg}"
                ) from error

            if not isinstance(parsed, Mapping):
                raise InvalidRecordError(f"Line {line_number} must contain a JSON object")

            records.append(_to_json_object(parsed))

    return records


def _prepare_record(record: Mapping[str, object]) -> JsonObject:
    if not isinstance(record, Mapping):
        raise InvalidRecordError("Record must be a JSON object")

    if record.get("record_type") == "event_audit_record":
        errors = validate_event_record(record)
        if errors:
            readable_errors = "; ".join(errors)
            raise InvalidRecordError(f"Event/audit record failed validation: {readable_errors}")

    return _to_json_object(cast(Mapping[object, object], record))


def _prepare_output_path(path: Path) -> None:
    _ensure_jsonl_path(path)
    if path.exists() and path.is_dir():
        raise InvalidRecordPathError(f"JSONL record path is a directory: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)


def _ensure_jsonl_path(path: Path) -> None:
    if path.suffix != ".jsonl":
        raise InvalidRecordPathError(f"JSONL record path must end with .jsonl: {path}")


def _to_json_object(value: Mapping[object, object]) -> JsonObject:
    json_object: JsonObject = {}
    for key, child_value in value.items():
        if not isinstance(key, str):
            raise InvalidRecordError("Record keys must be strings")
        json_object[key] = _to_json_value(child_value)
    return json_object


def _to_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | bool | int):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidRecordError("Float values must be finite JSON numbers")
        return value

    if isinstance(value, Mapping):
        return _to_json_object(value)

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_to_json_value(item) for item in value]

    raise InvalidRecordError(f"Record contains a non-JSON value: {type(value).__name__}")

"""Shared data contract helpers for OpenFloodAI."""

from openfloodai.contracts.event_validation import is_valid_event_record, validate_event_record
from openfloodai.contracts.local_store import (
    InvalidRecordError,
    InvalidRecordPathError,
    LocalRecordStoreError,
    read_jsonl_records,
    write_jsonl_record,
    write_jsonl_records,
)

__all__ = [
    "InvalidRecordError",
    "InvalidRecordPathError",
    "LocalRecordStoreError",
    "is_valid_event_record",
    "read_jsonl_records",
    "validate_event_record",
    "write_jsonl_record",
    "write_jsonl_records",
]

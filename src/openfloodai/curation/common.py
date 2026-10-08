"""Shared constants, errors and small helpers for training-dataset curation (Issue #215).

A dataset is curated from reviewed observations of saved runs. Nothing here trains a model,
classifies flooding, or publishes anything: it selects, validates and freezes local evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
# The handoff contract that a later export/publishing story (#207) reads. Frozen dataset
# versions carry this name and version in their manifest so a consumer can check compatibility.
CONTRACT_NAME = "openfloodai.training_dataset"
CONTRACT_VERSION = "1"

TASK_WATER_SEGMENTATION = "water_segmentation"
TASK_LEVEL_CLASSIFICATION = "level_classification"
TASK_GAUGE_HEIGHT = "gauge_height"
TASK_LEVEL_CHANGE = "level_change"
TASKS = (
    TASK_WATER_SEGMENTATION,
    TASK_LEVEL_CLASSIFICATION,
    TASK_GAUGE_HEIGHT,
    TASK_LEVEL_CHANGE,
)
TASK_TITLES = {
    TASK_WATER_SEGMENTATION: "Water segmentation",
    TASK_LEVEL_CLASSIFICATION: "Low / middle / high classification",
    TASK_GAUGE_HEIGHT: "Gauge-height estimation",
    TASK_LEVEL_CHANGE: "Rising / falling (height change)",
}

SPLITS = ("train", "validation", "test")
LEVEL_CATEGORIES = ("low", "middle", "high")

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

_DATASET_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


class CurationError(ValueError):
    """An invalid request, or a dataset that cannot be changed that way."""


class CurationConflict(CurationError):
    """The same observation already has a different annotation; a decision is needed."""

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = details


def reason(code: str, message: str, severity: str = SEVERITY_ERROR) -> dict[str, str]:
    """One explained finding: what is wrong (or worth knowing) and how serious it is."""

    return {"code": code, "message": message, "severity": severity}


def errors_in(reasons: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in reasons if r["severity"] == SEVERITY_ERROR]


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def canonical_json(value: Any) -> bytes:
    """Stable bytes for hashing and for files that must be identical on a rebuild."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def content_id(value: Any, length: int = 16) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()[:length]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def validate_dataset_id(value: str) -> str:
    if not _DATASET_ID.fullmatch(value):
        raise CurationError("Choose a valid dataset.")
    return value


def validate_safe_name(value: str, what: str) -> str:
    if not _SAFE_NAME.fullmatch(value) or ".." in value:
        raise CurationError(f"{what} is not a valid file name.")
    return value


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "dataset"


def clean_text(value: object, what: str, *, max_length: int = 200, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise CurationError(f"{what} must be text.")
    text = " ".join(value.split())
    if required and not text:
        raise CurationError(f"{what} is required.")
    if any(ord(ch) < 32 for ch in text) or len(text) > max_length:
        raise CurationError(
            f"{what} must be at most {max_length} characters without control characters."
        )
    return text

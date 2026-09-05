"""Human label validation for local video review."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from openfloodai.contracts import read_jsonl_records, write_jsonl_record, write_jsonl_records
from openfloodai.contracts.local_store import JsonObject, JsonValue
from openfloodai.review.dataset_manifest import load_manifest_records

ALLOWED_HUMAN_LABELS = {
    "water_rising",
    "water_falling",
    "no_clear_change",
    "camera_video_problem",
    "cannot_judge",
}
ALLOWED_CONFIDENCE_LEVELS = {"low", "medium", "high"}
_HUMAN_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_HUMAN_LABEL_LENGTH = 64
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
    _validate_human_label_value(
        record.get("human_label"),
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


def _validate_human_label_value(
    value: object,
    errors: list[str],
    *,
    required: bool,
) -> None:
    if value is None:
        if required:
            errors.append("human_label is required")
        return
    if not isinstance(value, str) or not value.strip():
        errors.append("human_label must be a non-empty string")
        return
    clean_value = value.strip()
    if len(clean_value) > _MAX_HUMAN_LABEL_LENGTH:
        errors.append("human_label must be 64 characters or fewer")
        return
    if _HUMAN_LABEL_PATTERN.fullmatch(clean_value) is None:
        errors.append("human_label may use only letters, numbers, dash, and underscore")


def _is_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float)


_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class CreateHumanLabelResult:
    """Result of creating or updating a human label record."""

    site_dir: Path
    labels_path: Path
    record: JsonObject | None
    created: bool
    message: str


def create_human_label_record(
    site_dir: Path,
    video_id: str,
    start_second: float | int,
    end_second: float | int,
    human_label: str,
    *,
    confidence: str | None = None,
    note: str = "",
    reviewer_id: str = "",
    site_id: str = "",
    camera_id: str = "",
    labels_filename: str | None = None,
    overwrite: bool = False,
) -> CreateHumanLabelResult:
    """Create or update a human label record for a site video."""

    site_dir = Path(site_dir).resolve()

    if not site_dir.exists() or not site_dir.is_dir():
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message=f"Site folder does not exist: {site_dir}",
        )

    clean_video_id = str(video_id).strip()
    if not clean_video_id:
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message="Missing required field: video_id is required.",
        )

    if _VIDEO_ID_PATTERN.fullmatch(clean_video_id) is None:
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message="Invalid video_id: use only letters, numbers, dash, and underscore.",
        )

    try:
        start_num = float(start_second)
        end_num = float(end_second)
    except (ValueError, TypeError):
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message="time_window_seconds values must be numbers",
        )

    if not math.isfinite(start_num) or not math.isfinite(end_num):
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message="time_window_seconds values must be finite numbers",
        )

    if start_num < 0 or end_num < 0:
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message="time_window_seconds values must be 0 or greater",
        )

    if end_num <= start_num:
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message="time_window_seconds end must be greater than start",
        )

    clean_human_label = str(human_label).strip()
    if not clean_human_label:
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message="human_label is required",
        )

    label_errors: list[str] = []
    _validate_human_label_value(clean_human_label, label_errors, required=True)
    if label_errors:
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message="; ".join(label_errors),
        )

    clean_confidence = str(confidence).strip() if confidence is not None else ""
    if clean_confidence and clean_confidence not in ALLOWED_CONFIDENCE_LEVELS:
        joined = ", ".join(sorted(ALLOWED_CONFIDENCE_LEVELS))
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message=f"confidence must be one of: {joined}",
        )

    start_val: int | float = int(start_num) if start_num.is_integer() else start_num
    end_val: int | float = int(end_num) if end_num.is_integer() else end_num
    time_window: list[JsonValue] = [start_val, end_val]

    record: JsonObject = {
        "video_id": clean_video_id,
        "time_window_seconds": time_window,
        "human_label": clean_human_label,
    }
    if clean_confidence:
        record["confidence"] = clean_confidence
    if note and str(note).strip():
        record["note"] = str(note).strip()
    if reviewer_id and str(reviewer_id).strip():
        record["reviewer_id"] = str(reviewer_id).strip()
    if site_id and str(site_id).strip():
        record["site_id"] = str(site_id).strip()
    if camera_id and str(camera_id).strip():
        record["camera_id"] = str(camera_id).strip()

    validation_errors = validate_human_label_record(record)
    if validation_errors:
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message="; ".join(validation_errors),
        )

    labels_dir = (site_dir / "labels").resolve()
    labels_dir.mkdir(parents=True, exist_ok=True)

    if labels_filename and str(labels_filename).strip():
        chosen_name = Path(str(labels_filename).strip()).name
        if not chosen_name.endswith(".jsonl"):
            return CreateHumanLabelResult(
                site_dir=site_dir,
                labels_path=Path(),
                record=None,
                created=False,
                message="Labels filename must end with .jsonl",
            )
        target_path = (labels_dir / chosen_name).resolve()
    elif (labels_dir / "labels.jsonl").exists():
        target_path = (labels_dir / "labels.jsonl").resolve()
    else:
        existing_jsonls = sorted(labels_dir.glob("*.jsonl"))
        if len(existing_jsonls) == 1:
            target_path = existing_jsonls[0].resolve()
        else:
            target_path = (labels_dir / "labels.jsonl").resolve()

    try:
        target_path.relative_to(labels_dir)
    except ValueError:
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=Path(),
            record=None,
            created=False,
            message="Invalid labels_filename: file must stay inside the site labels directory.",
        )

    existing_records: list[JsonObject] = []
    if target_path.exists() and target_path.stat().st_size > 0:
        try:
            existing_records = load_human_label_records(target_path)
        except HumanLabelError as error:
            return CreateHumanLabelResult(
                site_dir=site_dir,
                labels_path=target_path,
                record=None,
                created=False,
                message=f"Existing labels file is invalid: {error}",
            )

    duplicate_index = -1
    for idx, existing in enumerate(existing_records):
        if existing.get("video_id") == clean_video_id and _window_matches(
            existing.get("time_window_seconds"), start_val, end_val
        ):
            duplicate_index = idx
            break

    if duplicate_index != -1 and not overwrite:
        return CreateHumanLabelResult(
            site_dir=site_dir,
            labels_path=target_path,
            record=None,
            created=False,
            message=(
                f"Label record already exists for video_id '{clean_video_id}' and "
                f"time window [{start_val}, {end_val}]. "
                "Use overwrite=True if you want to replace it."
            ),
        )

    if duplicate_index != -1:
        updated_records = list(existing_records)
        updated_records[duplicate_index] = record
        if target_path.exists():
            target_path.unlink()
        write_jsonl_records(target_path, updated_records)
        action_word = "Replaced"
    else:
        if target_path.exists() and target_path.stat().st_size > 0:
            content = target_path.read_bytes()
            if not content.endswith(b"\n"):
                with target_path.open("a", encoding="utf-8") as file:
                    file.write("\n")
        write_jsonl_record(target_path, record)
        action_word = "Added"

    _update_manifest_human_label(site_dir, clean_video_id)

    return CreateHumanLabelResult(
        site_dir=site_dir,
        labels_path=target_path,
        record=record,
        created=True,
        message=(
            f"{action_word} label record for video_id '{clean_video_id}' "
            f"[{start_val}, {end_val}] in {target_path.name}."
        ),
    )


add_human_label_record = create_human_label_record


def _window_matches(window_obj: object, start_val: int | float, end_val: int | float) -> bool:
    if isinstance(window_obj, list) and len(window_obj) == 2:
        try:
            return float(window_obj[0]) == float(start_val) and float(window_obj[1]) == float(
                end_val
            )
        except (ValueError, TypeError):
            return False
    return False


def _update_manifest_human_label(site_dir: Path, video_id: str) -> None:
    manifest_path = site_dir / "manifest.jsonl"
    if not manifest_path.exists() or not manifest_path.is_file():
        return
    try:
        records = load_manifest_records(manifest_path)
    except Exception:
        return
    updated = False
    for record in records:
        if record.get("video_id") == video_id and not record.get("has_human_label"):
            record["has_human_label"] = True
            updated = True
    if updated:
        manifest_path.unlink()
        write_jsonl_records(manifest_path, records)

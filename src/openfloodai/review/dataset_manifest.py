"""Validation dataset manifest helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from openfloodai.contracts import read_jsonl_records, write_jsonl_records
from openfloodai.contracts.local_store import JsonObject

ALLOWED_MANIFEST_SPLITS = {"practice", "locked_validation"}
MANIFEST_PURPOSE_OPTIONS = (
    "practice_normal_water",
    "possible_rising_water",
    "possible_falling_water",
    "no_clear_change",
    "hard_case_review",
    "camera_video_problem",
)
HARD_CASE_TYPE_OPTIONS = (
    "heavy_glare",
    "rain_or_noisy_image",
    "night_or_dark_frame",
    "camera_shake",
    "blocked_view",
    "compression_or_noise_artifacts",
    "unreadable_video",
    "empty_video",
    "missing_video",
    "camera_offline",
)
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


@dataclass(frozen=True)
class ManifestRepairResult:
    """Result of conservatively creating missing local-video manifest rows."""

    manifest_path: Path
    created_count: int
    preserved_count: int
    issues: list[str]

    @property
    def created(self) -> bool:
        """Return whether the manifest was created or extended."""

        return self.created_count > 0

    @property
    def message(self) -> str:
        """Return a plain-language repair result without hiding outstanding issues."""

        if self.issues:
            return "Manifest was not changed: " + "; ".join(self.issues)
        if self.created_count:
            return (
                f"Added {self.created_count} missing manifest row(s). "
                f"Preserved {self.preserved_count} existing row(s). "
                "New videos are not approved for repository use."
            )
        return "Manifest already tracks every local video. Existing metadata was preserved."


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


def repair_manifest_from_local_videos(site_dir: Path) -> ManifestRepairResult:
    """Create only missing manifest rows for local videos, preserving existing metadata."""

    manifest_path = site_dir / "manifest.jsonl"
    videos_dir = site_dir / "inputs" / "videos"
    video_paths = (
        sorted(
            path
            for path in videos_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".avi", ".mkv", ".mov", ".mp4"}
        )
        if videos_dir.is_dir()
        else []
    )

    try:
        existing_records = read_jsonl_records(manifest_path) if manifest_path.exists() else []
    except ValueError as error:
        return ManifestRepairResult(manifest_path, 0, 0, [f"Could not read manifest: {error}"])

    issues = _manifest_repair_issues(existing_records)
    if issues:
        return ManifestRepairResult(manifest_path, 0, len(existing_records), issues)

    tracked_filenames = {
        record["filename"] for record in existing_records if isinstance(record.get("filename"), str)
    }
    tracked_video_ids = {
        record["video_id"] for record in existing_records if isinstance(record.get("video_id"), str)
    }
    new_records: list[JsonObject] = []
    for video_path in video_paths:
        if video_path.name in tracked_filenames:
            continue
        if video_path.stem in tracked_video_ids:
            issues.append(f"Local video conflicts with manifest video_id: {video_path.stem}")
            continue
        new_records.append(
            {
                "video_id": video_path.stem,
                "filename": video_path.name,
                "purpose": "practice_normal_water",
                "split": "practice",
                "approved_for_repo": False,
                "has_human_label": False,
                "notes": "Created from an existing local video; review metadata before validation.",
            }
        )

    if issues:
        return ManifestRepairResult(manifest_path, 0, len(existing_records), issues)
    if new_records:
        write_jsonl_records(manifest_path, [*existing_records, *new_records])
    return ManifestRepairResult(manifest_path, len(new_records), len(existing_records), [])


def _manifest_repair_issues(records: list[JsonObject]) -> list[str]:
    issues: list[str] = []
    seen_video_ids: set[str] = set()
    seen_filenames: set[str] = set()
    for index, record in enumerate(records, start=1):
        errors = validate_manifest_record(record)
        if errors:
            issues.append(f"Manifest row {index} is incomplete: {'; '.join(errors)}")
            continue
        video_id = str(record["video_id"])
        filename = str(record["filename"])
        if video_id in seen_video_ids:
            issues.append(f"Manifest has conflicting video_id: {video_id}")
        if filename in seen_filenames:
            issues.append(f"Manifest has conflicting filename: {filename}")
        seen_video_ids.add(video_id)
        seen_filenames.add(filename)
    return issues


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

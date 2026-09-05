"""Copy a local validation video into a site folder and record manifest metadata."""

from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from openfloodai.contracts.local_store import JsonObject, write_jsonl_records
from openfloodai.review.dataset_manifest import (
    ALLOWED_MANIFEST_SPLITS,
    DatasetManifestError,
    load_manifest_records,
    validate_manifest_record,
)
from openfloodai.validation.site_status import VIDEO_SUFFIXES

_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class ValidationVideoIntakeResult:
    """Result of adding one local validation video."""

    site_dir: Path
    video_path: Path
    manifest_path: Path
    created: bool
    message: str


def intake_validation_video(
    site_dir: Path,
    video_path: Path,
    video_id: str,
    purpose: str,
    split: str,
    notes: str,
    *,
    approved_for_repo: bool = False,
    has_human_label: bool = False,
    hard_case_type: str = "",
    overwrite: bool = False,
) -> ValidationVideoIntakeResult:
    """Copy a local video into a site folder and create or update its manifest row."""

    empty = ValidationVideoIntakeResult(
        site_dir=Path(),
        video_path=Path(),
        manifest_path=Path(),
        created=False,
        message="",
    )

    if not video_id or not purpose or not notes:
        return replace(
            empty,
            message=("Missing required fields: video_id, purpose, and notes are all required."),
        )

    if _VIDEO_ID_PATTERN.fullmatch(video_id) is None:
        return replace(
            empty,
            message=("Invalid video_id: use only letters, numbers, dash, and underscore."),
        )

    if split not in ALLOWED_MANIFEST_SPLITS:
        joined = ", ".join(sorted(ALLOWED_MANIFEST_SPLITS))
        return replace(empty, message=f"Invalid split: use one of {joined}.")

    if not site_dir.exists() or not site_dir.is_dir():
        return replace(empty, message=f"Site folder does not exist: {site_dir}")

    source = Path(video_path)
    if not source.exists() or not source.is_file():
        return replace(empty, message=f"Video file does not exist: {source}")

    suffix = source.suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        allowed = ", ".join(sorted(VIDEO_SUFFIXES))
        return replace(
            empty,
            message=f"Unsupported video type {suffix or '(none)'}. Use one of: {allowed}.",
        )

    videos_dir = site_dir / "inputs" / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{video_id}{suffix}"
    destination = (videos_dir / filename).resolve()
    try:
        destination.relative_to(videos_dir.resolve())
    except ValueError:
        return replace(
            empty,
            message="Invalid video_id: destination must stay inside the site videos folder.",
        )

    manifest_path = site_dir / "manifest.jsonl"
    try:
        records = _load_existing_records(manifest_path)
    except DatasetManifestError as error:
        return replace(empty, message=str(error))

    duplicate_id = any(record.get("video_id") == video_id for record in records)
    duplicate_name = any(record.get("filename") == filename for record in records)
    if not overwrite and (duplicate_id or duplicate_name or destination.exists()):
        if duplicate_id:
            reason = f"video_id already exists: {video_id}"
        elif duplicate_name:
            reason = f"filename already exists: {filename}"
        else:
            reason = f"Video file already exists: {destination}"
        return ValidationVideoIntakeResult(
            site_dir=site_dir,
            video_path=destination,
            manifest_path=manifest_path,
            created=False,
            message=f"{reason}. Use overwrite=True if you want to replace it.",
        )

    record: dict[str, object] = {
        "video_id": video_id,
        "filename": filename,
        "purpose": purpose,
        "split": split,
        "approved_for_repo": bool(approved_for_repo),
        "has_human_label": bool(has_human_label),
        "notes": notes,
    }
    if hard_case_type.strip():
        record["hard_case_type"] = hard_case_type.strip()

    errors = validate_manifest_record(record)
    if errors:
        return replace(empty, message="; ".join(errors))

    if source.resolve() != destination:
        shutil.copy2(source, destination)

    kept: list[Mapping[str, object]] = [
        existing
        for existing in records
        if existing.get("video_id") != video_id and existing.get("filename") != filename
    ]
    kept.append(record)
    _rewrite_manifest(manifest_path, kept)

    return ValidationVideoIntakeResult(
        site_dir=site_dir,
        video_path=destination,
        manifest_path=manifest_path,
        created=True,
        message=f"Added video {filename} and updated {manifest_path.name}.",
    )


def _load_existing_records(manifest_path: Path) -> list[JsonObject]:
    if not manifest_path.exists():
        return []
    return load_manifest_records(manifest_path)


def _rewrite_manifest(path: Path, records: list[Mapping[str, object]]) -> None:
    if path.exists():
        path.unlink()
    write_jsonl_records(path, records)

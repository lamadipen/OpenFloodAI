"""Validate a built release: checksums, schema, splits, licensing files and a privacy scan."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openfloodai.curation.common import sha256_file

REQUIRED_FILES = (
    "README.md",
    "LICENSE-DATA.md",
    "CHANGELOG.md",
    "metadata.jsonl",
    "sites.json",
    "checksums.sha256",
    "release-manifest.json",
    "REJECTIONS.md",
    "RELEASE-CHECKLIST.md",
)
REQUIRED_ROW_FIELDS = (
    "sample_id",
    "observation_id",
    "split",
    "task",
    "file_name",
    "site_id",
    "camera_id",
    "captured_at_utc",
    "source_system",
    "source_url",
    "source_credit",
    "image_sha256",
    "annotation_kind",
    "annotation",
    "review_status",
)
SPLITS = ("train", "validation", "test")
# Things that must never reach a public release: local paths and credential-like strings.
_FORBIDDEN = [
    ("local_path", re.compile(r"(?:/Users/|/home/|/private/var/|[A-Za-z]:\\\\|file://)")),
    (
        "secret",
        re.compile(r"(?:hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._-]{16,})"),
    ),
    ("credential_word", re.compile(r"(?i)(?:api[_-]?key|password|secret[_-]?token)\s*[:=]")),
]
_TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".sha256", ".txt"}
FORBIDDEN_ROW_FIELDS = ("note", "notes", "reviewer_id", "dataset_group", "folder_name", "run_id")
# Keys that must not appear anywhere inside the JSON text columns (guides, annotation, region).
FORBIDDEN_NESTED_KEYS = frozenset(
    {
        "note",
        "notes",
        "label",
        "reviewer_id",
        "reviewed_by",
        "author",
        "approved_by",
        "run_id",
        "folder_name",
        "path",
        "video_id",
        "image_filename",
        "image_sequence_id",
    }
)
JSON_COLUMNS = (
    "watched_region",
    "riverbank_guides",
    "annotation",
    "mask_files",
    "gauge_qualifiers",
    "later_gauge_qualifiers",
)


def _nested_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            found.add(str(key))
            found |= _nested_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            found |= _nested_keys(inner)
    return found


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def privacy_findings(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in _FORBIDDEN:
            match = pattern.search(text)
            if match:
                findings.append(
                    f"{path.relative_to(root).as_posix()}: contains a {name} "
                    f"({match.group(0)[:20]!r})."
                )
    return findings


def checklist_complete(root: Path) -> bool:
    path = root / "RELEASE-CHECKLIST.md"
    if not path.is_file():
        return False
    boxes = [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- [")
    ]
    return bool(boxes) and all(line.startswith("- [x]") for line in boxes)


def verify_release(root: Path, *, require_checklist: bool = False) -> dict[str, Any]:
    """Check a release folder and return `{ok, problems}`; it changes nothing."""

    problems: list[str] = []
    for name in REQUIRED_FILES:
        if not (root / name).is_file():
            problems.append(f"{name} is missing.")
    if problems:
        return {"ok": False, "problems": problems}
    listed: dict[str, str] = {}
    for line in (root / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        sha, _, name = line.partition("  ")
        listed[name] = sha
    for name, sha in listed.items():
        path = root / name
        if not path.is_file():
            problems.append(f"{name} is listed in the checksums but missing.")
        elif sha256_file(path) != sha:
            problems.append(f"{name} has changed since the release was built.")
    # The checksum list and the human-edited checklist are not themselves checksummed.
    on_disk = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} - {
        "checksums.sha256",
        "RELEASE-CHECKLIST.md",
    }
    for extra in sorted(on_disk - set(listed)):
        problems.append(f"{extra} is not in the checksum list.")

    rows = _lines(root / "metadata.jsonl")
    seen: set[str] = set()
    camera_splits: dict[str, set[str]] = {}
    site_splits: dict[str, set[str]] = {}
    for row in rows:
        missing = [f for f in REQUIRED_ROW_FIELDS if row.get(f) in (None, "")]
        if missing:
            problems.append(
                f"{row.get('sample_id')}: missing required fields {', '.join(missing)}."
            )
        for forbidden in FORBIDDEN_ROW_FIELDS:
            if forbidden in row:
                problems.append(f"{row.get('sample_id')}: contains the internal field {forbidden}.")
        if row.get("sample_id") in seen:
            problems.append(f"{row.get('sample_id')}: appears twice.")
        seen.add(str(row.get("sample_id")))
        if row.get("split") not in SPLITS:
            problems.append(f"{row.get('sample_id')}: has no valid split.")
        camera_splits.setdefault(str(row.get("camera_id")), set()).add(str(row.get("split")))
        site_splits.setdefault(str(row.get("site_id")), set()).add(str(row.get("split")))
        for column in JSON_COLUMNS:
            if not row.get(column):
                continue
            try:
                private = sorted(_nested_keys(json.loads(row[column])) & FORBIDDEN_NESTED_KEYS)
            except ValueError:
                problems.append(f"{row.get('sample_id')}: {column} is not valid JSON.")
                continue
            if private:
                problems.append(
                    f"{row.get('sample_id')}: {column} contains private field(s) "
                    f"{', '.join(private)}."
                )
        for field in ("file_name", "later_file_name", "baseline_file_name"):
            if row.get(field) and not (root / row[field]).is_file():
                problems.append(f"{row.get('sample_id')}: {row[field]} is missing.")
        for mask in json.loads(row.get("mask_files") or "[]"):
            if not (root / mask).is_file():
                problems.append(f"{row.get('sample_id')}: {mask} is missing.")
    for camera, splits in sorted(camera_splits.items()):
        if len(splits) > 1:
            problems.append(f"{camera} is in more than one split ({', '.join(sorted(splits))}).")
    for site, splits in sorted(site_splits.items()):
        if len(splits) > 1:
            problems.append(
                f"Site {site} is in more than one split ({', '.join(sorted(splits))}), "
                "so its cameras would leak between training and evaluation."
            )
    per_split: dict[str, set[str]] = {}
    for name in SPLITS:
        path = root / "splits" / f"{name}.jsonl"
        if path.is_file():
            per_split[name] = {r["sample_id"] for r in _lines(path)}
    union = [s for ids in per_split.values() for s in ids]
    if sorted(union) != sorted(seen):
        problems.append("The split files do not contain every example exactly once.")

    manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
    if manifest["counts"]["released"] != len(rows):
        problems.append("The manifest count does not match metadata.jsonl.")
    if manifest["channel"] == "public" and manifest.get("readiness_gaps"):
        problems.append("A public release cannot carry readiness gaps.")
    card = (root / "README.md").read_text(encoding="utf-8")
    for needed in ("Sources and credit", "Intended use and limits", "Licensing", "Citation"):
        if needed not in card:
            problems.append(f"The dataset card has no '{needed}' section.")
    problems += privacy_findings(root)
    if require_checklist and not checklist_complete(root):
        problems.append("RELEASE-CHECKLIST.md is not fully ticked.")
    return {"ok": not problems, "problems": problems}

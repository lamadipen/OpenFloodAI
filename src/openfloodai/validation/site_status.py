"""Read local validation site readiness status."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VIDEO_SUFFIXES = {".avi", ".mkv", ".mov", ".mp4"}
REPORT_PREVIEW_MAX_LENGTH = 1200


@dataclass(frozen=True)
class ValidationSiteStatus:
    """Simple readiness status for one local validation site."""

    site_name: str
    site_path: str
    config_found: bool
    config_count: int
    video_count: int
    video_ids: list[str]
    labels_found: bool
    label_count: int
    human_label_options: list[str]
    manifest_found: bool
    outputs_found: bool
    report_count: int
    latest_report_path: str | None
    latest_report_preview: str | None
    latest_report_counts: dict[str, int] | None
    latest_scorecard: dict[str, Any] | None
    review_images_path: str | None
    report_history: list[dict[str, Any]]

    @property
    def ready_for_machine_review(self) -> bool:
        """Return whether the site has the minimum files for machine review."""

        return self.config_found and self.video_count > 0

    @property
    def ready_for_human_comparison(self) -> bool:
        """Return whether the site has files needed for human comparison."""

        return self.ready_for_machine_review and self.labels_found and self.manifest_found

    @property
    def ready_for_validation(self) -> bool:
        """Return whether the site can run machine review."""

        return self.ready_for_machine_review

    @property
    def machine_review_explanation(self) -> str:
        """Explain whether the site has the files needed for machine review."""

        if self.ready_for_machine_review:
            return "Ready because config and videos are found."
        missing: list[str] = []
        if not self.config_found:
            missing.append("config")
        if self.video_count == 0:
            missing.append("videos")
        return f"Not ready because {_join_missing_items(missing)} are missing."

    @property
    def human_comparison_explanation(self) -> str:
        """Explain whether the site has the files needed for human comparison."""

        if self.ready_for_human_comparison:
            return "Ready because config, videos, labels, and manifest are found."
        missing: list[str] = []
        if not self.ready_for_machine_review:
            if not self.config_found:
                missing.append("config")
            if self.video_count == 0:
                missing.append("videos")
        if not self.labels_found:
            missing.append("labels")
        if not self.manifest_found:
            missing.append("manifest")
        return f"Not ready because {_join_missing_items(missing)} are missing."

    @property
    def next_steps(self) -> list[str]:
        """Return simple local actions that address missing site readiness items."""

        steps: list[str] = []
        if not self.config_found:
            steps.append("Add a site config under configs/.")
        if self.video_count == 0:
            steps.append("Add video files under inputs/videos/.")
        if not self.labels_found:
            steps.append("Machine review can still run, but human comparison needs labels.")
        if not self.manifest_found:
            steps.append("Add manifest.jsonl so videos can be tracked clearly.")
        if not self.outputs_found:
            steps.append("Run validation to create the first report.")
        if not steps:
            steps.append("Review the latest validation report and review images.")
        return steps

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this status."""

        payload = asdict(self)
        payload["ready_for_machine_review"] = self.ready_for_machine_review
        payload["ready_for_human_comparison"] = self.ready_for_human_comparison
        payload["ready_for_validation"] = self.ready_for_validation
        payload["machine_review_explanation"] = self.machine_review_explanation
        payload["human_comparison_explanation"] = self.human_comparison_explanation
        payload["next_steps"] = self.next_steps
        return payload


def discover_validation_site_statuses(
    sites_dir: Path = Path("data/sites"),
) -> list[ValidationSiteStatus]:
    """Return readiness status for each local validation site folder."""

    if not sites_dir.exists() or not sites_dir.is_dir():
        return []

    return [
        read_validation_site_status(site_dir)
        for site_dir in sorted(path for path in sites_dir.iterdir() if path.is_dir())
    ]


def read_validation_site_status(site_dir: Path) -> ValidationSiteStatus:
    """Return readiness status for one local validation site folder."""

    config_paths = _find_config_paths(site_dir)
    video_paths = _find_video_paths(site_dir)
    label_paths = _find_label_paths(site_dir)
    human_label_options = _find_human_label_options(label_paths)
    report_paths = _find_report_paths(site_dir)
    latest_report_path = _latest_path(report_paths)
    review_images_path = _latest_path(_find_review_images_paths(site_dir))

    return ValidationSiteStatus(
        site_name=site_dir.name,
        site_path=str(site_dir),
        config_found=bool(config_paths),
        config_count=len(config_paths),
        video_count=len(video_paths),
        video_ids=sorted({path.stem for path in video_paths}),
        labels_found=bool(label_paths),
        label_count=len(label_paths),
        human_label_options=human_label_options,
        manifest_found=(site_dir / "manifest.jsonl").is_file(),
        outputs_found=bool(report_paths),
        report_count=len(report_paths),
        latest_report_path=str(latest_report_path) if latest_report_path else None,
        latest_report_preview=_read_report_preview(latest_report_path),
        latest_report_counts=_read_report_counts(latest_report_path),
        latest_scorecard=_read_scorecard(latest_report_path),
        review_images_path=str(review_images_path) if review_images_path else None,
        report_history=_build_report_history(report_paths, review_images_path),
    )


def _find_config_paths(site_dir: Path) -> list[Path]:
    configs_dir = site_dir / "configs"
    if not configs_dir.exists():
        return []
    return sorted(path for path in configs_dir.glob("*.json") if path.is_file())


def _find_video_paths(site_dir: Path) -> list[Path]:
    videos_dir = site_dir / "inputs" / "videos"
    if not videos_dir.exists():
        return []
    return sorted(
        path
        for path in videos_dir.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
    )


def _find_label_paths(site_dir: Path) -> list[Path]:
    labels_dir = site_dir / "labels"
    if not labels_dir.exists():
        return []
    return sorted(path for path in labels_dir.glob("*.jsonl") if path.is_file())


def _find_human_label_options(label_paths: list[Path]) -> list[str]:
    options: set[str] = set()
    for label_path in label_paths:
        try:
            for line in label_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    continue
                label = record.get("human_label")
                if isinstance(label, str) and label.strip():
                    options.add(label.strip())
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
    return sorted(options)


def _find_report_paths(site_dir: Path) -> list[Path]:
    outputs_dir = site_dir / "outputs"
    if not outputs_dir.exists():
        return []
    return sorted(path for path in outputs_dir.rglob("validation-report*.md") if path.is_file())


def _find_review_images_paths(site_dir: Path) -> list[Path]:
    outputs_dir = site_dir / "outputs"
    if not outputs_dir.exists():
        return []
    return sorted(path for path in outputs_dir.rglob("review-images") if path.is_dir())


def _read_report_counts(report_path: Path | None) -> dict[str, int] | None:
    if report_path is None:
        return None
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    counts: dict[str, int] = {}
    for label, key in (
        ("Agree", "agree"),
        ("Disagree", "disagree"),
        ("Cannot compare", "cannot_compare"),
    ):
        match = re.search(rf"^- {re.escape(label)}:\s*(\d+)\s*$", report_text, re.MULTILINE)
        if match:
            counts[key] = int(match.group(1))
    return counts or None


def _read_report_preview(report_path: Path | None) -> str | None:
    if report_path is None:
        return None
    try:
        report_lines = report_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    preview_lines: list[str] = []
    in_counts = False
    for line in report_lines:
        if line == "## Counts":
            in_counts = True
        elif in_counts and line.startswith("## "):
            break
        if line.startswith("# Site Validation Report") or in_counts:
            preview_lines.append(line)
        elif line == "" and preview_lines:
            preview_lines.append(line)

    preview = "\n".join(preview_lines).strip()
    if not preview:
        return None
    if len(preview) > REPORT_PREVIEW_MAX_LENGTH:
        return preview[:REPORT_PREVIEW_MAX_LENGTH].rstrip() + "..."
    return preview


def _read_scorecard(report_path: Path | None) -> dict[str, Any] | None:
    if report_path is None:
        return None
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    fields: dict[str, Any] = {}
    patterns = (
        ("videos_tested", "Videos tested", int),
        ("label_windows", "Label windows", int),
        ("agree", "Agree", int),
        ("disagree", "Disagree", int),
        ("cannot_compare", "Cannot compare", int),
    )
    for key, label, converter in patterns:
        match = re.search(rf"^- {re.escape(label)}:\s*(\d+)\s*$", report_text, re.MULTILINE)
        if match:
            fields[key] = converter(match.group(1))

    summary_match = re.search(r"^- Summary:\s*(.+)$", report_text, re.MULTILINE)
    if summary_match:
        fields["summary"] = summary_match.group(1).strip()
    if not fields:
        return None
    fields["human_review_needed"] = fields.get("disagree", 0) + fields.get("cannot_compare", 0)
    return fields


def _build_report_history(
    report_paths: list[Path],
    review_images_path: Path | None,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for report_path in sorted(report_paths, key=_path_sort_key, reverse=True):
        try:
            modified_time = report_path.stat().st_mtime
        except OSError:
            continue
        history.append(
            {
                "path": str(report_path),
                "modified_time": datetime.fromtimestamp(modified_time, tz=UTC).isoformat(),
                "counts": _read_report_counts(report_path),
                "evidence_path": str(review_images_path) if review_images_path else None,
            }
        )
    return history


def _path_sort_key(path: Path) -> tuple[float, str]:
    try:
        modified_time = path.stat().st_mtime
    except OSError:
        modified_time = 0.0
    return modified_time, str(path)


def _latest_path(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return max(paths, key=lambda path: (path.stat().st_mtime, str(path)))


def _join_missing_items(items: list[str]) -> str:
    if len(items) < 2:
        return items[0]
    if len(items) == 2:
        return " and ".join(items)
    return f"{', '.join(items[:-1])}, and {items[-1]}"

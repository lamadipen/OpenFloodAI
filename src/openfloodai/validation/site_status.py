"""Read local validation site readiness status."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

VIDEO_SUFFIXES = {".avi", ".mkv", ".mov", ".mp4"}


@dataclass(frozen=True)
class ValidationSiteStatus:
    """Simple readiness status for one local validation site."""

    site_name: str
    site_path: str
    config_found: bool
    config_count: int
    video_count: int
    labels_found: bool
    label_count: int
    human_label_options: list[str]
    manifest_found: bool
    outputs_found: bool
    report_count: int
    latest_report_path: str | None

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

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this status."""

        payload = asdict(self)
        payload["ready_for_machine_review"] = self.ready_for_machine_review
        payload["ready_for_human_comparison"] = self.ready_for_human_comparison
        payload["ready_for_validation"] = self.ready_for_validation
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

    return ValidationSiteStatus(
        site_name=site_dir.name,
        site_path=str(site_dir),
        config_found=bool(config_paths),
        config_count=len(config_paths),
        video_count=len(video_paths),
        labels_found=bool(label_paths),
        label_count=len(label_paths),
        human_label_options=human_label_options,
        manifest_found=(site_dir / "manifest.jsonl").is_file(),
        outputs_found=bool(report_paths),
        report_count=len(report_paths),
        latest_report_path=str(latest_report_path) if latest_report_path else None,
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
    return sorted(path for path in outputs_dir.rglob("*.md") if path.is_file())


def _latest_path(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return max(paths, key=lambda path: (path.stat().st_mtime, str(path)))

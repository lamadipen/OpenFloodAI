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


READINESS_FULL = "full"
READINESS_MACHINE_ONLY = "machine_only"
READINESS_BLOCKED = "blocked"


@dataclass(frozen=True)
class ReadinessCheck:
    """One input the local validation run depends on."""

    label: str
    value: str
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this check."""

        return asdict(self)


@dataclass(frozen=True)
class ValidationReadiness:
    """What a local validation run will do for one site before it starts."""

    mode: str
    headline: str
    checks: list[ReadinessCheck]
    missing: list[str]
    notes: list[str]

    @property
    def can_run(self) -> bool:
        """Return whether validation can start at all."""

        return self.mode != READINESS_BLOCKED

    @property
    def compares_with_human_labels(self) -> bool:
        """Return whether the run will compare machine evidence with human labels."""

        return self.mode == READINESS_FULL

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this readiness summary."""

        payload = asdict(self)
        payload["checks"] = [check.to_dict() for check in self.checks]
        payload["can_run"] = self.can_run
        payload["compares_with_human_labels"] = self.compares_with_human_labels
        return payload


WORKFLOW_STEP_COMPLETE = "complete"
WORKFLOW_STEP_MISSING = "missing"
WORKFLOW_STEP_NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class WorkflowAction:
    """One button offered by a guided workflow step."""

    label: str
    action_id: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this action."""

        return asdict(self)


@dataclass(frozen=True)
class WorkflowStep:
    """One step in the guided local validation workflow."""

    number: int
    key: str
    title: str
    status: str
    meaning: str
    actions: list[WorkflowAction]
    required_for_validation: bool

    @property
    def status_text(self) -> str:
        """Return simple wording for this step status."""

        if self.status == WORKFLOW_STEP_COMPLETE:
            return "Complete"
        if self.status == WORKFLOW_STEP_MISSING:
            return "Missing"
        return "Needs review"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this workflow step."""

        payload = asdict(self)
        payload["status_text"] = self.status_text
        payload["actions"] = [action.to_dict() for action in self.actions]
        return payload


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
    reference_region_found: bool
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
        """Return whether the site has the minimum files for machine review.

        The watched area counts because run_local_video_review reads evidence
        inside the configured reference_region and fails without one.
        """

        return self.config_found and self.video_count > 0 and self.reference_region_found

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
            return "Ready because config, videos, and a watched area are found."
        return (
            f"Not ready because {_join_missing_items(self._missing_machine_items())} are missing."
        )

    @property
    def human_comparison_explanation(self) -> str:
        """Explain whether the site has the files needed for human comparison."""

        if self.ready_for_human_comparison:
            return "Ready because config, videos, labels, and manifest are found."
        missing: list[str] = []
        if not self.ready_for_machine_review:
            missing.extend(self._missing_machine_items())
        if not self.labels_found:
            missing.append("labels")
        if not self.manifest_found:
            missing.append("manifest")
        return f"Not ready because {_join_missing_items(missing)} are missing."

    def _missing_machine_items(self) -> list[str]:
        """Return the required machine-review inputs this site does not have."""

        missing: list[str] = []
        if not self.config_found:
            missing.append("config")
        if self.video_count == 0:
            missing.append("videos")
        if not self.reference_region_found:
            missing.append("watched area")
        return missing

    @property
    def validation_readiness(self) -> ValidationReadiness:
        """Describe what a validation run will do for this site before it starts."""

        video_value = f"{self.video_count} found" if self.video_count else "None found"
        label_value = (
            f"{self.label_count} label file(s) found" if self.labels_found else "None found"
        )
        checks = [
            ReadinessCheck(
                label="Site config",
                value="Found" if self.config_found else "Missing",
                ok=self.config_found,
            ),
            ReadinessCheck(label="Videos", value=video_value, ok=self.video_count > 0),
            ReadinessCheck(
                label="Watched area",
                value="Found" if self.reference_region_found else "Missing",
                ok=self.reference_region_found,
            ),
            ReadinessCheck(label="Human labels", value=label_value, ok=self.labels_found),
            ReadinessCheck(
                label="Manifest",
                value="Found" if self.manifest_found else "Missing",
                ok=self.manifest_found,
            ),
            ReadinessCheck(label="Output", value="Saved on this computer", ok=True),
        ]

        if not self.ready_for_machine_review:
            missing = self._missing_machine_items()
            notes = [
                "Add the missing items above to start a run.",
                "No video is checked yet. No report is saved yet.",
            ]
            return ValidationReadiness(
                mode=READINESS_BLOCKED,
                headline="Cannot run yet. Something is missing.",
                checks=checks,
                missing=missing,
                notes=notes,
            )

        if self.ready_for_human_comparison:
            notes = [
                "The system checks every video in this site.",
                "It looks at frames inside each time window a person labelled.",
                "It compares what it saw with what the person wrote.",
                "It saves a report, a scorecard, and review images.",
                "Unclear cases stay as cannot_compare. They do not count as success.",
            ]
            return ValidationReadiness(
                mode=READINESS_FULL,
                headline="Ready to run. The system will compare with human labels.",
                checks=checks,
                missing=[],
                notes=notes,
            )

        missing = []
        if not self.labels_found:
            missing.append("human labels")
        if not self.manifest_found:
            missing.append("manifest")
        notes = [
            "The system checks every video and saves records and review images.",
            "There are no human labels, so it cannot check its own work.",
            "Every result stays cannot_compare.",
            "This run does not show that the system is right.",
        ]
        return ValidationReadiness(
            mode=READINESS_MACHINE_ONLY,
            headline="Ready to run, but there is nothing to compare with.",
            checks=checks,
            missing=missing,
            notes=notes,
        )

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

    @property
    def workflow_steps(self) -> list[WorkflowStep]:
        """Return the guided validation workflow steps for this site.

        Each step reports its own status so a user can start from any step that
        still needs work instead of restarting the whole workflow.
        """

        has_videos = self.video_count > 0
        has_reports = self.report_count > 0

        site_actions = [WorkflowAction(label="Create site", action_id="create_site")]
        if self.config_found:
            site_actions = [
                WorkflowAction(label="Select site", action_id="select_site"),
                WorkflowAction(label="Create another site", action_id="create_site"),
            ]

        video_actions = [WorkflowAction(label="Add video", action_id="add_video")]
        if has_videos:
            video_actions = [
                WorkflowAction(label="Select video", action_id="select_video"),
                WorkflowAction(label="Add video", action_id="add_video"),
            ]

        label_actions = [WorkflowAction(label="Add label", action_id="add_label")]
        if self.labels_found:
            label_actions = [
                WorkflowAction(label="Select label", action_id="select_label"),
                WorkflowAction(label="Add label", action_id="add_label"),
            ]

        return [
            WorkflowStep(
                number=1,
                key="site_setup",
                title="Site setup",
                status=(WORKFLOW_STEP_COMPLETE if self.config_found else WORKFLOW_STEP_MISSING),
                meaning=("The site config holds the camera and place details. Every run uses it."),
                actions=site_actions,
                required_for_validation=True,
            ),
            WorkflowStep(
                number=2,
                key="video_intake",
                title="Video intake",
                status=WORKFLOW_STEP_COMPLETE if has_videos else WORKFLOW_STEP_MISSING,
                meaning=("The system checks these videos. They stay on this computer."),
                actions=video_actions,
                required_for_validation=True,
            ),
            WorkflowStep(
                number=3,
                key="watched_area",
                title="Watched area",
                status=(
                    WORKFLOW_STEP_COMPLETE if self.reference_region_found else WORKFLOW_STEP_MISSING
                ),
                meaning=(
                    "Pick the part of the video where the system should look for water "
                    "change. A run cannot start without it. You pick this area when you "
                    "add a video."
                ),
                actions=[WorkflowAction(label="Set area in video intake", action_id="add_video")],
                required_for_validation=True,
            ),
            WorkflowStep(
                number=4,
                key="human_labels",
                title="Human labels",
                status=(
                    WORKFLOW_STEP_COMPLETE if self.labels_found else WORKFLOW_STEP_NEEDS_REVIEW
                ),
                meaning=(
                    "A human label says what a person saw. Without labels the system "
                    "cannot check its work, and results stay cannot_compare."
                ),
                actions=label_actions,
                required_for_validation=False,
            ),
            WorkflowStep(
                number=5,
                key="manifest",
                title="Manifest",
                status=(
                    WORKFLOW_STEP_COMPLETE if self.manifest_found else WORKFLOW_STEP_NEEDS_REVIEW
                ),
                meaning=(
                    "The manifest says which video is which, and if it can be shared. "
                    "You need it to compare with human labels."
                ),
                actions=[
                    WorkflowAction(label="Add video to update manifest", action_id="add_video")
                ],
                required_for_validation=False,
            ),
            WorkflowStep(
                number=6,
                key="run_validation",
                title="Run validation",
                status=(
                    WORKFLOW_STEP_COMPLETE
                    if has_reports
                    else (
                        WORKFLOW_STEP_NEEDS_REVIEW
                        if self.ready_for_validation
                        else WORKFLOW_STEP_MISSING
                    )
                ),
                meaning=("Check the videos, save what the system saw, and compare with labels."),
                actions=[WorkflowAction(label="Run validation", action_id="run_validation")],
                required_for_validation=True,
            ),
            WorkflowStep(
                number=7,
                key="review_results",
                title="Review results",
                status=(
                    WORKFLOW_STEP_COMPLETE if self.latest_report_path else WORKFLOW_STEP_MISSING
                ),
                meaning=(
                    "Read the report, the scorecard, and the review images. Unclear "
                    "cases stay as cannot_compare."
                ),
                actions=[WorkflowAction(label="Review results", action_id="review_results")],
                required_for_validation=False,
            ),
        ]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this status."""

        payload = asdict(self)
        payload["ready_for_machine_review"] = self.ready_for_machine_review
        payload["ready_for_human_comparison"] = self.ready_for_human_comparison
        payload["ready_for_validation"] = self.ready_for_validation
        payload["machine_review_explanation"] = self.machine_review_explanation
        payload["human_comparison_explanation"] = self.human_comparison_explanation
        payload["next_steps"] = self.next_steps
        payload["workflow_steps"] = [step.to_dict() for step in self.workflow_steps]
        payload["validation_readiness"] = self.validation_readiness.to_dict()
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
        reference_region_found=_has_reference_region(config_paths),
        outputs_found=bool(report_paths),
        report_count=len(report_paths),
        latest_report_path=str(latest_report_path) if latest_report_path else None,
        latest_report_preview=_read_report_preview(latest_report_path),
        latest_report_counts=_read_report_counts(latest_report_path),
        latest_scorecard=_read_scorecard(latest_report_path),
        review_images_path=str(review_images_path) if review_images_path else None,
        report_history=_build_report_history(site_dir, report_paths, review_images_path),
    )


def _find_config_paths(site_dir: Path) -> list[Path]:
    configs_dir = site_dir / "configs"
    if not configs_dir.exists():
        return []
    return sorted(path for path in configs_dir.glob("*.json") if path.is_file())


def _has_reference_region(config_paths: list[Path]) -> bool:
    """Return whether any site config declares a watched reference region."""

    for config_path in config_paths:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(config, dict) and isinstance(config.get("reference_region"), dict):
            return True
    return False


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
    site_dir: Path,
    report_paths: list[Path],
    review_images_path: Path | None,
) -> list[dict[str, Any]]:
    runs_dir = site_dir / "outputs" / "runs"
    run_history = _read_saved_run_history(runs_dir)
    if run_history:
        return run_history

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
                "status": "legacy",
                "legacy": True,
            }
        )
    return sorted(history, key=lambda entry: str(entry.get("modified_time") or ""), reverse=True)


def _read_saved_run_history(runs_dir: Path) -> list[dict[str, Any]]:
    if not runs_dir.is_dir():
        return []
    history: list[dict[str, Any]] = []
    run_dirs = sorted(
        (path for path in runs_dir.iterdir() if path.is_dir()),
        key=str,
        reverse=True,
    )
    for run_dir in run_dirs:
        metadata_path = run_dir / "run-metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(metadata, dict):
            continue
        report_path = Path(str(metadata.get("report_path", run_dir / "validation-report.md")))
        history.append(
            {
                "run_id": metadata.get("run_id", run_dir.name),
                "path": str(report_path),
                "modified_time": metadata.get("created_at"),
                "status": metadata.get("status", "unknown"),
                "counts": _read_report_counts(report_path),
                "evidence_path": metadata.get("review_images_path"),
                "legacy": False,
            }
        )
    return sorted(history, key=lambda entry: str(entry.get("modified_time") or ""), reverse=True)


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

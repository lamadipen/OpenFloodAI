"""Run local validation for all videos in one site folder."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from openfloodai.contracts import read_jsonl_records
from openfloodai.contracts.local_store import JsonObject
from openfloodai.ingestion.evidence_sampling import SamplingSettings
from openfloodai.pipeline import LocalPocSmokeError, run_local_video_review
from openfloodai.review import (
    LabelComparison,
    compare_label_records,
    load_human_label_records,
    render_label_comparison_report,
)

VIDEO_SUFFIXES = {".avi", ".mkv", ".mov", ".mp4"}


class ValidationRunnerError(ValueError):
    """Raised when a site validation run cannot be configured."""


@dataclass(frozen=True)
class SiteValidationResult:
    """Validation result for one video or expected label."""

    video_id: str
    video_filename: str
    processed: bool
    comparisons: list[LabelComparison]
    output_dir: str | None

    @property
    def human_label(self) -> str:
        """Return a short label summary for this video."""

        return _comparison_field_summary(
            (comparison.human_label for comparison in self.comparisons),
            fallback="missing",
        )

    @property
    def system_result(self) -> str:
        """Return a short system-result summary for this video."""

        return _comparison_field_summary(
            (comparison.system_result for comparison in self.comparisons),
            fallback="missing_system_output",
        )

    @property
    def result(self) -> str:
        """Return a conservative video-level result summary."""

        results = {comparison.result for comparison in self.comparisons}
        if "disagree" in results:
            return "disagree"
        if "cannot_compare" in results:
            return "cannot_compare"
        if results == {"agree"}:
            return "agree"
        return "cannot_compare"

    @property
    def note(self) -> str:
        """Return a short note summary for this video."""

        if not self.comparisons:
            return "No comparison was available for this video."
        if len(self.comparisons) == 1:
            return self.comparisons[0].note
        return (
            f"{len(self.comparisons)} label windows were compared. "
            "See the per-window results below."
        )


@dataclass(frozen=True)
class SiteValidationReport:
    """Combined local validation report for one site."""

    site_name: str
    site_dir: str
    output_path: str
    results: list[SiteValidationResult]
    processed_count: int
    failed_count: int
    label_window_count: int
    agree_count: int
    disagree_count: int
    cannot_compare_count: int


def run_site_validation(
    site_dir: Path,
    *,
    config_path: Path | None = None,
    sampling: SamplingSettings | None = None,
) -> SiteValidationReport:
    """Run local validation for all videos in one site folder."""

    if not site_dir.exists() or not site_dir.is_dir():
        raise ValidationRunnerError(f"Site folder does not exist: {site_dir}")

    videos = _find_videos(site_dir)
    labels = _load_site_labels(site_dir)
    labels_by_video_id = _labels_by_video_id(labels)
    selected_config_path = config_path or _find_config_path(site_dir, required=bool(videos))
    outputs_dir = site_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    results: list[SiteValidationResult] = []
    seen_video_ids: set[str] = set()

    for video_path in videos:
        video_id = video_path.stem
        seen_video_ids.add(video_id)
        results.append(
            _run_one_video(
                video_path=video_path,
                video_id=video_id,
                site_dir=site_dir,
                config_path=selected_config_path,
                labels=labels,
                sampling=sampling,
            )
        )

    for video_id in sorted(set(labels_by_video_id) - seen_video_ids):
        results.append(
            SiteValidationResult(
                video_id=video_id,
                video_filename="missing",
                processed=False,
                comparisons=[
                    LabelComparison(
                        video_id=video_id,
                        human_label=_text(label.get("human_label"), fallback="unknown"),
                        system_result="missing_video",
                        result="cannot_compare",
                        note="A human label exists, but no matching local video file was found.",
                        time_window_seconds=_label_time_window_seconds(label),
                    )
                    for label in labels_by_video_id[video_id]
                ],
                output_dir=None,
            )
        )

    report_path = outputs_dir / "validation-report.md"
    report = _build_report(
        site_dir=site_dir,
        output_path=report_path,
        results=sorted(results, key=lambda result: result.video_id),
    )
    report_path.write_text(render_site_validation_report(report), encoding="utf-8")
    return report


def render_site_validation_report(report: SiteValidationReport) -> str:
    """Render a combined site validation report as simple Markdown."""

    lines = [
        "# Site Validation Report",
        "",
        f"Validation Site: {report.site_name}",
        "",
        "## Counts",
        f"- Videos processed: {report.processed_count}",
        f"- Videos failed or missing: {report.failed_count}",
        f"- Label windows compared: {report.label_window_count}",
        f"- Agree: {report.agree_count}",
        f"- Disagree: {report.disagree_count}",
        f"- Cannot compare: {report.cannot_compare_count}",
        "",
        "## Summary Table",
    ]

    if not report.results:
        lines.append("- No videos or labels were found.")
    else:
        lines.extend(
            [
                "| Video | Processed | Human label | System result | Result | Windows | Note |",
                "| --- | --- | --- | --- | --- | ---: | --- |",
            ]
        )
        for result in report.results:
            lines.append(
                "| "
                f"{_table_cell(result.video_filename)} | "
                f"{'yes' if result.processed else 'no'} | "
                f"{_table_cell(result.human_label)} | "
                f"{_table_cell(result.system_result)} | "
                f"{_table_cell(result.result)} | "
                f"{len(result.comparisons)} | "
                f"{_table_cell(result.note)} |"
            )

    lines.extend(["", "## Detailed Results"])

    for result in report.results:
        lines.extend(
            [
                "",
                f"### {result.video_id}",
                f"- Video: {result.video_filename}",
                f"- Processed: {'yes' if result.processed else 'no'}",
                f"- Human label: {result.human_label}",
                f"- System result: {result.system_result}",
                f"- Result: {result.result}",
                f"- Note: {result.note}",
                f"- Label windows compared: {len(result.comparisons)}",
            ]
        )
        if result.output_dir is not None:
            lines.append(f"- Output folder: {result.output_dir}")
        if result.comparisons:
            lines.append("- Per-window comparisons:")
            for index, comparison in enumerate(result.comparisons, start=1):
                lines.extend(
                    [
                        f"  - Window {index}:",
                        f"    - Human label: {comparison.human_label}",
                        f"    - System result: {comparison.system_result}",
                        f"    - Result: {comparison.result}",
                        f"    - Time window: {_time_window_text(comparison.time_window_seconds)}",
                        f"    - Note: {comparison.note}",
                    ]
                )

    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "This report is local validation evidence only.",
            "It does not prove flood detection accuracy, send alerts, upload files, "
            "or create public warnings.",
            "Cases marked `cannot_compare` are not counted as success.",
        ]
    )
    return "\n".join(lines) + "\n"


def _run_one_video(
    *,
    video_path: Path,
    video_id: str,
    site_dir: Path,
    config_path: Path,
    labels: list[JsonObject],
    sampling: SamplingSettings | None,
) -> SiteValidationResult:
    output_dir = site_dir / "outputs" / video_id

    try:
        review_result = run_local_video_review(
            video_path=video_path,
            config_path=config_path,
            output_dir=output_dir,
            image_prefix=video_id,
            time_windows=[
                window
                for label in labels
                if label.get("video_id") == video_id
                and (window := _label_time_window_seconds(label)) is not None
            ]
            or None,
            sampling=sampling,
        )
    except (LocalPocSmokeError, OSError, ValueError) as error:
        return SiteValidationResult(
            video_id=video_id,
            video_filename=video_path.name,
            processed=False,
            comparisons=[
                LabelComparison(
                    video_id=video_id,
                    human_label=_first_label_text(labels, video_id),
                    system_result="processing_failed",
                    result="cannot_compare",
                    note=f"Video could not be processed: {error}",
                    time_window_seconds=_label_time_window_seconds(_first_label(labels, video_id)),
                )
            ],
            output_dir=str(output_dir),
        )

    records = read_jsonl_records(Path(review_result.records_path))
    comparison_report = compare_label_records(
        system_records=records,
        human_labels=labels,
        video_id=video_id,
    )
    comparison_path = output_dir / "label-comparison.md"
    comparison_path.write_text(
        render_label_comparison_report(comparison_report),
        encoding="utf-8",
    )

    return SiteValidationResult(
        video_id=video_id,
        video_filename=video_path.name,
        processed=True,
        comparisons=comparison_report.comparisons,
        output_dir=str(output_dir),
    )


def _build_report(
    *,
    site_dir: Path,
    output_path: Path,
    results: list[SiteValidationResult],
) -> SiteValidationReport:
    return SiteValidationReport(
        site_name=site_dir.name,
        site_dir=str(site_dir),
        output_path=str(output_path),
        results=results,
        processed_count=sum(result.processed for result in results),
        failed_count=sum(not result.processed for result in results),
        label_window_count=sum(len(result.comparisons) for result in results),
        agree_count=sum(
            comparison.result == "agree" for result in results for comparison in result.comparisons
        ),
        disagree_count=sum(
            comparison.result == "disagree"
            for result in results
            for comparison in result.comparisons
        ),
        cannot_compare_count=sum(
            comparison.result == "cannot_compare"
            for result in results
            for comparison in result.comparisons
        ),
    )


def _find_videos(site_dir: Path) -> list[Path]:
    videos_dir = site_dir / "inputs" / "videos"
    if not videos_dir.exists():
        return []

    return sorted(
        path
        for path in videos_dir.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
    )


def _find_config_path(site_dir: Path, *, required: bool) -> Path:
    configs_dir = site_dir / "configs"
    config_paths = sorted(configs_dir.glob("*.json")) if configs_dir.exists() else []
    if config_paths:
        return config_paths[0]
    if required:
        raise ValidationRunnerError(f"No site config JSON file found under: {configs_dir}")
    return configs_dir / "site-config.json"


def _load_site_labels(site_dir: Path) -> list[JsonObject]:
    labels_dir = site_dir / "labels"
    if not labels_dir.exists():
        return []

    labels: list[JsonObject] = []
    for label_path in sorted(labels_dir.glob("*.jsonl")):
        labels.extend(load_human_label_records(label_path))
    return labels


def _labels_by_video_id(
    labels: Iterable[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    labels_by_video: dict[str, list[Mapping[str, object]]] = {}
    for label in labels:
        video_id = _text(label.get("video_id"))
        if video_id:
            labels_by_video.setdefault(video_id, []).append(label)
    return labels_by_video


def _first_label_text(labels: list[JsonObject], video_id: str) -> str:
    label = _first_label(labels, video_id)
    if label is not None:
        return _text(label.get("human_label"), fallback="unknown")
    return "missing"


def _first_label(labels: list[JsonObject], video_id: str) -> JsonObject | None:
    for label in labels:
        if _text(label.get("video_id")) == video_id:
            return label
    return None


def _label_time_window_seconds(label: Mapping[str, object] | None) -> tuple[float, float] | None:
    if label is None:
        return None
    value = label.get("time_window_seconds")
    if not isinstance(value, list) or len(value) != 2:
        return None

    start, end = value
    if not _is_number(start) or not _is_number(end):
        return None

    start_second = float(start)
    end_second = float(end)
    if start_second < 0 or end_second <= start_second:
        return None
    return (start_second, end_second)


def _time_window_text(time_window_seconds: tuple[float, float] | None) -> str:
    if time_window_seconds is None:
        return "missing"
    start_second, end_second = time_window_seconds
    return f"{start_second:g}s to {end_second:g}s"


def _comparison_field_summary(values: Iterable[str], *, fallback: str) -> str:
    unique_values = sorted({value for value in values if value})
    if not unique_values:
        return fallback
    if len(unique_values) == 1:
        return unique_values[0]
    return "multiple"


def _table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _text(value: object, *, fallback: str = "") -> str:
    if isinstance(value, str) and value:
        return value
    return fallback


def _is_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float)

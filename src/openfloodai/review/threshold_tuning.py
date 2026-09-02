"""Prototype threshold tuning for local human-label comparison."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from openfloodai.contracts import read_jsonl_records
from openfloodai.review.human_labels import load_human_label_records
from openfloodai.review.label_comparison import compare_label_records

DEFAULT_CANDIDATE_THRESHOLDS = (0.02, 0.05, 0.1, 0.2)


class ThresholdTuningError(ValueError):
    """Raised when threshold tuning input is invalid."""


@dataclass(frozen=True)
class ThresholdTuningResult:
    """Comparison counts for one candidate threshold."""

    threshold: float
    agree_count: int
    disagree_count: int
    cannot_compare_count: int
    compared_count: int


@dataclass(frozen=True)
class ThresholdTuningReport:
    """Prototype tuning report for one video."""

    video_id: str
    results: list[ThresholdTuningResult]
    note: str


def tune_threshold_records(
    *,
    system_records: Iterable[Mapping[str, object]],
    human_labels: Iterable[Mapping[str, object]],
    video_id: str,
    candidate_thresholds: Sequence[float] = DEFAULT_CANDIDATE_THRESHOLDS,
) -> ThresholdTuningReport:
    """Try candidate visual-change thresholds against human labels."""

    if not video_id.strip():
        raise ThresholdTuningError("video_id must be a non-empty string")

    thresholds = _validate_candidate_thresholds(candidate_thresholds)
    system_records_list = list(system_records)
    human_labels_list = list(human_labels)

    results: list[ThresholdTuningResult] = []
    for threshold in thresholds:
        comparison_report = compare_label_records(
            system_records=system_records_list,
            human_labels=human_labels_list,
            video_id=video_id,
            change_signal_threshold=threshold,
        )
        compared_count = comparison_report.agree_count + comparison_report.disagree_count
        results.append(
            ThresholdTuningResult(
                threshold=threshold,
                agree_count=comparison_report.agree_count,
                disagree_count=comparison_report.disagree_count,
                cannot_compare_count=comparison_report.cannot_compare_count,
                compared_count=compared_count,
            )
        )

    return ThresholdTuningReport(
        video_id=video_id,
        results=results,
        note=(
            "Prototype threshold tuning only. Cannot-compare cases stay separate and "
            "are not counted as success."
        ),
    )


def tune_threshold_files(
    *,
    system_records_path: Path,
    human_labels_path: Path,
    video_id: str,
    candidate_thresholds: Sequence[float] = DEFAULT_CANDIDATE_THRESHOLDS,
) -> ThresholdTuningReport:
    """Read local files and tune candidate visual-change thresholds."""

    system_records = read_jsonl_records(system_records_path)
    human_labels = load_human_label_records(human_labels_path)
    return tune_threshold_records(
        system_records=system_records,
        human_labels=human_labels,
        video_id=video_id,
        candidate_thresholds=candidate_thresholds,
    )


def render_threshold_tuning_report(report: ThresholdTuningReport) -> str:
    """Render a threshold tuning report as simple Markdown."""

    lines = [
        "# Threshold Tuning Report",
        "",
        f"Video: {report.video_id}",
        "",
        "| Threshold | Agree | Disagree | Cannot Compare | Compared |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]

    for result in report.results:
        lines.append(
            "| "
            f"{result.threshold:.3f} | "
            f"{result.agree_count} | "
            f"{result.disagree_count} | "
            f"{result.cannot_compare_count} | "
            f"{result.compared_count} |"
        )

    lines.extend(
        [
            "",
            f"Note: {report.note}",
            "",
            "This report does not prove flood detection accuracy or create public warnings.",
        ]
    )
    return "\n".join(lines) + "\n"


def _validate_candidate_thresholds(candidate_thresholds: Sequence[float]) -> list[float]:
    if not candidate_thresholds:
        raise ThresholdTuningError("At least one candidate threshold is required")

    thresholds: list[float] = []
    for threshold in candidate_thresholds:
        if isinstance(threshold, bool) or not isinstance(threshold, int | float):
            raise ThresholdTuningError("Candidate thresholds must be numbers")
        threshold_value = float(threshold)
        if not 0.0 <= threshold_value <= 1.0:
            raise ThresholdTuningError("Candidate thresholds must be between 0.0 and 1.0")
        thresholds.append(threshold_value)

    return thresholds

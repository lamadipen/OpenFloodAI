"""Compare human labels with local OpenFloodAI POC output records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from openfloodai.contracts import read_jsonl_records
from openfloodai.review.human_labels import load_human_label_records

CHANGE_SIGNAL_THRESHOLD = 0.05
VISUAL_CHANGE_FIELDS = (
    "region_change_score",
    "frame_change_score",
    "risk_signal_score",
    "water_coverage_score",
)
CHANGE_LABELS = {"water_rising", "water_falling"}
NO_CHANGE_LABELS = {"no_clear_change"}
UNCLEAR_LABELS = {"camera_video_problem", "cannot_judge"}


class LabelComparisonError(ValueError):
    """Raised when label comparison inputs are invalid."""


@dataclass(frozen=True)
class LabelComparison:
    """One comparison between a human label and system output."""

    video_id: str
    human_label: str
    system_result: str
    result: str
    note: str


@dataclass(frozen=True)
class LabelComparisonReport:
    """Local report comparing human labels with system output."""

    video_id: str
    comparisons: list[LabelComparison]
    agree_count: int
    disagree_count: int
    cannot_compare_count: int


def compare_label_records(
    *,
    system_records: Iterable[Mapping[str, object]],
    human_labels: Iterable[Mapping[str, object]],
    video_id: str,
    change_signal_threshold: float = CHANGE_SIGNAL_THRESHOLD,
) -> LabelComparisonReport:
    """Compare system output records against human labels for one video."""

    if not video_id.strip():
        raise LabelComparisonError("video_id must be a non-empty string")
    if not 0.0 <= change_signal_threshold <= 1.0:
        raise LabelComparisonError("change_signal_threshold must be between 0.0 and 1.0")

    labels_for_video = [label for label in human_labels if _text(label.get("video_id")) == video_id]
    system_records_for_video = _system_records_for_video(system_records, video_id)
    system_result = _system_result(system_records_for_video, change_signal_threshold)

    if not labels_for_video:
        comparisons = [
            LabelComparison(
                video_id=video_id,
                human_label="missing",
                system_result=system_result,
                result="cannot_compare",
                note="No human label was found for this video.",
            )
        ]
    elif system_result == "missing_system_output":
        comparisons = [
            LabelComparison(
                video_id=video_id,
                human_label=_text(label.get("human_label"), fallback="unknown"),
                system_result=system_result,
                result="cannot_compare",
                note="No visual signal or risk-state output was found to compare.",
            )
            for label in labels_for_video
        ]
    else:
        comparisons = [
            _compare_one_label(
                label,
                video_id=video_id,
                system_result=system_result,
            )
            for label in labels_for_video
        ]

    return LabelComparisonReport(
        video_id=video_id,
        comparisons=comparisons,
        agree_count=sum(comparison.result == "agree" for comparison in comparisons),
        disagree_count=sum(comparison.result == "disagree" for comparison in comparisons),
        cannot_compare_count=sum(
            comparison.result == "cannot_compare" for comparison in comparisons
        ),
    )


def compare_label_files(
    *,
    system_records_path: Path,
    human_labels_path: Path,
    video_id: str,
    change_signal_threshold: float = CHANGE_SIGNAL_THRESHOLD,
) -> LabelComparisonReport:
    """Read local files and compare system output against human labels."""

    system_records = read_jsonl_records(system_records_path)
    human_labels = load_human_label_records(human_labels_path)
    return compare_label_records(
        system_records=system_records,
        human_labels=human_labels,
        video_id=video_id,
        change_signal_threshold=change_signal_threshold,
    )


def render_label_comparison_report(report: LabelComparisonReport) -> str:
    """Render a label comparison report in simple Markdown."""

    lines = [
        "# Human Label Comparison",
        "",
        f"Video: {report.video_id}",
        "",
        "## Result Counts",
        f"- Agree: {report.agree_count}",
        f"- Disagree: {report.disagree_count}",
        f"- Cannot compare: {report.cannot_compare_count}",
        "",
        "## Comparisons",
    ]

    for comparison in report.comparisons:
        lines.extend(
            [
                "",
                f"Video: {comparison.video_id}",
                f"Human label: {comparison.human_label}",
                f"System result: {comparison.system_result}",
                f"Result: {comparison.result}",
                f"Note: {comparison.note}",
            ]
        )

    lines.extend(
        [
            "",
            "This report is local validation evidence only.",
            "It does not prove flood detection accuracy or create a public warning.",
        ]
    )
    return "\n".join(lines) + "\n"


def _compare_one_label(
    label: Mapping[str, object],
    *,
    video_id: str,
    system_result: str,
) -> LabelComparison:
    human_label = _text(label.get("human_label"), fallback="unknown")

    if human_label in UNCLEAR_LABELS or system_result == "cannot_judge":
        return LabelComparison(
            video_id=video_id,
            human_label=human_label,
            system_result=system_result,
            result="cannot_compare",
            note="The human label or system output says this case is unclear.",
        )

    if human_label in CHANGE_LABELS and system_result == "water_change_seen":
        return LabelComparison(
            video_id=video_id,
            human_label=human_label,
            system_result=system_result,
            result="agree",
            note=(
                "The human saw water change, and the system measured visual change. "
                "The current simple signal does not know direction yet."
            ),
        )

    if human_label in NO_CHANGE_LABELS and system_result == "no_clear_change":
        return LabelComparison(
            video_id=video_id,
            human_label=human_label,
            system_result=system_result,
            result="agree",
            note="The human saw no clear change, and the system change signal stayed low.",
        )

    return LabelComparison(
        video_id=video_id,
        human_label=human_label,
        system_result=system_result,
        result="disagree",
        note="The human label and system visual-change result do not match.",
    )


def _system_result(
    system_records: Iterable[Mapping[str, object]],
    change_signal_threshold: float,
) -> str:
    has_system_output = False
    highest_change_score = 0.0

    for record in system_records:
        record_type = _text(record.get("record_type"))
        if record_type in {"visual_signal_output", "risk_state_output"}:
            has_system_output = True

        risk_state = _text(record.get("risk_state")).upper()
        if risk_state in {"UNKNOWN", "UNKNOWN_DEGRADED"}:
            return "cannot_judge"

        if record_type == "visual_signal_output":
            highest_change_score = max(highest_change_score, _highest_change_score(record))

    if not has_system_output:
        return "missing_system_output"
    if highest_change_score >= change_signal_threshold:
        return "water_change_seen"
    return "no_clear_change"


def _system_records_for_video(
    system_records: Iterable[Mapping[str, object]],
    video_id: str,
) -> list[Mapping[str, object]]:
    records = list(system_records)
    scoped_records = [record for record in records if _text(record.get("video_id"))]
    matching_records = [
        record for record in scoped_records if _text(record.get("video_id")) == video_id
    ]

    if matching_records:
        return matching_records
    if scoped_records:
        return []

    return records


def _highest_change_score(record: Mapping[str, object]) -> float:
    scores: list[float] = []
    for field_name in VISUAL_CHANGE_FIELDS:
        score = _score_value(record.get(field_name))
        if score is not None:
            scores.append(score)
    if not scores:
        return 0.0
    return max(scores)


def _score_value(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _text(value: object, *, fallback: str = "") -> str:
    if isinstance(value, str):
        return value.strip()
    return fallback

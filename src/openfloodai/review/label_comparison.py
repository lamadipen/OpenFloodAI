"""Compare human labels with local OpenFloodAI POC output records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from openfloodai.contracts import read_jsonl_records
from openfloodai.ingestion.evidence_sampling import SamplingSettings, window_evidence
from openfloodai.review.human_labels import load_human_label_records

CHANGE_SIGNAL_THRESHOLD = 0.05
SAFE_WATER_LEVEL_EVIDENCE_STATE = "useful_water_level_evidence"
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
    time_window_seconds: tuple[float, float] | None = None


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

    if not labels_for_video:
        comparisons = [
            LabelComparison(
                video_id=video_id,
                human_label="missing",
                system_result=_system_result(system_records_for_video, change_signal_threshold),
                result="cannot_compare",
                note="No human label was found for this video.",
            )
        ]
    else:
        comparisons = [
            _compare_one_label_window(
                label,
                video_id=video_id,
                system_records=system_records_for_video,
                change_signal_threshold=change_signal_threshold,
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
                f"Time window: {_time_window_text(comparison.time_window_seconds)}",
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


def _compare_one_label_window(
    label: Mapping[str, object],
    *,
    video_id: str,
    system_records: list[Mapping[str, object]],
    change_signal_threshold: float,
) -> LabelComparison:
    time_window = _time_window_seconds(label)
    human_label = _text(label.get("human_label"), fallback="unknown")

    if time_window is None:
        return LabelComparison(
            video_id=video_id,
            human_label=human_label,
            system_result="missing_system_output",
            result="cannot_compare",
            note="The human label time window is missing or invalid.",
            time_window_seconds=None,
        )

    evidence_records = [
        r for r in system_records if r.get("record_type") == "evidence_window_output"
    ]
    coverage_note = ""
    if evidence_records:
        interval = evidence_records[0].get("sample_interval_seconds", 5.0)
        settings = SamplingSettings(
            interval_seconds=float(interval) if isinstance(interval, int | float) else 5.0
        )
        metadata = [r for r in system_records if r.get("record_type") == "video_frame_metadata"]
        coverage = window_evidence(metadata, time_window, settings)
        coverage_note = (
            f" Usable frames: {coverage['usable_frame_count']}; "
            f"unusable frames: {coverage['unusable_frame_count']}; "
            f"reasons: {coverage['unusable_reasons']}; "
            f"usable range: {coverage['first_usable_second']}s to "
            f"{coverage['last_usable_second']}s."
        )
        if coverage["coverage_sufficient"] is not True:
            return LabelComparison(
                video_id=video_id,
                human_label=human_label,
                system_result="cannot_judge",
                result="cannot_compare",
                note=str(coverage["coverage_reason"]) + coverage_note,
                time_window_seconds=time_window,
            )

    matching_records = _system_records_in_time_window(system_records, time_window)
    system_result = _system_result(matching_records, change_signal_threshold)
    if system_result == "missing_system_output":
        return LabelComparison(
            video_id=video_id,
            human_label=human_label,
            system_result=system_result,
            result="cannot_compare",
            note=(
                "No matching visual signal or risk-state output was found for "
                f"{_time_window_text(time_window)}."
            ),
            time_window_seconds=time_window,
        )

    comparison = _compare_one_label(
        label,
        video_id=video_id,
        system_result=system_result,
        time_window_seconds=time_window,
    )
    return replace(comparison, note=comparison.note + coverage_note)


def _compare_one_label(
    label: Mapping[str, object],
    *,
    video_id: str,
    system_result: str,
    time_window_seconds: tuple[float, float] | None,
) -> LabelComparison:
    human_label = _text(label.get("human_label"), fallback="unknown")

    if human_label in UNCLEAR_LABELS or system_result == "cannot_judge":
        return LabelComparison(
            video_id=video_id,
            human_label=human_label,
            system_result=system_result,
            result="cannot_compare",
            note="The human label or system output says this case is unclear.",
            time_window_seconds=time_window_seconds,
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
            time_window_seconds=time_window_seconds,
        )

    if human_label in NO_CHANGE_LABELS and system_result == "no_clear_change":
        return LabelComparison(
            video_id=video_id,
            human_label=human_label,
            system_result=system_result,
            result="agree",
            note="The human saw no clear change, and the system change signal stayed low.",
            time_window_seconds=time_window_seconds,
        )

    return LabelComparison(
        video_id=video_id,
        human_label=human_label,
        system_result=system_result,
        result="disagree",
        note="The human label and system visual-change result do not match.",
        time_window_seconds=time_window_seconds,
    )


def _system_result(
    system_records: Iterable[Mapping[str, object]],
    change_signal_threshold: float,
) -> str:
    has_system_output = False
    has_unsafe_region_evidence = False
    has_safe_region_evidence = False
    highest_change_score = 0.0

    for record in system_records:
        record_type = _text(record.get("record_type"))
        if record.get("coverage_sufficient") is False:
            continue
        if record_type in {"visual_signal_output", "risk_state_output"}:
            has_system_output = True
        risk_state = _text(record.get("risk_state")).upper()
        if risk_state in {"UNKNOWN", "UNKNOWN_DEGRADED"}:
            return "cannot_judge"

        if record_type == "visual_signal_output":
            evidence_state = record.get("water_level_evidence_state")
            if evidence_state is not None:
                if evidence_state == SAFE_WATER_LEVEL_EVIDENCE_STATE:
                    has_safe_region_evidence = True
                else:
                    has_unsafe_region_evidence = True
            highest_change_score = max(highest_change_score, _highest_change_score(record))

    if not has_system_output:
        return "missing_system_output"
    if has_unsafe_region_evidence and not has_safe_region_evidence:
        return "cannot_judge"
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


def _system_records_in_time_window(
    system_records: Iterable[Mapping[str, object]],
    time_window_seconds: tuple[float, float],
) -> list[Mapping[str, object]]:
    records = list(system_records)
    base_timestamp = _base_timestamp(records)
    record_ids_in_window = {
        _text(record.get("record_id"))
        for record in records
        if _record_time_is_in_window(record, time_window_seconds, base_timestamp)
        and _text(record.get("record_id"))
    }

    matching = []
    start, end = time_window_seconds
    for record in records:
        if "comparison_start_seconds" in record or "comparison_end_seconds" in record:
            before = _score_value(record.get("comparison_start_seconds"))
            after = _score_value(record.get("comparison_end_seconds"))
            # Explicit pair bounds take priority over timestamps and source-ID fallback.
            if before is not None and after is not None and start <= before < after < end:
                matching.append(record)
        elif _record_time_is_in_window(
            record, time_window_seconds, base_timestamp
        ) or _source_records_overlap_window(record, record_ids_in_window):
            matching.append(record)
    return matching


def _record_time_is_in_window(
    record: Mapping[str, object],
    time_window_seconds: tuple[float, float],
    base_timestamp: datetime | None,
) -> bool:
    record_second = _record_video_second(record, base_timestamp)
    if record_second is None:
        return False

    start_second, end_second = time_window_seconds
    return start_second <= record_second < end_second


def _source_records_overlap_window(
    record: Mapping[str, object],
    record_ids_in_window: set[str],
) -> bool:
    source_record_ids = record.get("source_record_ids")
    if not isinstance(source_record_ids, list):
        return False
    return any(
        _text(source_record_id) in record_ids_in_window for source_record_id in source_record_ids
    )


def _record_video_second(
    record: Mapping[str, object],
    base_timestamp: datetime | None,
) -> float | None:
    for field_name in ("video_time_seconds", "time_offset_seconds", "relative_time_seconds"):
        score = _score_value(record.get(field_name))
        if score is not None:
            return score

    if base_timestamp is None:
        return None

    timestamp = _parse_timestamp(_text(record.get("timestamp")))
    if timestamp is None:
        return None

    return (timestamp - base_timestamp).total_seconds()


def _base_timestamp(records: Iterable[Mapping[str, object]]) -> datetime | None:
    timestamps = [
        timestamp
        for record in records
        if (timestamp := _parse_timestamp(_text(record.get("timestamp")))) is not None
    ]
    if not timestamps:
        return None
    return min(timestamps)


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _time_window_seconds(label: Mapping[str, object]) -> tuple[float, float] | None:
    value = label.get("time_window_seconds")
    if not isinstance(value, list) or len(value) != 2:
        return None

    start, end = value
    if _score_value(start) is None or _score_value(end) is None:
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

"""Readable local summary reports for POC JSON Lines records."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from openfloodai.contracts import InvalidRecordError, InvalidRecordPathError, read_jsonl_records
from openfloodai.contracts.local_store import JsonObject

VISUAL_SIGNAL_FIELDS = (
    "brightness_score",
    "sharpness_score",
    "frame_change_score",
    "water_coverage_score",
    "risk_signal_score",
)


class ReplaySummaryError(ValueError):
    """Raised when a local replay summary cannot be created."""


@dataclass(frozen=True)
class ReplaySummary:
    """Safe summary of records from one local POC run."""

    total_records: int
    record_type_counts: dict[str, int]
    risk_state_counts: dict[str, int]
    unknown_or_degraded_records: int
    first_timestamp: str | None
    last_timestamp: str | None
    highest_visual_signals: dict[str, float]
    notes: list[str]


def summarize_jsonl_records(path: Path) -> ReplaySummary:
    """Read a local JSON Lines file and produce a safe summary."""

    try:
        records = read_jsonl_records(path)
    except (FileNotFoundError, InvalidRecordError, InvalidRecordPathError) as error:
        raise ReplaySummaryError(f"Could not summarize JSONL records: {error}") from error

    record_type_counts: Counter[str] = Counter()
    risk_state_counts: Counter[str] = Counter()
    timestamps: list[str] = []
    highest_visual_signals: dict[str, float] = {}
    unknown_or_degraded_records = 0

    for record in records:
        record_type = _safe_text(record.get("record_type"), fallback="unknown_record_type")
        record_type_counts[record_type] += 1

        risk_state = _safe_text(record.get("risk_state"), fallback="")
        if risk_state:
            risk_state_counts[risk_state] += 1

        timestamp = _safe_text(record.get("timestamp"), fallback="")
        if timestamp:
            timestamps.append(timestamp)

        if _is_unknown_or_degraded(record):
            unknown_or_degraded_records += 1

        if record_type == "visual_signal_output":
            _update_highest_visual_signals(record, highest_visual_signals)

    return ReplaySummary(
        total_records=len(records),
        record_type_counts=dict(sorted(record_type_counts.items())),
        risk_state_counts=dict(sorted(risk_state_counts.items())),
        unknown_or_degraded_records=unknown_or_degraded_records,
        first_timestamp=timestamps[0] if timestamps else None,
        last_timestamp=timestamps[-1] if timestamps else None,
        highest_visual_signals=dict(sorted(highest_visual_signals.items())),
        notes=_build_notes(
            total_records=len(records),
            record_type_counts=record_type_counts,
            risk_state_counts=risk_state_counts,
            unknown_or_degraded_records=unknown_or_degraded_records,
        ),
    )


def render_summary_markdown(summary: ReplaySummary) -> str:
    """Render a replay summary as simple Markdown for local review."""

    lines = [
        "# POC Summary",
        "",
        f"Records: {summary.total_records}",
        "",
        "## Record Types",
    ]

    if summary.record_type_counts:
        lines.extend(
            f"- {record_type}: {count}" for record_type, count in summary.record_type_counts.items()
        )
    else:
        lines.append("- None")

    lines.extend(["", "## Risk States"])
    if summary.risk_state_counts:
        lines.extend(
            f"- {risk_state}: {count}" for risk_state, count in summary.risk_state_counts.items()
        )
    else:
        lines.append("- None found")

    lines.extend(
        [
            "",
            "## Health And Time",
            f"- Unknown or degraded records: {summary.unknown_or_degraded_records}",
            f"- First timestamp: {summary.first_timestamp or 'Not found'}",
            f"- Last timestamp: {summary.last_timestamp or 'Not found'}",
            "",
            "## Highest Visual Signals",
        ]
    )

    if summary.highest_visual_signals:
        lines.extend(
            f"- {field_name}: {value:.3f}"
            for field_name, value in summary.highest_visual_signals.items()
        )
    else:
        lines.append("- None found")

    lines.extend(["", "## Plain Notes"])
    lines.extend(f"- {note}" for note in summary.notes)

    return "\n".join(lines) + "\n"


def _safe_text(value: object, *, fallback: str) -> str:
    if isinstance(value, str):
        return value
    return fallback


def _is_unknown_or_degraded(record: JsonObject) -> bool:
    state_fields = (
        "input_quality_state",
        "risk_state",
        "pipeline_state",
        "health_state",
    )

    for field_name in state_fields:
        value = record.get(field_name)
        if isinstance(value, str) and value.upper() in {"UNKNOWN", "DEGRADED"}:
            return True

    reason_codes = record.get("reason_codes")
    if isinstance(reason_codes, list):
        return any(
            isinstance(reason_code, str)
            and ("UNKNOWN" in reason_code.upper() or "DEGRADED" in reason_code.upper())
            for reason_code in reason_codes
        )

    return False


def _update_highest_visual_signals(
    record: JsonObject,
    highest_visual_signals: dict[str, float],
) -> None:
    for field_name in VISUAL_SIGNAL_FIELDS:
        value = record.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue

        numeric_value = float(value)
        current_highest = highest_visual_signals.get(field_name)
        if current_highest is None or numeric_value > current_highest:
            highest_visual_signals[field_name] = numeric_value


def _build_notes(
    *,
    total_records: int,
    record_type_counts: Counter[str],
    risk_state_counts: Counter[str],
    unknown_or_degraded_records: int,
) -> list[str]:
    notes: list[str] = []

    if total_records == 0:
        notes.append("No records were found in this file.")
    else:
        notes.append("The report summarized saved local records only.")

    if record_type_counts.get("visual_signal_output", 0) > 0:
        notes.append("The run produced visual signal records for review.")
    else:
        notes.append("No visual signal records were found.")

    if risk_state_counts:
        risk_states = ", ".join(sorted(risk_state_counts))
        notes.append(f"Risk states found in this run: {risk_states}.")
    else:
        notes.append("No risk-state records were found.")

    if unknown_or_degraded_records > 0:
        notes.append("One or more records were unknown or degraded and should be reviewed.")
    else:
        notes.append("No unknown or degraded records were found.")

    notes.append("No public warning was created by this report.")
    return notes

"""Evaluate riverbank-crossing evidence against human-reviewed pilot samples."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import TypedDict

from openfloodai.contracts import read_jsonl_records

RIVERBANK_PLUGIN_ID = "riverbank_crossing_v1"
EXPECTED_RESULTS = frozenset({"change", "no_change", "unclear"})
OVERLAY_REVIEWS = frozenset({"accepted", "rejected", "not_reviewed"})
PILOT_CONDITIONS = (
    "clear_water",
    "muddy_water",
    "glare",
    "shadows",
    "vegetation",
    "snow",
    "low_light",
    "camera_movement",
    "spring",
    "summer",
    "autumn",
    "winter",
    "high_water",
    "low_water",
)
FALSE_CROSSING_CAUSES = frozenset(
    {"camera_movement", "non_water_change", "glare", "shadows", "vegetation", "other"}
)


class RiverbankPilotError(ValueError):
    """Raised when pilot observations or evidence cannot be evaluated safely."""


class _ValidatedObservation(TypedDict):
    observation_id: str
    evidence_record_id: str
    expected_result: str
    conditions: tuple[str, ...]
    overlay_review: str
    false_crossing_cause: str | None


@dataclass(frozen=True)
class ConfusionMetrics:
    """Binary change/no-change counts and rates for evaluable samples."""

    sample_count: int
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    precision: float | None
    recall: float | None
    false_crossing_rate: float | None


@dataclass(frozen=True)
class ConditionMetrics:
    """Metrics for one environmental or scene-condition slice."""

    condition: str
    reviewed_count: int
    available_count: int
    metrics: ConfusionMetrics


@dataclass(frozen=True)
class ProcessingCostSummary:
    """Observed adapter cost fields from available evidence records."""

    timing_sample_count: int
    mean_processing_time_ms: float | None
    p95_processing_time_ms: float | None
    memory_sample_count: int
    mean_estimated_frame_memory_bytes: float | None
    max_estimated_frame_memory_bytes: int | None


@dataclass(frozen=True)
class PilotSampleResult:
    """One matched human review and adapter outcome."""

    observation_id: str
    evidence_record_id: str
    expected_result: str
    system_result: str
    outcome: str
    evidence_status: str
    conditions: tuple[str, ...]
    overlay_review: str
    false_crossing_cause: str | None


@dataclass(frozen=True)
class RiverbankPilotReport:
    """Aggregate pilot metrics with condition slices and traceable samples."""

    plugin_id: str
    reviewed_count: int
    matched_count: int
    available_count: int
    unavailable_or_failure_count: int
    unavailable_or_failure_rate: float | None
    unclear_count: int
    metrics: ConfusionMetrics
    false_crossing_causes: Mapping[str, int]
    overlay_accepted_count: int
    overlay_rejected_count: int
    overlay_acceptance_rate: float | None
    processing_cost: ProcessingCostSummary
    condition_metrics: tuple[ConditionMetrics, ...]
    samples: tuple[PilotSampleResult, ...]


def evaluate_riverbank_pilot(
    *,
    evidence_records: Iterable[Mapping[str, object]],
    reviewed_observations: Iterable[Mapping[str, object]],
) -> RiverbankPilotReport:
    """Compare saved riverbank evidence with independent human reviews."""

    evidence_by_id = _index_evidence(evidence_records)
    observations = list(reviewed_observations)
    if not observations:
        raise RiverbankPilotError("At least one human-reviewed pilot observation is required.")

    samples: list[PilotSampleResult] = []
    evidence_used: list[Mapping[str, object]] = []
    seen_observation_ids: set[str] = set()
    for index, observation in enumerate(observations, start=1):
        clean = _validate_observation(observation, index=index)
        if clean["observation_id"] in seen_observation_ids:
            raise RiverbankPilotError(
                f"Observation {index}: duplicate observation_id {clean['observation_id']!r}."
            )
        seen_observation_ids.add(clean["observation_id"])

        evidence = evidence_by_id.get(clean["evidence_record_id"])
        if evidence is not None:
            evidence_used.append(evidence)
        samples.append(_evaluate_sample(clean, evidence))

    available_samples = [sample for sample in samples if sample.evidence_status == "available"]
    unavailable_count = len(samples) - len(available_samples)
    evaluable_samples = [
        sample for sample in available_samples if sample.expected_result in {"change", "no_change"}
    ]
    metrics = _confusion_metrics(evaluable_samples)
    accepted_count = sum(sample.overlay_review == "accepted" for sample in samples)
    rejected_count = sum(sample.overlay_review == "rejected" for sample in samples)
    reviewed_overlay_count = accepted_count + rejected_count
    false_crossing_causes = Counter(
        sample.false_crossing_cause or "unspecified"
        for sample in samples
        if sample.outcome == "false_positive"
    )

    return RiverbankPilotReport(
        plugin_id=RIVERBANK_PLUGIN_ID,
        reviewed_count=len(samples),
        matched_count=sum(sample.evidence_status != "missing" for sample in samples),
        available_count=len(available_samples),
        unavailable_or_failure_count=unavailable_count,
        unavailable_or_failure_rate=_ratio(unavailable_count, len(samples)),
        unclear_count=sum(sample.expected_result == "unclear" for sample in samples),
        metrics=metrics,
        false_crossing_causes=dict(sorted(false_crossing_causes.items())),
        overlay_accepted_count=accepted_count,
        overlay_rejected_count=rejected_count,
        overlay_acceptance_rate=_ratio(accepted_count, reviewed_overlay_count),
        processing_cost=_processing_cost(evidence_used),
        condition_metrics=tuple(
            _condition_metrics(condition, samples) for condition in PILOT_CONDITIONS
        ),
        samples=tuple(samples),
    )


def evaluate_riverbank_pilot_files(
    *, evidence_path: Path, reviewed_observations_path: Path
) -> RiverbankPilotReport:
    """Load two local JSONL files and evaluate the riverbank pilot."""

    try:
        evidence_records = read_jsonl_records(evidence_path)
        observations = read_jsonl_records(reviewed_observations_path)
    except ValueError as error:
        raise RiverbankPilotError(f"Could not read pilot JSONL input: {error}") from error
    return evaluate_riverbank_pilot(
        evidence_records=evidence_records,
        reviewed_observations=observations,
    )


def render_riverbank_pilot_report(report: RiverbankPilotReport) -> str:
    """Render pilot metrics in plain, safety-conscious Markdown."""

    metrics = report.metrics
    cost = report.processing_cost
    lines = [
        "# Riverbank-Crossing Pilot Evaluation",
        "",
        (
            "This is local visual-evidence evaluation. It does not confirm flooding, "
            "prove safety, or create a public warning."
        ),
        "",
        "## Coverage",
        "",
        f"- Human-reviewed observations: {report.reviewed_count}",
        f"- Matched evidence records: {report.matched_count}",
        f"- Available measurements: {report.available_count}",
        (
            "- Unavailable, failed, invalid, disabled, or missing: "
            f"{report.unavailable_or_failure_count}"
        ),
        f"- Unavailable/failure rate: {_percent(report.unavailable_or_failure_rate)}",
        f"- Human reviews marked unclear: {report.unclear_count}",
        "",
        "## Change / No-Change Metrics",
        "",
        f"- Evaluable observations: {metrics.sample_count}",
        f"- Precision: {_percent(metrics.precision)}",
        f"- Recall: {_percent(metrics.recall)}",
        f"- False crossings: {metrics.false_positive}",
        f"- False-crossing rate: {_percent(metrics.false_crossing_rate)}",
        (
            f"- Counts: TP={metrics.true_positive}, FP={metrics.false_positive}, "
            f"FN={metrics.false_negative}, TN={metrics.true_negative}"
        ),
        "",
        (
            "Precision asks: when the adapter showed a crossing, how often did the "
            "reviewer also mark change?"
        ),
        "Recall asks: when the reviewer marked change, how often did the adapter show a crossing?",
        "Unclear and unavailable observations are not silently counted as correct.",
        "",
        "## False-Crossing Causes",
        "",
    ]
    if report.false_crossing_causes:
        lines.extend(f"- {cause}: {count}" for cause, count in report.false_crossing_causes.items())
    else:
        lines.append(
            "- No false crossings were recorded in this sample. This does not prove there are none."
        )

    lines.extend(
        [
            "",
            "## Overlay Review",
            "",
            f"- Accepted by reviewer: {report.overlay_accepted_count}",
            f"- Rejected by reviewer: {report.overlay_rejected_count}",
            f"- Acceptance rate: {_percent(report.overlay_acceptance_rate)}",
            "",
            "## Processing Cost",
            "",
            f"- Timing samples: {cost.timing_sample_count}",
            f"- Mean processing time: {_milliseconds(cost.mean_processing_time_ms)}",
            f"- P95 processing time: {_milliseconds(cost.p95_processing_time_ms)}",
            f"- Memory samples: {cost.memory_sample_count}",
            f"- Mean input-frame memory: {_mebibytes(cost.mean_estimated_frame_memory_bytes)}",
            f"- Maximum input-frame memory: {_mebibytes(cost.max_estimated_frame_memory_bytes)}",
            "",
            (
                "Memory is the baseline and current image-array footprint only. It is a "
                "repeatable lower-bound estimate, not peak process memory."
            ),
            "",
            "## Condition Slices",
            "",
            "| Condition | Reviewed | Available | Precision | Recall | False crossings |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for condition in report.condition_metrics:
        lines.append(
            "| "
            f"{condition.condition} | {condition.reviewed_count} | {condition.available_count} | "
            f"{_percent(condition.metrics.precision)} | {_percent(condition.metrics.recall)} | "
            f"{condition.metrics.false_positive} |"
        )

    lines.extend(
        [
            "",
            "A condition with zero reviewed samples is **not tested**, not successful.",
            (
                "Results from a small or single-site pilot must not be generalized to "
                "other rivers, cameras, seasons, or weather."
            ),
            "Human review and independent evidence remain required before any safety decision.",
        ]
    )
    return "\n".join(lines) + "\n"


def _index_evidence(
    evidence_records: Iterable[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    indexed: dict[str, Mapping[str, object]] = {}
    for record in evidence_records:
        if record.get("plugin_id") != RIVERBANK_PLUGIN_ID:
            continue
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or not record_id.strip():
            raise RiverbankPilotError("Riverbank evidence record is missing a valid record_id.")
        if record_id in indexed:
            raise RiverbankPilotError(f"Duplicate riverbank evidence record_id {record_id!r}.")
        indexed[record_id] = record
    return indexed


def _validate_observation(record: Mapping[str, object], *, index: int) -> _ValidatedObservation:
    required = {
        "observation_id",
        "evidence_record_id",
        "expected_result",
        "conditions",
        "overlay_review",
    }
    optional = {"false_crossing_cause", "note"}
    unknown = sorted(set(record) - required - optional)
    missing = sorted(required - set(record))
    if missing:
        raise RiverbankPilotError(f"Observation {index}: missing fields: {', '.join(missing)}.")
    if unknown:
        raise RiverbankPilotError(f"Observation {index}: unsupported fields: {', '.join(unknown)}.")

    observation_id = _required_text(record["observation_id"], "observation_id", index)
    evidence_record_id = _required_text(record["evidence_record_id"], "evidence_record_id", index)
    expected_result = _required_text(record["expected_result"], "expected_result", index)
    if expected_result not in EXPECTED_RESULTS:
        raise RiverbankPilotError(
            f"Observation {index}: expected_result must be one of {sorted(EXPECTED_RESULTS)}."
        )
    overlay_review = _required_text(record["overlay_review"], "overlay_review", index)
    if overlay_review not in OVERLAY_REVIEWS:
        raise RiverbankPilotError(
            f"Observation {index}: overlay_review must be one of {sorted(OVERLAY_REVIEWS)}."
        )

    conditions_value = record["conditions"]
    if not isinstance(conditions_value, list) or not conditions_value:
        raise RiverbankPilotError(f"Observation {index}: conditions must be a non-empty list.")
    conditions: list[str] = []
    for condition in conditions_value:
        if not isinstance(condition, str) or condition not in PILOT_CONDITIONS:
            raise RiverbankPilotError(
                f"Observation {index}: every condition must be one of {list(PILOT_CONDITIONS)}."
            )
        if condition not in conditions:
            conditions.append(condition)

    false_crossing_cause = record.get("false_crossing_cause")
    if false_crossing_cause is not None:
        if (
            not isinstance(false_crossing_cause, str)
            or false_crossing_cause not in FALSE_CROSSING_CAUSES
        ):
            raise RiverbankPilotError(
                f"Observation {index}: false_crossing_cause must be one of "
                f"{sorted(FALSE_CROSSING_CAUSES)}."
            )

    note = record.get("note")
    if note is not None and (not isinstance(note, str) or not note.strip()):
        raise RiverbankPilotError(f"Observation {index}: note must be a non-empty string.")

    return {
        "observation_id": observation_id,
        "evidence_record_id": evidence_record_id,
        "expected_result": expected_result,
        "conditions": tuple(conditions),
        "overlay_review": overlay_review,
        "false_crossing_cause": false_crossing_cause,
    }


def _evaluate_sample(
    observation: _ValidatedObservation, evidence: Mapping[str, object] | None
) -> PilotSampleResult:
    expected = str(observation["expected_result"])
    evidence_status = "missing" if evidence is None else str(evidence.get("status", "invalid"))
    system_result = "unavailable"
    outcome = "cannot_compare"
    if evidence_status == "available" and evidence is not None:
        value = evidence.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise RiverbankPilotError(
                f"Evidence {observation['evidence_record_id']!r} has an invalid available value."
            )
        system_result = "change" if float(value) > 0.0 else "no_change"
        if expected == "change" and system_result == "change":
            outcome = "true_positive"
        elif expected == "change":
            outcome = "false_negative"
        elif expected == "no_change" and system_result == "change":
            outcome = "false_positive"
        elif expected == "no_change":
            outcome = "true_negative"

    return PilotSampleResult(
        observation_id=str(observation["observation_id"]),
        evidence_record_id=str(observation["evidence_record_id"]),
        expected_result=expected,
        system_result=system_result,
        outcome=outcome,
        evidence_status=evidence_status,
        conditions=observation["conditions"],
        overlay_review=str(observation["overlay_review"]),
        false_crossing_cause=(
            str(observation["false_crossing_cause"])
            if observation.get("false_crossing_cause") is not None
            else None
        ),
    )


def _confusion_metrics(samples: Iterable[PilotSampleResult]) -> ConfusionMetrics:
    sample_list = list(samples)
    outcomes = Counter(sample.outcome for sample in sample_list)
    true_positive = outcomes["true_positive"]
    false_positive = outcomes["false_positive"]
    false_negative = outcomes["false_negative"]
    true_negative = outcomes["true_negative"]
    return ConfusionMetrics(
        sample_count=len(sample_list),
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        true_negative=true_negative,
        precision=_ratio(true_positive, true_positive + false_positive),
        recall=_ratio(true_positive, true_positive + false_negative),
        false_crossing_rate=_ratio(false_positive, false_positive + true_negative),
    )


def _condition_metrics(condition: str, samples: list[PilotSampleResult]) -> ConditionMetrics:
    reviewed = [sample for sample in samples if condition in sample.conditions]
    available = [sample for sample in reviewed if sample.evidence_status == "available"]
    evaluable = [
        sample for sample in available if sample.expected_result in {"change", "no_change"}
    ]
    return ConditionMetrics(
        condition=condition,
        reviewed_count=len(reviewed),
        available_count=len(available),
        metrics=_confusion_metrics(evaluable),
    )


def _processing_cost(records: Iterable[Mapping[str, object]]) -> ProcessingCostSummary:
    times: list[float] = []
    memory_values: list[int] = []
    for record in records:
        quality = record.get("quality")
        if not isinstance(quality, Mapping):
            continue
        processing_time = quality.get("processing_time_ms")
        if (
            not isinstance(processing_time, bool)
            and isinstance(processing_time, int | float)
            and math.isfinite(processing_time)
            and processing_time >= 0
        ):
            times.append(float(processing_time))
        memory = quality.get("estimated_frame_memory_bytes")
        if not isinstance(memory, bool) and isinstance(memory, int) and memory >= 0:
            memory_values.append(memory)

    return ProcessingCostSummary(
        timing_sample_count=len(times),
        mean_processing_time_ms=mean(times) if times else None,
        p95_processing_time_ms=_percentile_95(times),
        memory_sample_count=len(memory_values),
        mean_estimated_frame_memory_bytes=mean(memory_values) if memory_values else None,
        max_estimated_frame_memory_bytes=max(memory_values) if memory_values else None,
    )


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _required_text(value: object, field_name: str, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RiverbankPilotError(f"Observation {index}: {field_name} must be non-empty text.")
    return value.strip()


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percent(value: float | None) -> str:
    return "Not available" if value is None else f"{value * 100:.1f}%"


def _milliseconds(value: float | None) -> str:
    return "Not measured" if value is None else f"{value:.3f} ms"


def _mebibytes(value: float | int | None) -> str:
    return "Not measured" if value is None else f"{value / (1024 * 1024):.3f} MiB"

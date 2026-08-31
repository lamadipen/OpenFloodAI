"""Rule-based risk-state skeleton for test signals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


class RiskEvaluationError(ValueError):
    """Raised when risk evaluation input is not usable."""


@dataclass(frozen=True)
class RiskThresholds:
    """Simple thresholds for the first rule-based risk evaluator."""

    watch_threshold: float = 0.5
    warning_candidate_threshold: float = 0.8

    def __post_init__(self) -> None:
        if not 0.0 <= self.watch_threshold < self.warning_candidate_threshold <= 1.0:
            raise RiskEvaluationError(
                "Thresholds must satisfy 0.0 <= watch_threshold "
                "< warning_candidate_threshold <= 1.0"
            )


def evaluate_risk_state(
    health_record: Mapping[str, object],
    visual_signal_record: Mapping[str, object],
    thresholds: RiskThresholds | None = None,
) -> dict[str, object]:
    """Evaluate a simple risk-state result from health and visual signal records."""

    active_thresholds = thresholds or RiskThresholds()
    site_id = _string_field("site_id", health_record, visual_signal_record)
    camera_id = _string_field("camera_id", health_record, visual_signal_record)
    timestamp = _timestamp_field(health_record, visual_signal_record)

    if not _health_is_ok(health_record):
        return _build_result(
            site_id=site_id,
            camera_id=camera_id,
            timestamp=timestamp,
            risk_state="UNKNOWN",
            reason_codes=_health_reason_codes(health_record),
            confidence=0.0,
            human_summary="Camera or feed health is not OK, so risk cannot be judged.",
        )

    signal_score = _visual_signal_score(visual_signal_record)
    if signal_score >= active_thresholds.warning_candidate_threshold:
        return _build_result(
            site_id=site_id,
            camera_id=camera_id,
            timestamp=timestamp,
            risk_state="WARNING_CANDIDATE",
            reason_codes=["WARNING_CANDIDATE_SIGNAL", "HUMAN_REVIEW_NEEDED"],
            confidence=signal_score,
            human_summary=(
                "Test visual signal crossed the warning-candidate threshold. "
                "Human review is needed before any public warning."
            ),
        )

    if signal_score >= active_thresholds.watch_threshold:
        return _build_result(
            site_id=site_id,
            camera_id=camera_id,
            timestamp=timestamp,
            risk_state="WATCH",
            reason_codes=["WATCH_SIGNAL"],
            confidence=signal_score,
            human_summary="Test visual signal crossed the watch threshold. Keep reviewing.",
        )

    return _build_result(
        site_id=site_id,
        camera_id=camera_id,
        timestamp=timestamp,
        risk_state="NORMAL",
        reason_codes=["NORMAL_TEST_SIGNAL"],
        confidence=1.0 - signal_score,
        human_summary="Camera/feed health is OK and test visual signals are below thresholds.",
    )


def _build_result(
    *,
    site_id: str,
    camera_id: str,
    timestamp: str,
    risk_state: str,
    reason_codes: list[str],
    confidence: float,
    human_summary: str,
) -> dict[str, object]:
    return {
        "contract_version": "v1",
        "record_id": f"risk-state-{uuid4()}",
        "record_type": "risk_state_output",
        "site_id": site_id,
        "camera_id": camera_id,
        "timestamp": timestamp,
        "risk_state": risk_state,
        "reason_codes": reason_codes,
        "confidence": _clamp_confidence(confidence),
        "human_summary": human_summary,
    }


def _health_is_ok(health_record: Mapping[str, object]) -> bool:
    health_values = [
        health_record.get("health_state"),
        health_record.get("camera_health_state"),
        health_record.get("feed_health_state"),
        health_record.get("camera_status"),
        health_record.get("feed_status"),
        health_record.get("input_quality_state"),
    ]
    normalized_values = {
        str(value).strip().upper()
        for value in health_values
        if isinstance(value, str) and value.strip()
    }

    if normalized_values & {"BROKEN", "OFFLINE", "FAILED", "DEGRADED", "UNKNOWN"}:
        return False

    return bool(normalized_values & {"OK", "USABLE", "HEALTHY", "ACTIVE"})


def _health_reason_codes(health_record: Mapping[str, object]) -> list[str]:
    reason_codes = health_record.get("reason_codes")
    if isinstance(reason_codes, list) and all(isinstance(code, str) for code in reason_codes):
        return [*reason_codes, "RISK_UNKNOWN_DUE_TO_HEALTH"]

    return ["INPUT_UNKNOWN", "RISK_UNKNOWN_DUE_TO_HEALTH"]


def _visual_signal_score(visual_signal_record: Mapping[str, object]) -> float:
    score_fields = [
        "water_coverage_ratio",
        "water_level_score",
        "frame_change_score",
        "change_score",
        "risk_signal_score",
    ]
    scores = [
        _score_field(field_name, visual_signal_record[field_name])
        for field_name in score_fields
        if field_name in visual_signal_record
    ]
    if not scores:
        raise RiskEvaluationError("Visual signal record must include at least one numeric score")

    return max(scores)


def _score_field(field_name: str, value: object) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise RiskEvaluationError(f"{field_name} must be a number between 0.0 and 1.0")

    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise RiskEvaluationError(f"{field_name} must be between 0.0 and 1.0")

    return score


def _string_field(
    field_name: str,
    primary_record: Mapping[str, object],
    secondary_record: Mapping[str, object],
) -> str:
    for record in (primary_record, secondary_record):
        value = record.get(field_name)
        if isinstance(value, str) and value:
            return value

    raise RiskEvaluationError(f"{field_name} is required")


def _timestamp_field(
    primary_record: Mapping[str, object],
    secondary_record: Mapping[str, object],
) -> str:
    for record in (secondary_record, primary_record):
        value = record.get("timestamp")
        if isinstance(value, str) and value:
            return value

    return datetime.now(tz=UTC).isoformat()


def _clamp_confidence(confidence: float) -> float:
    return min(max(confidence, 0.0), 1.0)

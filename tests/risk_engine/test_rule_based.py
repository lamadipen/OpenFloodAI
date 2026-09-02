from __future__ import annotations

from typing import cast

import pytest

from openfloodai.risk_engine import RiskEvaluationError, RiskThresholds, evaluate_risk_state


def health_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "contract_version": "v1",
        "record_id": "health-001",
        "record_type": "camera_health_output",
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "timestamp": "2026-08-30T12:00:00+00:00",
        "health_state": "OK",
        "input_quality_state": "USABLE",
    }
    record.update(overrides)
    return record


def visual_signal_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "contract_version": "v1",
        "record_id": "signal-001",
        "record_type": "visual_signal_output",
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "timestamp": "2026-08-30T12:00:05+00:00",
        "water_coverage_ratio": 0.2,
        "frame_change_score": 0.1,
    }
    record.update(overrides)
    return record


def test_broken_health_produces_unknown_risk() -> None:
    result = evaluate_risk_state(
        health_record(health_state="BROKEN", reason_codes=["CAMERA_OFFLINE"]),
        visual_signal_record(water_coverage_ratio=0.1),
    )

    assert result["record_type"] == "risk_state_output"
    assert result["risk_state"] == "UNKNOWN"
    assert result["confidence"] == 0.0
    assert result["reason_codes"] == ["CAMERA_OFFLINE", "DEGRADED_EVIDENCE_USED"]
    assert "not OK" in str(result["human_summary"])


def test_unknown_input_health_produces_unknown_not_normal() -> None:
    result = evaluate_risk_state(
        health_record(input_quality_state="UNKNOWN"),
        visual_signal_record(water_coverage_ratio=0.1),
    )

    assert result["risk_state"] == "UNKNOWN"


def test_normal_visual_signals_produce_normal_risk() -> None:
    result = evaluate_risk_state(
        health_record(),
        visual_signal_record(water_coverage_ratio=0.2, frame_change_score=0.1),
    )

    assert result["contract_version"] == "v1"
    assert result["site_id"] == "site-demo-01"
    assert result["camera_id"] == "camera-demo-01"
    assert result["timestamp"] == "2026-08-30T12:00:00+00:00"
    assert result["risk_state"] == "NORMAL"
    assert result["reason_codes"] == ["NORMAL_CONDITIONS"]
    confidence = cast(float, result["confidence"])
    assert 0.0 <= confidence <= 1.0


def test_elevated_visual_signal_produces_watch() -> None:
    result = evaluate_risk_state(
        health_record(),
        visual_signal_record(water_coverage_ratio=0.55),
    )

    assert result["risk_state"] == "WATCH"
    assert result["reason_codes"] == ["ELEVATED_WATER_EVIDENCE"]
    assert result["confidence"] == 0.55


def test_stronger_visual_signal_produces_warning_candidate() -> None:
    result = evaluate_risk_state(
        health_record(),
        visual_signal_record(water_coverage_ratio=0.82),
    )

    assert result["risk_state"] == "WARNING_CANDIDATE"
    assert result["reason_codes"] == ["HIGH_WATER_COVERAGE", "HUMAN_REVIEW_NEEDED"]
    assert result["confidence"] == 0.82
    assert "Human review" in str(result["human_summary"])


def test_high_frame_change_can_drive_warning_candidate() -> None:
    result = evaluate_risk_state(
        health_record(),
        visual_signal_record(water_coverage_ratio=0.2, frame_change_score=0.9),
    )

    assert result["risk_state"] == "WARNING_CANDIDATE"


def test_custom_thresholds_are_explicit() -> None:
    result = evaluate_risk_state(
        health_record(),
        visual_signal_record(water_coverage_ratio=0.7),
        thresholds=RiskThresholds(watch_threshold=0.3, warning_candidate_threshold=0.7),
    )

    assert result["risk_state"] == "WARNING_CANDIDATE"


def test_bad_thresholds_fail_clearly() -> None:
    with pytest.raises(RiskEvaluationError, match="Thresholds must satisfy"):
        RiskThresholds(watch_threshold=0.8, warning_candidate_threshold=0.5)


def test_missing_site_id_fails_clearly() -> None:
    bad_health = health_record()
    del bad_health["site_id"]
    bad_visual = visual_signal_record()
    del bad_visual["site_id"]

    with pytest.raises(RiskEvaluationError, match="site_id is required"):
        evaluate_risk_state(bad_health, bad_visual)


def test_missing_visual_scores_fail_clearly() -> None:
    signal_record = visual_signal_record()
    del signal_record["water_coverage_ratio"]
    del signal_record["frame_change_score"]

    with pytest.raises(RiskEvaluationError, match="at least one numeric score"):
        evaluate_risk_state(health_record(), signal_record)


def test_visual_scores_must_be_between_zero_and_one() -> None:
    with pytest.raises(RiskEvaluationError, match="water_coverage_ratio must be between"):
        evaluate_risk_state(health_record(), visual_signal_record(water_coverage_ratio=1.5))

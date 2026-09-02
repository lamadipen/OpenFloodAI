from __future__ import annotations

from typing import cast

import pytest

from openfloodai.risk_engine import RiskEvaluationError
from openfloodai.risk_engine.multi_source import (
    MultiSourceThresholds,
    evaluate_multi_source_risk,
)


def _health(**overrides: object) -> dict[str, object]:
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


def _visual(**overrides: object) -> dict[str, object]:
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


def test_visual_only_produces_base_result() -> None:
    result = evaluate_multi_source_risk(_health(), _visual())
    assert result["record_type"] == "multi_source_risk_output"
    assert result["data_sources_used"] == ["visual"]
    assert result["final_risk_state"] == result["base_risk_state"]


def test_usgs_escalates_to_watch() -> None:
    water = {"gage_height_ft": 7.5, "flood_stage_ft": 10.0}
    result = evaluate_multi_source_risk(_health(), _visual(), water_conditions=water)
    sources = cast(list[str], result["data_sources_used"])
    assert "usgs" in sources
    assert result["final_risk_state"] in {"WATCH", "WARNING_CANDIDATE"}


def test_usgs_escalates_to_warning() -> None:
    water = {"gage_height_ft": 9.5, "flood_stage_ft": 10.0}
    result = evaluate_multi_source_risk(_health(), _visual(), water_conditions=water)
    assert result["final_risk_state"] == "WARNING_CANDIDATE"


def test_usgs_no_escalation_when_low() -> None:
    water = {"gage_height_ft": 3.0, "flood_stage_ft": 10.0}
    result = evaluate_multi_source_risk(_health(), _visual(), water_conditions=water)
    assert result["final_risk_state"] == result["base_risk_state"]


def test_nws_warning_escalates() -> None:
    alerts = {"alert_type": "WARNING", "severity": "SEVERE"}
    result = evaluate_multi_source_risk(_health(), _visual(), flood_alerts=alerts)
    sources = cast(list[str], result["data_sources_used"])
    assert "nws" in sources
    assert result["final_risk_state"] == "WARNING_CANDIDATE"


def test_nws_watch_escalates() -> None:
    alerts = {"alert_type": "FLOOD WATCH", "severity": "MODERATE"}
    result = evaluate_multi_source_risk(_health(), _visual(), flood_alerts=alerts)
    assert result["final_risk_state"] in {"WATCH", "WARNING_CANDIDATE"}


def test_precipitation_escalates() -> None:
    precip = {"precipitation_sum_mm": 60.0}
    result = evaluate_multi_source_risk(_health(), _visual(), precipitation=precip)
    sources = cast(list[str], result["data_sources_used"])
    assert "precipitation" in sources
    assert result["final_risk_state"] in {"WATCH", "WARNING_CANDIDATE"}


def test_all_sources_combined() -> None:
    water = {"gage_height_ft": 9.0, "flood_stage_ft": 10.0}
    alerts = {"alert_type": "FLOOD WARNING", "severity": "SEVERE"}
    precip = {"precipitation_sum_mm": 55.0}
    result = evaluate_multi_source_risk(
        _health(),
        _visual(),
        water_conditions=water,
        flood_alerts=alerts,
        precipitation=precip,
    )
    sources = cast(list[str], result["data_sources_used"])
    assert set(sources) == {"visual", "usgs", "nws", "precipitation"}
    assert result["final_risk_state"] == "WARNING_CANDIDATE"


def test_never_deescalates() -> None:
    visual = _visual(water_coverage_ratio=0.6, frame_change_score=0.5)
    water = {"gage_height_ft": 2.0, "flood_stage_ft": 10.0}
    result = evaluate_multi_source_risk(_health(), visual, water_conditions=water)
    base_state = result["base_risk_state"]
    final_state = result["final_risk_state"]
    from openfloodai.risk_engine.multi_source import _level

    assert _level(str(final_state)) >= _level(str(base_state))


def test_none_sources_skipped() -> None:
    result = evaluate_multi_source_risk(
        _health(),
        _visual(),
        water_conditions=None,
        flood_alerts=None,
        precipitation=None,
    )
    assert result["data_sources_used"] == ["visual"]


def test_custom_thresholds() -> None:
    thresholds = MultiSourceThresholds(
        gauge_watch_ratio=0.5,
        gauge_warning_ratio=0.8,
    )
    water = {"gage_height_ft": 5.5, "flood_stage_ft": 10.0}
    result = evaluate_multi_source_risk(
        _health(), _visual(), water_conditions=water, thresholds=thresholds
    )
    assert result["final_risk_state"] in {"WATCH", "WARNING_CANDIDATE"}


def test_invalid_gauge_ratios() -> None:
    with pytest.raises(RiskEvaluationError, match="Gauge ratios"):
        MultiSourceThresholds(gauge_watch_ratio=0.9, gauge_warning_ratio=0.7)


def test_invalid_precipitation_thresholds() -> None:
    with pytest.raises(RiskEvaluationError, match="Precipitation thresholds"):
        MultiSourceThresholds(precipitation_watch_mm=50.0, precipitation_warning_mm=25.0)


def test_output_has_required_fields() -> None:
    result = evaluate_multi_source_risk(_health(), _visual())
    assert "contract_version" in result
    assert "record_id" in result
    assert "base_risk_state" in result
    assert "base_confidence" in result
    assert "escalation_reasons" in result
    assert "source_signals" in result

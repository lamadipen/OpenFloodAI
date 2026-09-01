from __future__ import annotations

from openfloodai.data_sources.open_meteo import assess_precipitation_risk


def test_low_risk() -> None:
    result = assess_precipitation_risk(recent_mm=2.0, forecast_mm=3.0)
    assert result["precipitation_risk_state"] == "LOW"
    assert result["combined_mm"] == 5.0
    assert result["risk_factor"] == 0.05


def test_moderate_risk() -> None:
    result = assess_precipitation_risk(recent_mm=6.0, forecast_mm=8.0)
    assert result["precipitation_risk_state"] == "MODERATE"
    assert result["combined_mm"] == 14.0


def test_high_risk() -> None:
    result = assess_precipitation_risk(recent_mm=15.0, forecast_mm=15.0)
    assert result["precipitation_risk_state"] == "HIGH"
    assert result["combined_mm"] == 30.0


def test_extreme_risk() -> None:
    result = assess_precipitation_risk(recent_mm=30.0, forecast_mm=25.0)
    assert result["precipitation_risk_state"] == "EXTREME"
    assert result["combined_mm"] == 55.0


def test_zero_precipitation() -> None:
    result = assess_precipitation_risk(recent_mm=0.0, forecast_mm=0.0)
    assert result["precipitation_risk_state"] == "LOW"
    assert result["risk_factor"] == 0.0


def test_risk_factor_caps_at_one() -> None:
    result = assess_precipitation_risk(recent_mm=80.0, forecast_mm=80.0)
    assert result["risk_factor"] == 1.0


def test_boundary_moderate() -> None:
    result = assess_precipitation_risk(recent_mm=10.0, forecast_mm=0.0)
    assert result["precipitation_risk_state"] == "MODERATE"


def test_boundary_high() -> None:
    result = assess_precipitation_risk(recent_mm=25.0, forecast_mm=0.0)
    assert result["precipitation_risk_state"] == "HIGH"


def test_boundary_extreme() -> None:
    result = assess_precipitation_risk(recent_mm=50.0, forecast_mm=0.0)
    assert result["precipitation_risk_state"] == "EXTREME"

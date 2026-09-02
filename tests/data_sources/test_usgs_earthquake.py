from __future__ import annotations

import pytest

from openfloodai.data_sources.usgs_earthquake import (
    _haversine_km,
    _risk_factor_from_magnitude,
    _risk_state_from_magnitude,
    assess_seismic_flood_risk,
)


def _eq(
    magnitude: float = 5.5,
    place: str = "10km NW of test",
    depth_km: float = 10.0,
    distance_km: float = 50.0,
) -> dict[str, object]:
    return {
        "magnitude": magnitude,
        "place": place,
        "depth_km": depth_km,
        "distance_km": distance_km,
    }


def test_no_earthquakes() -> None:
    result = assess_seismic_flood_risk([])
    assert result["seismic_risk_state"] == "NONE"
    assert result["earthquake_count"] == 0
    assert result["risk_factor"] == 0.0
    assert result["strongest_event"] is None


def test_low_risk_magnitude() -> None:
    result = assess_seismic_flood_risk([_eq(magnitude=4.2)])
    assert result["seismic_risk_state"] == "LOW"
    assert result["earthquake_count"] == 1
    assert result["max_magnitude"] == 4.2


def test_moderate_risk_magnitude() -> None:
    result = assess_seismic_flood_risk([_eq(magnitude=5.5)])
    assert result["seismic_risk_state"] == "MODERATE"
    assert result["max_magnitude"] == 5.5


def test_high_risk_magnitude() -> None:
    result = assess_seismic_flood_risk([_eq(magnitude=6.3)])
    assert result["seismic_risk_state"] == "HIGH"


def test_extreme_risk_magnitude() -> None:
    result = assess_seismic_flood_risk([_eq(magnitude=7.8)])
    assert result["seismic_risk_state"] == "EXTREME"
    assert result["max_magnitude"] == 7.8


def test_strongest_event_selected() -> None:
    events = [
        _eq(magnitude=4.5, place="small"),
        _eq(magnitude=6.2, place="big"),
    ]
    result = assess_seismic_flood_risk(events)
    strongest = result["strongest_event"]
    assert isinstance(strongest, dict)
    assert strongest["magnitude"] == 6.2
    assert strongest["place"] == "big"


def test_risk_factor_caps_at_one() -> None:
    result = assess_seismic_flood_risk([_eq(magnitude=9.0)])
    assert result["risk_factor"] == 1.0


def test_risk_factor_zero_below_threshold() -> None:
    assert _risk_factor_from_magnitude(3.9) == 0.0
    assert _risk_factor_from_magnitude(4.0) == 0.0


def test_risk_state_boundaries() -> None:
    assert _risk_state_from_magnitude(3.5) == "NONE"
    assert _risk_state_from_magnitude(4.0) == "LOW"
    assert _risk_state_from_magnitude(5.0) == "MODERATE"
    assert _risk_state_from_magnitude(6.0) == "HIGH"
    assert _risk_state_from_magnitude(7.0) == "EXTREME"


def test_haversine_same_point() -> None:
    assert _haversine_km(27.7, 85.3, 27.7, 85.3) == pytest.approx(0.0, abs=0.01)


def test_haversine_kathmandu_to_pokhara() -> None:
    dist = _haversine_km(27.7172, 85.3240, 28.2096, 83.9856)
    assert 130 < dist < 145

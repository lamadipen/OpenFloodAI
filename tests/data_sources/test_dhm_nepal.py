from __future__ import annotations

from openfloodai.data_sources.dhm_nepal import (
    assess_dhm_flood_risk,
    summarize_bulletin,
)


def _station(
    *,
    name: str = "Chatara",
    river: str = "Koshi",
    water_level: float = 5.0,
    danger_level: float = 8.0,
    warning_level: float = 6.5,
) -> dict[str, object]:
    return {
        "station_name": name,
        "river": river,
        "basin": "Koshi",
        "water_level_m": water_level,
        "danger_level_m": danger_level,
        "warning_level_m": warning_level,
    }


def test_assess_empty() -> None:
    result = assess_dhm_flood_risk([])
    assert result["dhm_risk_state"] == "NONE"
    assert result["stations_total"] == 0
    assert result["risk_factor"] == 0.0


def test_assess_normal() -> None:
    stations = [_station(water_level=4.0, danger_level=8.0, warning_level=6.0)]
    result = assess_dhm_flood_risk(stations)
    assert result["dhm_risk_state"] == "NORMAL"
    assert result["stations_normal"] == 1


def test_assess_warning() -> None:
    stations = [_station(water_level=7.0, danger_level=8.0, warning_level=6.0)]
    result = assess_dhm_flood_risk(stations)
    assert result["dhm_risk_state"] == "WARNING"
    assert result["stations_warning"] == 1


def test_assess_danger() -> None:
    stations = [_station(water_level=9.0, danger_level=8.0, warning_level=6.0)]
    result = assess_dhm_flood_risk(stations)
    assert result["dhm_risk_state"] == "DANGER"
    assert result["stations_danger"] == 1
    risk_factor = result["risk_factor"]
    assert isinstance(risk_factor, float) and risk_factor > 1.0


def test_assess_multiple_stations() -> None:
    stations = [
        _station(name="A", water_level=4.0, danger_level=8.0, warning_level=6.0),
        _station(name="B", water_level=9.0, danger_level=8.0, warning_level=6.0),
        _station(name="C", water_level=7.0, danger_level=8.0, warning_level=6.0),
    ]
    result = assess_dhm_flood_risk(stations)
    assert result["dhm_risk_state"] == "DANGER"
    assert result["stations_danger"] == 1
    assert result["stations_warning"] == 1
    assert result["stations_normal"] == 1
    highest = result["highest_risk_station"]
    assert isinstance(highest, dict)
    assert highest["station_name"] == "B"


def test_summarize_empty() -> None:
    result = summarize_bulletin([])
    assert result["station_count"] == 0
    assert result["bulletin_state"] == "NO_DATA"


def test_summarize_normal() -> None:
    stations = [_station()]
    result = summarize_bulletin(stations)
    assert result["station_count"] == 1
    rivers = result["rivers"]
    assert isinstance(rivers, list) and "Koshi" in rivers
    assert result["bulletin_state"] == "CLEAR"


def test_summarize_danger() -> None:
    stations = [_station(water_level=9.0)]
    result = summarize_bulletin(stations)
    assert result["bulletin_state"] == "DANGER"
    assert result["stations_danger"] == 1


def test_assess_station_without_levels() -> None:
    station: dict[str, object] = {"station_name": "X", "river": "Test", "water_level_m": None}
    result = assess_dhm_flood_risk([station])
    assert result["dhm_risk_state"] == "NORMAL"

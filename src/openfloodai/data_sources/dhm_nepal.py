"""Fetch flood bulletin data from Nepal's Department of Hydrology and Meteorology.

The DHM (https://dhm.gov.np) publishes river water level readings and
flood bulletins for Nepal's major river basins.  This module queries
their publicly accessible bulletin endpoints to bring direct hydrological
observations into the multi-source risk assessment -- critical for
monitoring flood-prone areas like the Koshi, Narayani, Karnali, and
Bagmati river basins.

The DHM bulletin data is JSON-formatted and includes station-level
water levels with danger/warning thresholds set by DHM hydrologists.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from uuid import uuid4

logger = logging.getLogger("openfloodai.data_sources.dhm_nepal")

_BULLETIN_URL = "https://dhm.gov.np/api/floodbulletin"
_STATION_URL = "https://dhm.gov.np/api/station"
_USER_AGENT = "OpenFloodAI/0.1.0 (open-source flood detection; github.com/openfloodai)"


class DHMNepalError(RuntimeError):
    """Raised when DHM Nepal API data cannot be fetched or parsed."""


def fetch_flood_bulletin(
    *,
    timeout: float = 15.0,
) -> list[dict[str, object]]:
    """Fetch the current DHM flood bulletin.

    Returns a list of station-level water level records with their
    danger and warning thresholds.
    """

    data = _fetch_json(_BULLETIN_URL, timeout=timeout)

    items: list[object]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        raw = data.get("data", data.get("stations", data.get("results", [])))
        if isinstance(raw, list):
            items = raw
        else:
            items = [data]
    else:
        raise DHMNepalError("DHM bulletin response is not a JSON array or object")

    records: list[dict[str, object]] = []
    for item in items:
        record = _build_station_record(item)
        if record is not None:
            records.append(record)

    return records


def fetch_station_data(
    station_id: str,
    *,
    timeout: float = 15.0,
) -> dict[str, object] | None:
    """Fetch data for a specific DHM station by ID."""

    if not station_id.strip():
        raise DHMNepalError("station_id must not be empty")

    url = f"{_STATION_URL}/{station_id}"
    data = _fetch_json(url, timeout=timeout)

    if isinstance(data, dict):
        record = _build_station_record(data)
        return record
    return None


def assess_dhm_flood_risk(
    stations: list[dict[str, object]],
) -> dict[str, object]:
    """Assess flood risk from DHM station readings.

    Compares current water levels against DHM-defined danger and warning
    thresholds for each station.
    """

    if not stations:
        return {
            "dhm_risk_state": "NONE",
            "stations_total": 0,
            "stations_danger": 0,
            "stations_warning": 0,
            "stations_normal": 0,
            "risk_factor": 0.0,
            "highest_risk_station": None,
        }

    danger_count = 0
    warning_count = 0
    normal_count = 0
    highest_ratio = 0.0
    highest_station: dict[str, object] | None = None

    for station in stations:
        water_level = _opt_float(station.get("water_level_m"))
        danger_level = _opt_float(station.get("danger_level_m"))
        warning_level = _opt_float(station.get("warning_level_m"))

        if water_level is None:
            continue

        if danger_level is not None and danger_level > 0 and water_level >= danger_level:
            danger_count += 1
            ratio = water_level / danger_level
            if ratio > highest_ratio:
                highest_ratio = ratio
                highest_station = station
        elif warning_level is not None and warning_level > 0 and water_level >= warning_level:
            warning_count += 1
            if danger_level is not None and danger_level > 0:
                ratio = water_level / danger_level
                if ratio > highest_ratio:
                    highest_ratio = ratio
                    highest_station = station
        else:
            normal_count += 1

    if danger_count > 0:
        risk_state = "DANGER"
        risk_factor = min(highest_ratio, 1.5)
    elif warning_count > 0:
        risk_state = "WARNING"
        risk_factor = min(highest_ratio, 1.0) if highest_ratio > 0 else 0.5
    else:
        risk_state = "NORMAL"
        risk_factor = 0.0

    return {
        "dhm_risk_state": risk_state,
        "stations_total": len(stations),
        "stations_danger": danger_count,
        "stations_warning": warning_count,
        "stations_normal": normal_count,
        "risk_factor": round(risk_factor, 4),
        "highest_risk_station": {
            "station_name": highest_station.get("station_name") if highest_station else None,
            "river": highest_station.get("river") if highest_station else None,
            "water_level_m": highest_station.get("water_level_m") if highest_station else None,
            "danger_level_m": highest_station.get("danger_level_m") if highest_station else None,
        },
    }


def summarize_bulletin(
    stations: list[dict[str, object]],
) -> dict[str, object]:
    """Summarize DHM bulletin data for display."""

    if not stations:
        return {
            "station_count": 0,
            "rivers": [],
            "basins": [],
            "bulletin_state": "NO_DATA",
        }

    rivers: set[str] = set()
    basins: set[str] = set()

    for station in stations:
        river = station.get("river")
        if isinstance(river, str) and river:
            rivers.add(river)
        basin = station.get("basin")
        if isinstance(basin, str) and basin:
            basins.add(basin)

    risk = assess_dhm_flood_risk(stations)
    dhm_state = str(risk.get("dhm_risk_state", "NONE"))

    bulletin_state = "CLEAR"
    if dhm_state == "DANGER":
        bulletin_state = "DANGER"
    elif dhm_state == "WARNING":
        bulletin_state = "WARNING"

    return {
        "station_count": len(stations),
        "rivers": sorted(rivers),
        "basins": sorted(basins),
        "bulletin_state": bulletin_state,
        "stations_danger": risk.get("stations_danger", 0),
        "stations_warning": risk.get("stations_warning", 0),
    }


def _fetch_json(url: str, *, timeout: float) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise DHMNepalError(f"DHM API returned HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise DHMNepalError(f"Could not reach DHM API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise DHMNepalError(f"DHM API timed out after {timeout}s") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise DHMNepalError("DHM API returned invalid JSON") from exc


def _build_station_record(item: object) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None

    station_name = _str_field(item, "station_name", "name", "stationName")
    if not station_name:
        return None

    return {
        "contract_version": "v1",
        "record_id": f"dhm-station-{uuid4()}",
        "record_type": "dhm_station_reading",
        "station_id": _str_field(item, "station_id", "id", "stationId") or "",
        "station_name": station_name,
        "river": _str_field(item, "river", "riverName", "river_name") or "",
        "basin": _str_field(item, "basin", "basinName", "basin_name") or "",
        "district": _str_field(item, "district", "districtName") or "",
        "latitude": _opt_float(item.get("latitude") or item.get("lat")),
        "longitude": _opt_float(item.get("longitude") or item.get("lon") or item.get("lng")),
        "water_level_m": _opt_float(
            item.get("water_level_m")
            or item.get("waterLevel")
            or item.get("water_level")
            or item.get("wl")
        ),
        "danger_level_m": _opt_float(
            item.get("danger_level_m")
            or item.get("dangerLevel")
            or item.get("danger_level")
            or item.get("dl")
        ),
        "warning_level_m": _opt_float(
            item.get("warning_level_m") or item.get("warningLevel") or item.get("warning_level")
        ),
        "observation_time": _str_field(item, "observation_time", "time", "dateTime") or "",
    }


def _str_field(data: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None
    return result

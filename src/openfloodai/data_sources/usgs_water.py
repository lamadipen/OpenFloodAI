"""Fetch real-time river gauge data from the USGS Water Services API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

_BASE_URL = "https://waterservices.usgs.gov/nwis/iv/"
_USER_AGENT = "OpenFloodAI/0.1.0 (open-source flood detection; github.com/openfloodai)"

_PARAM_GAGE_HEIGHT = "00065"
_PARAM_DISCHARGE = "00060"
_PARAM_WATER_TEMP = "00010"

_PARAM_FIELD_MAP: dict[str, str] = {
    _PARAM_GAGE_HEIGHT: "gage_height_ft",
    _PARAM_DISCHARGE: "discharge_cfs",
    _PARAM_WATER_TEMP: "water_temp_c",
}


class USGSDataError(RuntimeError):
    """Raised when USGS Water Services data cannot be fetched or parsed."""


def fetch_site_conditions(
    site_number: str,
    *,
    timeout: float = 10.0,
) -> dict[str, object]:
    """Fetch current gage height, discharge, and water temperature for a USGS site."""

    _validate_site_number(site_number)
    param_codes = f"{_PARAM_GAGE_HEIGHT},{_PARAM_DISCHARGE},{_PARAM_WATER_TEMP}"
    params = f"format=json&sites={site_number}&parameterCd={param_codes}&siteStatus=active"
    data = _fetch_json(f"{_BASE_URL}?{params}", timeout=timeout)

    time_series_list = _extract_time_series(data)
    station_name = _extract_station_name(time_series_list)
    now = datetime.now(tz=UTC)

    readings: dict[str, float | None] = {
        "gage_height_ft": None,
        "discharge_cfs": None,
        "water_temp_c": None,
    }
    oldest_reading_time: datetime | None = None

    for ts in time_series_list:
        param_code = _extract_parameter_code(ts)
        field_name = _PARAM_FIELD_MAP.get(param_code)
        if field_name is None:
            continue

        value, reading_time = _extract_latest_value(ts)
        readings[field_name] = value
        if reading_time is not None:
            if oldest_reading_time is None or reading_time < oldest_reading_time:
                oldest_reading_time = reading_time

    data_age_seconds = (now - oldest_reading_time).total_seconds() if oldest_reading_time else None

    return {
        "contract_version": "v1",
        "record_id": f"usgs-conditions-{uuid4()}",
        "record_type": "usgs_water_conditions",
        "site_number": site_number,
        "timestamp": now.isoformat(),
        "station_name": station_name,
        "gage_height_ft": readings["gage_height_ft"],
        "discharge_cfs": readings["discharge_cfs"],
        "water_temp_c": readings["water_temp_c"],
        "data_age_seconds": data_age_seconds,
    }


def fetch_flood_stage(
    site_number: str,
    *,
    timeout: float = 10.0,
) -> dict[str, object]:
    """Fetch flood stage thresholds for a USGS site.

    Flood stages originate from NWS via NWIS. Many sites do not publish
    them, in which case the threshold fields are returned as None.
    """

    _validate_site_number(site_number)
    params = f"format=json&sites={site_number}&parameterCd={_PARAM_GAGE_HEIGHT}&siteStatus=active"
    data = _fetch_json(f"{_BASE_URL}?{params}", timeout=timeout)

    time_series_list = _extract_time_series(data)
    station_name = _extract_station_name(time_series_list)

    action_stage: float | None = None
    flood_stage: float | None = None
    moderate_flood_stage: float | None = None
    major_flood_stage: float | None = None

    for ts in time_series_list:
        param_code = _extract_parameter_code(ts)
        if param_code != _PARAM_GAGE_HEIGHT:
            continue

        variable = ts.get("variable", {})
        properties = variable.get("properties", []) if isinstance(variable, dict) else []
        if not isinstance(properties, list):
            break

        for prop in properties:
            if not isinstance(prop, dict):
                continue
            name = str(prop.get("name", "")).lower()
            raw_value = prop.get("value")
            parsed = _parse_optional_float(raw_value)
            if name == "action stage":
                action_stage = parsed
            elif name == "flood stage":
                flood_stage = parsed
            elif name == "moderate flood stage":
                moderate_flood_stage = parsed
            elif name == "major flood stage":
                major_flood_stage = parsed

    return {
        "contract_version": "v1",
        "record_id": f"usgs-flood-stage-{uuid4()}",
        "record_type": "usgs_flood_stage",
        "site_number": site_number,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "station_name": station_name,
        "action_stage_ft": action_stage,
        "flood_stage_ft": flood_stage,
        "moderate_flood_stage_ft": moderate_flood_stage,
        "major_flood_stage_ft": major_flood_stage,
    }


def compute_flood_proximity(
    gage_height_ft: float,
    flood_stage_ft: float,
) -> dict[str, object]:
    """Compute how close the current gage height is to flood stage."""

    if flood_stage_ft <= 0.0:
        raise USGSDataError("flood_stage_ft must be positive")

    ratio = gage_height_ft / flood_stage_ft

    if ratio >= 1.0:
        state = "ABOVE_FLOOD"
    elif ratio >= 0.95:
        state = "AT_FLOOD"
    elif ratio >= 0.85:
        state = "NEAR_FLOOD"
    elif ratio >= 0.7:
        state = "WATCH"
    else:
        state = "NORMAL"

    return {
        "contract_version": "v1",
        "record_id": f"flood-proximity-{uuid4()}",
        "record_type": "flood_proximity",
        "flood_proximity_ratio": round(ratio, 4),
        "flood_proximity_state": state,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_site_number(site_number: str) -> None:
    if not site_number or not site_number.strip().isdigit():
        raise USGSDataError(f"Invalid USGS site number: {site_number!r}")


def _fetch_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise USGSDataError(f"USGS API returned HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise USGSDataError(f"Could not reach USGS Water Services: {exc.reason}") from exc
    except TimeoutError as exc:
        raise USGSDataError(f"USGS API request timed out after {timeout}s") from exc

    try:
        return json.loads(body)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        raise USGSDataError("USGS API returned invalid JSON") from exc


def _extract_time_series(data: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        ts_list = data["value"]["timeSeries"]
    except (KeyError, TypeError) as exc:
        raise USGSDataError("Unexpected USGS response structure: missing value.timeSeries") from exc

    if not isinstance(ts_list, list):
        raise USGSDataError("Unexpected USGS response structure: timeSeries is not a list")

    return ts_list


def _extract_station_name(time_series_list: list[dict[str, Any]]) -> str:
    for ts in time_series_list:
        source_info = ts.get("sourceInfo")
        if isinstance(source_info, dict):
            name = source_info.get("siteName")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return ""


def _extract_parameter_code(ts: dict[str, Any]) -> str:
    try:
        return str(ts["variable"]["variableCode"][0]["value"])
    except (KeyError, TypeError, IndexError):
        return ""


def _extract_latest_value(ts: dict[str, Any]) -> tuple[float | None, datetime | None]:
    try:
        values_list = ts["values"][0]["value"]
    except (KeyError, TypeError, IndexError):
        return None, None

    if not isinstance(values_list, list) or not values_list:
        return None, None

    latest = values_list[-1]
    raw_value = latest.get("value")
    reading = _parse_optional_float(raw_value)

    raw_dt = latest.get("dateTime")
    reading_time: datetime | None = None
    if isinstance(raw_dt, str):
        try:
            reading_time = datetime.fromisoformat(raw_dt)
            if reading_time.tzinfo is None:
                reading_time = reading_time.replace(tzinfo=UTC)
        except ValueError:
            pass

    return reading, reading_time


def _parse_optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None
    # USGS uses -999999 as a sentinel for missing data
    if result <= -999999:
        return None
    return result

"""Fetch precipitation data from the Open-Meteo forecast API."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from uuid import uuid4

_OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

_USER_AGENT = "OpenFloodAI/0.1.0 (open-source flood detection; github.com/openfloodai)"


class OpenMeteoError(RuntimeError):
    """Raised when fetching or parsing Open-Meteo data fails."""


def fetch_precipitation(
    latitude: float,
    longitude: float,
    *,
    past_days: int = 1,
    forecast_days: int = 2,
    timeout: float = 10.0,
) -> dict[str, object]:
    """Fetch hourly precipitation data and compute summary statistics.

    Queries the Open-Meteo API for historical and forecast precipitation,
    then derives recent totals, forecast totals, current-hour value, and an
    overall trend.
    """

    _validate_coordinates(latitude, longitude)
    _validate_day_range("past_days", past_days, min_val=0, max_val=92)
    _validate_day_range("forecast_days", forecast_days, min_val=1, max_val=16)

    data = _fetch_json(
        latitude=latitude,
        longitude=longitude,
        past_days=past_days,
        forecast_days=forecast_days,
        timeout=timeout,
    )

    hourly = data.get("hourly")
    if not isinstance(hourly, dict):
        raise OpenMeteoError("Open-Meteo response missing 'hourly' object")

    times = hourly.get("time")
    precipitation = hourly.get("precipitation")
    if not isinstance(times, list) or not isinstance(precipitation, list):
        raise OpenMeteoError("Open-Meteo response missing 'time' or 'precipitation' arrays")
    if len(times) != len(precipitation):
        raise OpenMeteoError("Open-Meteo 'time' and 'precipitation' arrays differ in length")

    now = datetime.now(tz=UTC)
    recent_mm, forecast_mm, current_mm = _partition_precipitation(
        times,
        precipitation,
        now,
        past_hours=past_days * 24,
    )
    trend = _compute_trend(times, precipitation, now)

    return {
        "contract_version": "v1",
        "record_id": f"precip-{uuid4()}",
        "record_type": "precipitation_data",
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": now.isoformat(),
        "recent_precipitation_mm": round(recent_mm, 2),
        "forecast_precipitation_mm": round(forecast_mm, 2),
        "current_precipitation_mm": round(current_mm, 2),
        "precipitation_trend": trend,
    }


def assess_precipitation_risk(
    recent_mm: float,
    forecast_mm: float,
) -> dict[str, object]:
    """Assess flood risk from precipitation totals.

    Pure computation -- no network calls.  Returns risk state, combined
    millimeters, and a normalised risk factor between 0.0 and 1.0.
    """

    combined_mm = recent_mm + forecast_mm
    risk_state = _risk_state_from_combined(combined_mm)
    risk_factor = _risk_factor_from_combined(combined_mm)

    return {
        "precipitation_risk_state": risk_state,
        "combined_mm": round(combined_mm, 2),
        "risk_factor": round(risk_factor, 6),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90.0 <= latitude <= 90.0):
        raise OpenMeteoError(f"Latitude must be between -90 and 90, got {latitude}")
    if not (-180.0 <= longitude <= 180.0):
        raise OpenMeteoError(f"Longitude must be between -180 and 180, got {longitude}")


def _validate_day_range(
    name: str,
    value: int,
    *,
    min_val: int,
    max_val: int,
) -> None:
    if not (min_val <= value <= max_val):
        raise OpenMeteoError(f"{name} must be between {min_val} and {max_val}, got {value}")


def _fetch_json(
    *,
    latitude: float,
    longitude: float,
    past_days: int,
    forecast_days: int,
    timeout: float,
) -> dict[str, object]:
    params = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "precipitation",
            "past_days": past_days,
            "forecast_days": forecast_days,
        }
    )
    url = f"{_OPEN_METEO_BASE}?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise OpenMeteoError(f"Open-Meteo API returned HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise OpenMeteoError(f"Open-Meteo API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise OpenMeteoError(f"Open-Meteo API request timed out after {timeout}s") from exc

    try:
        return json.loads(body)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, ValueError) as exc:
        raise OpenMeteoError("Open-Meteo API returned invalid JSON") from exc


def _parse_timestamp(iso_string: str) -> datetime | None:
    """Parse an ISO-8601 local timestamp from Open-Meteo into a UTC datetime.

    Open-Meteo returns timestamps without timezone info (e.g.
    ``2024-01-15T12:00``).  We treat them as UTC for partitioning purposes.
    """

    try:
        return datetime.fromisoformat(iso_string).replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _safe_float(value: object) -> float:
    """Coerce a precipitation value to float, treating None as 0.0."""

    if value is None:
        return 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _partition_precipitation(
    times: list[object],
    precipitation: list[object],
    now: datetime,
    *,
    past_hours: int,
) -> tuple[float, float, float]:
    """Split hourly precipitation into recent, forecast, and current."""

    recent_mm = 0.0
    forecast_mm = 0.0
    current_mm = 0.0
    current_found = False

    for raw_time, raw_precip in zip(times, precipitation, strict=False):
        if not isinstance(raw_time, str):
            continue
        ts = _parse_timestamp(raw_time)
        if ts is None:
            continue
        mm = _safe_float(raw_precip)

        diff_hours = (now - ts).total_seconds() / 3600.0

        if 0 <= diff_hours < 1 and not current_found:
            current_mm = mm
            current_found = True
            recent_mm += mm
        elif diff_hours >= 0 and diff_hours < past_hours:
            recent_mm += mm
        elif diff_hours < 0:
            forecast_mm += mm

    return recent_mm, forecast_mm, current_mm


def _compute_trend(
    times: list[object],
    precipitation: list[object],
    now: datetime,
) -> str:
    """Determine the precipitation trend from recent vs. upcoming hours."""

    recent_sum = 0.0
    upcoming_sum = 0.0
    recent_count = 0
    upcoming_count = 0

    for raw_time, raw_precip in zip(times, precipitation, strict=False):
        if not isinstance(raw_time, str):
            continue
        ts = _parse_timestamp(raw_time)
        if ts is None:
            continue
        mm = _safe_float(raw_precip)
        diff_hours = (now - ts).total_seconds() / 3600.0

        if 0 <= diff_hours <= 6:
            recent_sum += mm
            recent_count += 1
        elif -6 <= diff_hours < 0:
            upcoming_sum += mm
            upcoming_count += 1

    if recent_count == 0 and upcoming_count == 0:
        return "DRY"

    total = recent_sum + upcoming_sum
    if total < 0.1:
        return "DRY"

    recent_avg = recent_sum / max(recent_count, 1)
    upcoming_avg = upcoming_sum / max(upcoming_count, 1)

    if upcoming_avg > recent_avg * 1.25:
        return "INCREASING"
    if upcoming_avg < recent_avg * 0.75:
        return "DECREASING"
    return "STEADY"


def _risk_state_from_combined(combined_mm: float) -> str:
    if combined_mm >= 50.0:
        return "EXTREME"
    if combined_mm >= 25.0:
        return "HIGH"
    if combined_mm >= 10.0:
        return "MODERATE"
    return "LOW"


def _risk_factor_from_combined(combined_mm: float) -> float:
    """Map combined precipitation to a 0.0-1.0 risk factor.

    Uses 100 mm as the saturation point so the factor stays meaningful
    well above the EXTREME threshold.
    """

    if combined_mm <= 0.0:
        return 0.0
    return min(combined_mm / 100.0, 1.0)

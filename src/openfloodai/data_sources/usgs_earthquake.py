"""Fetch recent earthquake data from the USGS Earthquake Hazards API.

Earthquakes near flood-prone river basins can trigger landslides that dam
rivers, destabilise glacial lakes, and rupture embankments -- all upstream
causes of catastrophic flooding.  This module provides real-time seismic
data that the multi-source risk engine can use to raise flood risk when
significant earthquakes occur near monitored sites.

API documentation: https://earthquake.usgs.gov/fdsnws/event/1/
Free, no API key required.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import uuid4

_BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
_USER_AGENT = "OpenFloodAI/0.1.0 (open-source flood detection; github.com/openfloodai)"


class USGSEarthquakeError(RuntimeError):
    """Raised when USGS Earthquake API data cannot be fetched or parsed."""


def fetch_nearby_earthquakes(
    latitude: float,
    longitude: float,
    *,
    radius_km: float = 300.0,
    min_magnitude: float = 4.0,
    days_back: int = 7,
    timeout: float = 10.0,
) -> list[dict[str, object]]:
    """Fetch recent earthquakes near a geographic point.

    Returns a list of V1 earthquake records sorted by magnitude descending.
    """

    _validate_coordinates(latitude, longitude)
    if radius_km <= 0:
        raise USGSEarthquakeError("radius_km must be positive")
    if min_magnitude < 0:
        raise USGSEarthquakeError("min_magnitude must be non-negative")
    if days_back < 1:
        raise USGSEarthquakeError("days_back must be at least 1")

    end = datetime.now(tz=UTC)
    start = end - timedelta(days=days_back)

    params = (
        f"format=geojson"
        f"&starttime={start.strftime('%Y-%m-%d')}"
        f"&endtime={end.strftime('%Y-%m-%d')}"
        f"&latitude={latitude}&longitude={longitude}"
        f"&maxradiuskm={radius_km}"
        f"&minmagnitude={min_magnitude}"
        f"&orderby=magnitude"
        f"&limit=20"
    )

    data = _fetch_json(f"{_BASE_URL}?{params}", timeout=timeout)

    features = data.get("features")
    if not isinstance(features, list):
        raise USGSEarthquakeError("USGS Earthquake response missing 'features' array")

    records: list[dict[str, object]] = []
    for feature in features:
        record = _build_record(feature, latitude, longitude)
        if record is not None:
            records.append(record)

    return records


def assess_seismic_flood_risk(
    earthquakes: list[dict[str, object]],
) -> dict[str, object]:
    """Assess flood risk posed by recent seismic activity.

    Pure computation -- no network calls.  Returns a seismic risk state
    and a normalised risk factor.

    Risk logic:
    - Magnitude >= 7.0 within range -> EXTREME (landslide dams, GLOF triggers)
    - Magnitude >= 6.0 -> HIGH
    - Magnitude >= 5.0 -> MODERATE
    - Magnitude >= 4.0 -> LOW
    - No significant earthquakes -> NONE
    """

    if not earthquakes:
        return {
            "seismic_risk_state": "NONE",
            "earthquake_count": 0,
            "max_magnitude": 0.0,
            "risk_factor": 0.0,
            "strongest_event": None,
        }

    max_mag = 0.0
    strongest: dict[str, object] | None = None

    for eq in earthquakes:
        mag = _optional_float(eq.get("magnitude"))
        if mag is not None and mag > max_mag:
            max_mag = mag
            strongest = eq

    risk_state = _risk_state_from_magnitude(max_mag)
    risk_factor = _risk_factor_from_magnitude(max_mag)

    return {
        "seismic_risk_state": risk_state,
        "earthquake_count": len(earthquakes),
        "max_magnitude": round(max_mag, 1),
        "risk_factor": round(risk_factor, 4),
        "strongest_event": {
            "magnitude": strongest.get("magnitude") if strongest else None,
            "place": strongest.get("place") if strongest else None,
            "depth_km": strongest.get("depth_km") if strongest else None,
            "distance_km": strongest.get("distance_km") if strongest else None,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90.0 <= latitude <= 90.0):
        raise USGSEarthquakeError(f"Latitude must be between -90 and 90, got {latitude}")
    if not (-180.0 <= longitude <= 180.0):
        raise USGSEarthquakeError(f"Longitude must be between -180 and 180, got {longitude}")


def _fetch_json(url: str, *, timeout: float) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        msg = f"USGS Earthquake API returned HTTP {exc.code}: {exc.reason}"
        raise USGSEarthquakeError(msg) from exc
    except urllib.error.URLError as exc:
        msg = f"Could not reach USGS Earthquake API: {exc.reason}"
        raise USGSEarthquakeError(msg) from exc
    except TimeoutError as exc:
        msg = f"USGS Earthquake API timed out after {timeout}s"
        raise USGSEarthquakeError(msg) from exc

    try:
        return json.loads(body)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        raise USGSEarthquakeError("USGS Earthquake API returned invalid JSON") from exc


def _build_record(
    feature: object,
    ref_lat: float,
    ref_lon: float,
) -> dict[str, object] | None:
    if not isinstance(feature, dict):
        return None

    properties = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(properties, dict) or not isinstance(geometry, dict):
        return None

    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or len(coords) < 3:
        return None

    eq_lon = _optional_float(coords[0])
    eq_lat = _optional_float(coords[1])
    eq_depth = _optional_float(coords[2])

    if eq_lat is None or eq_lon is None:
        return None

    distance = _haversine_km(ref_lat, ref_lon, eq_lat, eq_lon)
    magnitude = _optional_float(properties.get("mag"))
    if magnitude is None:
        return None

    epoch_ms = properties.get("time")
    timestamp = ""
    if isinstance(epoch_ms, (int, float)):
        timestamp = datetime.fromtimestamp(epoch_ms / 1000.0, tz=UTC).isoformat()

    return {
        "contract_version": "v1",
        "record_id": f"earthquake-{uuid4()}",
        "record_type": "earthquake_event",
        "magnitude": round(magnitude, 1),
        "place": str(properties.get("place", "")),
        "depth_km": round(eq_depth, 1) if eq_depth is not None else None,
        "latitude": round(eq_lat, 4),
        "longitude": round(eq_lon, 4),
        "distance_km": round(distance, 1),
        "timestamp": timestamp,
        "usgs_id": str(properties.get("ids", "")),
        "alert_level": str(properties.get("alert", "")),
        "tsunami_flag": bool(properties.get("tsunami", 0)),
    }


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None
    return result


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance between two points in km."""
    import math

    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _risk_state_from_magnitude(magnitude: float) -> str:
    if magnitude >= 7.0:
        return "EXTREME"
    if magnitude >= 6.0:
        return "HIGH"
    if magnitude >= 5.0:
        return "MODERATE"
    if magnitude >= 4.0:
        return "LOW"
    return "NONE"


def _risk_factor_from_magnitude(magnitude: float) -> float:
    if magnitude <= 4.0:
        return 0.0
    return min((magnitude - 4.0) / 4.0, 1.0)

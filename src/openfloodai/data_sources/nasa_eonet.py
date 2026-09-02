"""Fetch active natural disaster events from NASA EONET (Earth Observatory Natural Event Tracker).

EONET provides near-real-time data on natural events worldwide including
floods, severe storms, and landslides.  Unlike NWS (US-only), EONET covers
the entire globe -- critical for monitoring in Nepal, Bangladesh, and other
flood-prone regions outside the US.

API documentation: https://eonet.gsfc.nasa.gov/docs/v3
Free, no API key required.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from uuid import uuid4

_BASE_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
_USER_AGENT = "OpenFloodAI/0.1.0 (open-source flood detection; github.com/openfloodai)"

_FLOOD_CATEGORY_ID = "floods"
_SEVERE_STORM_CATEGORY_ID = "severeStorms"
_LANDSLIDE_CATEGORY_ID = "landslides"

_RELEVANT_CATEGORIES = frozenset({
    _FLOOD_CATEGORY_ID,
    _SEVERE_STORM_CATEGORY_ID,
    _LANDSLIDE_CATEGORY_ID,
})


class NASAEONETError(RuntimeError):
    """Raised when NASA EONET API data cannot be fetched or parsed."""


def fetch_flood_events(
    *,
    days_back: int = 30,
    status: str = "open",
    timeout: float = 15.0,
) -> list[dict[str, object]]:
    """Fetch active flood, severe storm, and landslide events globally.

    Returns a list of V1 event records.  Events are classified by category
    and include geographic coordinates where available.
    """

    if days_back < 1:
        raise NASAEONETError("days_back must be at least 1")

    categories = ",".join(sorted(_RELEVANT_CATEGORIES))
    params = f"category={categories}&status={status}&days={days_back}&limit=50"
    data = _fetch_json(f"{_BASE_URL}?{params}", timeout=timeout)

    events = data.get("events")
    if not isinstance(events, list):
        raise NASAEONETError("NASA EONET response missing 'events' array")

    records: list[dict[str, object]] = []
    for event in events:
        record = _build_event_record(event)
        if record is not None:
            records.append(record)

    return records


def fetch_events_near(
    latitude: float,
    longitude: float,
    *,
    radius_km: float = 500.0,
    days_back: int = 30,
    timeout: float = 15.0,
) -> list[dict[str, object]]:
    """Fetch flood-related events near a geographic point.

    Filters the global event list to those within ``radius_km`` of the
    given coordinates.
    """

    _validate_coordinates(latitude, longitude)
    if radius_km <= 0:
        raise NASAEONETError("radius_km must be positive")

    all_events = fetch_flood_events(days_back=days_back, timeout=timeout)
    nearby: list[dict[str, object]] = []

    for event in all_events:
        event_lat = _optional_float(event.get("latitude"))
        event_lon = _optional_float(event.get("longitude"))
        if event_lat is None or event_lon is None:
            continue
        dist = _haversine_km(latitude, longitude, event_lat, event_lon)
        if dist <= radius_km:
            event["distance_km"] = round(dist, 1)
            nearby.append(event)

    nearby.sort(key=lambda e: _optional_float(e.get("distance_km")) or float("inf"))
    return nearby


def summarize_events(events: list[dict[str, object]]) -> dict[str, object]:
    """Summarize a list of EONET event records.

    Pure computation -- no network calls.
    """

    if not events:
        return {
            "event_count": 0,
            "flood_count": 0,
            "storm_count": 0,
            "landslide_count": 0,
            "event_state": "CLEAR",
            "nearest_event": None,
        }

    flood_count = 0
    storm_count = 0
    landslide_count = 0
    nearest: dict[str, object] | None = None
    nearest_dist = float("inf")

    for event in events:
        category = str(event.get("category", "")).lower()
        if "flood" in category:
            flood_count += 1
        elif "storm" in category:
            storm_count += 1
        elif "landslide" in category:
            landslide_count += 1

        dist = _optional_float(event.get("distance_km"))
        if dist is not None and dist < nearest_dist:
            nearest_dist = dist
            nearest = event

    event_state = "CLEAR"
    if flood_count > 0 or landslide_count > 0:
        event_state = "ACTIVE_FLOOD"
    elif storm_count > 0:
        event_state = "ACTIVE_STORM"

    return {
        "event_count": len(events),
        "flood_count": flood_count,
        "storm_count": storm_count,
        "landslide_count": landslide_count,
        "event_state": event_state,
        "nearest_event": {
            "title": nearest.get("title") if nearest else None,
            "category": nearest.get("category") if nearest else None,
            "distance_km": nearest.get("distance_km") if nearest else None,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90.0 <= latitude <= 90.0):
        raise NASAEONETError(f"Latitude must be between -90 and 90, got {latitude}")
    if not (-180.0 <= longitude <= 180.0):
        raise NASAEONETError(f"Longitude must be between -180 and 180, got {longitude}")


def _fetch_json(url: str, *, timeout: float) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise NASAEONETError(f"NASA EONET API returned HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise NASAEONETError(f"Could not reach NASA EONET API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise NASAEONETError(f"NASA EONET API request timed out after {timeout}s") from exc

    try:
        return json.loads(body)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        raise NASAEONETError("NASA EONET API returned invalid JSON") from exc


def _build_event_record(event: object) -> dict[str, object] | None:
    if not isinstance(event, dict):
        return None

    title = event.get("title")
    if not isinstance(title, str):
        return None

    categories = event.get("categories")
    category_name = ""
    if isinstance(categories, list) and categories:
        first_cat = categories[0]
        if isinstance(first_cat, dict):
            category_name = str(first_cat.get("title", first_cat.get("id", "")))

    geometry_list = event.get("geometry")
    lat: float | None = None
    lon: float | None = None
    event_date = ""

    if isinstance(geometry_list, list) and geometry_list:
        latest_geo = geometry_list[-1]
        if isinstance(latest_geo, dict):
            coords = latest_geo.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 2:
                lon = _optional_float(coords[0])
                lat = _optional_float(coords[1])
            raw_date = latest_geo.get("date")
            if isinstance(raw_date, str):
                event_date = raw_date

    return {
        "contract_version": "v1",
        "record_id": f"eonet-{uuid4()}",
        "record_type": "eonet_event",
        "eonet_id": str(event.get("id", "")),
        "title": title,
        "category": category_name,
        "latitude": lat,
        "longitude": lon,
        "event_date": event_date,
        "closed": event.get("closed"),
        "sources": _extract_sources(event.get("sources")),
    }


def _extract_sources(sources: object) -> list[dict[str, str]]:
    if not isinstance(sources, list):
        return []
    result: list[dict[str, str]] = []
    for src in sources:
        if isinstance(src, dict):
            result.append({
                "id": str(src.get("id", "")),
                "url": str(src.get("url", "")),
            })
    return result


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

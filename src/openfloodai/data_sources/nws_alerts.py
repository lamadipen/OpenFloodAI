"""Fetch active flood-related alerts from the National Weather Service API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from uuid import uuid4

_NWS_API_BASE = "https://api.weather.gov"

_USER_AGENT = "OpenFloodAI/0.1.0 (open-source flood detection; github.com/openfloodai)"

_FLOOD_EVENT_TYPES = frozenset(
    {
        "Flood Warning",
        "Flood Watch",
        "Flood Advisory",
        "Flash Flood Warning",
        "Flash Flood Watch",
        "Coastal Flood Warning",
        "Coastal Flood Watch",
        "River Flood Warning",
    }
)

_SEVERITY_ORDER: dict[str, int] = {
    "Extreme": 4,
    "Severe": 3,
    "Moderate": 2,
    "Minor": 1,
    "Unknown": 0,
}


class NWSAlertError(RuntimeError):
    """Raised when fetching or parsing NWS alert data fails."""


def fetch_active_flood_alerts(
    latitude: float,
    longitude: float,
    *,
    timeout: float = 10.0,
) -> list[dict[str, object]]:
    """Fetch active flood-related alerts for a geographic point.

    Uses the NWS ``/alerts/active`` endpoint, filtering to flood-related
    event types only.  Returns a list of V1 alert records.
    """

    _validate_coordinates(latitude, longitude)

    url = f"{_NWS_API_BASE}/alerts/active?point={latitude},{longitude}"
    data = _fetch_json(url, timeout=timeout)

    features = data.get("features")
    if not isinstance(features, list):
        raise NWSAlertError("NWS response missing 'features' array")

    alerts: list[dict[str, object]] = []
    for feature in features:
        properties = _feature_properties(feature)
        event_type = _string_or_default(properties, "event", "")
        if event_type not in _FLOOD_EVENT_TYPES:
            continue
        alerts.append(_build_alert_record(properties, event_type))

    return alerts


def summarize_alerts(alerts: list[dict[str, object]]) -> dict[str, object]:
    """Compute a summary from a list of alert records.

    Pure computation -- no network calls.  Returns alert count, maximum
    severity, boolean flags for warnings and watches, and an overall
    ``alert_state``.
    """

    if not alerts:
        return {
            "alert_count": 0,
            "max_severity": "Unknown",
            "has_warning": False,
            "has_watch": False,
            "alert_state": "CLEAR",
        }

    max_severity = _max_severity(alerts)
    has_warning = _has_event_keyword(alerts, "Warning")
    has_watch = _has_event_keyword(alerts, "Watch")
    alert_state = _derive_alert_state(max_severity, has_warning)

    return {
        "alert_count": len(alerts),
        "max_severity": max_severity,
        "has_warning": has_warning,
        "has_watch": has_watch,
        "alert_state": alert_state,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90.0 <= latitude <= 90.0):
        raise NWSAlertError(f"Latitude must be between -90 and 90, got {latitude}")
    if not (-180.0 <= longitude <= 180.0):
        raise NWSAlertError(f"Longitude must be between -180 and 180, got {longitude}")


def _fetch_json(url: str, *, timeout: float) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/geo+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise NWSAlertError(f"NWS API returned HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise NWSAlertError(f"NWS API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise NWSAlertError(f"NWS API request timed out after {timeout}s") from exc

    try:
        return json.loads(body)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, ValueError) as exc:
        raise NWSAlertError("NWS API returned invalid JSON") from exc


def _feature_properties(feature: object) -> dict[str, object]:
    if not isinstance(feature, dict):
        raise NWSAlertError("NWS feature is not a JSON object")
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise NWSAlertError("NWS feature missing 'properties' object")
    return properties


def _string_or_default(
    mapping: dict[str, object],
    key: str,
    default: str,
) -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def _build_alert_record(
    properties: dict[str, object],
    event_type: str,
) -> dict[str, object]:
    affected_zones_raw = properties.get("affectedZones")
    affected_zones: list[str] = []
    if isinstance(affected_zones_raw, list):
        affected_zones = [str(zone) for zone in affected_zones_raw if isinstance(zone, str)]

    return {
        "contract_version": "v1",
        "record_id": f"nws-alert-{uuid4()}",
        "record_type": "nws_flood_alert",
        "event_type": event_type,
        "severity": _string_or_default(properties, "severity", "Unknown"),
        "urgency": _string_or_default(properties, "urgency", "Unknown"),
        "certainty": _string_or_default(properties, "certainty", "Unknown"),
        "headline": _string_or_default(properties, "headline", ""),
        "description": _string_or_default(properties, "description", ""),
        "onset": _string_or_default(
            properties,
            "onset",
            datetime.now(tz=UTC).isoformat(),
        ),
        "expires": _string_or_default(
            properties,
            "expires",
            "",
        ),
        "affected_zones": affected_zones,
    }


def _max_severity(alerts: list[dict[str, object]]) -> str:
    best_label = "Unknown"
    best_rank = _SEVERITY_ORDER.get(best_label, 0)
    for alert in alerts:
        label = _string_or_default(alert, "severity", "Unknown")
        rank = _SEVERITY_ORDER.get(label, 0)
        if rank > best_rank:
            best_rank = rank
            best_label = label
    return best_label


def _has_event_keyword(
    alerts: list[dict[str, object]],
    keyword: str,
) -> bool:
    for alert in alerts:
        event_type = _string_or_default(alert, "event_type", "")
        if keyword in event_type:
            return True
    return False


def _derive_alert_state(max_severity: str, has_warning: bool) -> str:
    if max_severity == "Extreme":
        return "EXTREME"
    if has_warning:
        return "WARNING"
    return "WATCH"

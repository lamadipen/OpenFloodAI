from __future__ import annotations

from openfloodai.data_sources.nasa_eonet import summarize_events


def _event(
    title: str = "Test Flood",
    category: str = "Floods",
    distance_km: float | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "title": title,
        "category": category,
    }
    if distance_km is not None:
        record["distance_km"] = distance_km
    return record


def test_empty_events() -> None:
    result = summarize_events([])
    assert result["event_count"] == 0
    assert result["event_state"] == "CLEAR"
    assert result["nearest_event"] is None


def test_single_flood_event() -> None:
    result = summarize_events([_event("Nepal Flood 2024", "Floods", 100.0)])
    assert result["event_count"] == 1
    assert result["flood_count"] == 1
    assert result["event_state"] == "ACTIVE_FLOOD"


def test_storm_event() -> None:
    result = summarize_events([_event("Cyclone", "Severe Storms", 200.0)])
    assert result["storm_count"] == 1
    assert result["event_state"] == "ACTIVE_STORM"


def test_landslide_triggers_flood_state() -> None:
    result = summarize_events([_event("Landslide", "Landslides", 50.0)])
    assert result["landslide_count"] == 1
    assert result["event_state"] == "ACTIVE_FLOOD"


def test_multiple_events_nearest() -> None:
    events = [
        _event("Far flood", "Floods", 300.0),
        _event("Near flood", "Floods", 50.0),
    ]
    result = summarize_events(events)
    assert result["event_count"] == 2
    nearest = result["nearest_event"]
    assert isinstance(nearest, dict)
    assert nearest["distance_km"] == 50.0


def test_mixed_categories() -> None:
    events = [
        _event("Flood A", "Floods"),
        _event("Storm B", "Severe Storms"),
        _event("Landslide C", "Landslides"),
    ]
    result = summarize_events(events)
    assert result["flood_count"] == 1
    assert result["storm_count"] == 1
    assert result["landslide_count"] == 1
    assert result["event_state"] == "ACTIVE_FLOOD"


def test_flood_takes_priority_over_storm() -> None:
    events = [
        _event("Storm", "Severe Storms"),
        _event("Flood", "Floods"),
    ]
    result = summarize_events(events)
    assert result["event_state"] == "ACTIVE_FLOOD"

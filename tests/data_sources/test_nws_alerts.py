from __future__ import annotations

from openfloodai.data_sources.nws_alerts import summarize_alerts


def _alert(event_type: str, severity: str = "Unknown") -> dict[str, object]:
    return {
        "event_type": event_type,
        "severity": severity,
    }


def test_empty_alerts() -> None:
    result = summarize_alerts([])
    assert result["alert_count"] == 0
    assert result["max_severity"] == "Unknown"
    assert result["has_warning"] is False
    assert result["has_watch"] is False
    assert result["alert_state"] == "CLEAR"


def test_single_warning() -> None:
    result = summarize_alerts([_alert("Flood Warning", "Severe")])
    assert result["alert_count"] == 1
    assert result["max_severity"] == "Severe"
    assert result["has_warning"] is True
    assert result["alert_state"] == "WARNING"


def test_single_watch() -> None:
    result = summarize_alerts([_alert("Flood Watch", "Moderate")])
    assert result["alert_count"] == 1
    assert result["has_watch"] is True
    assert result["has_warning"] is False
    assert result["alert_state"] == "WATCH"


def test_extreme_severity() -> None:
    result = summarize_alerts([_alert("Flash Flood Warning", "Extreme")])
    assert result["max_severity"] == "Extreme"
    assert result["alert_state"] == "EXTREME"


def test_multiple_alerts_picks_highest() -> None:
    alerts = [
        _alert("Flood Watch", "Minor"),
        _alert("Flood Warning", "Severe"),
    ]
    result = summarize_alerts(alerts)
    assert result["alert_count"] == 2
    assert result["max_severity"] == "Severe"
    assert result["has_warning"] is True
    assert result["has_watch"] is True

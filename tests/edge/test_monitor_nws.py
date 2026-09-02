from __future__ import annotations

from typing import Any

import pytest

from openfloodai.edge.monitor import (
    DataSourceCache,
    _assess_nws_cache,
    _fetch_nws_alerts,
)


def test_fetch_nws_alerts_returns_none_on_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_fetch_nws_alerts returns None when the nws_alerts module cannot be imported."""
    real_import = __import__

    def _failing_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if "nws_alerts" in name:
            raise ImportError("mocked import failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _failing_import)
    result = _fetch_nws_alerts(27.7, 85.3)
    assert result is None


def test_fetch_nws_alerts_returns_none_on_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_fetch_nws_alerts returns None when the fetch call raises."""

    def _boom(lat: float, lon: float) -> list[dict[str, object]]:
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "openfloodai.data_sources.nws_alerts.fetch_active_flood_alerts",
        _boom,
    )
    result = _fetch_nws_alerts(27.7, 85.3)
    assert result is None


def test_assess_nws_cache_extreme() -> None:
    state, reasons = _assess_nws_cache({"alert_state": "EXTREME", "alert_count": 2})
    assert state == "WARNING_CANDIDATE"
    assert len(reasons) == 1
    assert "extreme" in reasons[0].lower()
    assert "2 alert(s)" in reasons[0]


def test_assess_nws_cache_warning() -> None:
    state, reasons = _assess_nws_cache({"alert_state": "WARNING", "alert_count": 1})
    assert state == "WARNING_CANDIDATE"
    assert len(reasons) == 1
    assert "warning" in reasons[0].lower()


def test_assess_nws_cache_watch() -> None:
    state, reasons = _assess_nws_cache({"alert_state": "WATCH", "alert_count": 3})
    assert state == "WATCH"
    assert len(reasons) == 1
    assert "watch" in reasons[0].lower()
    assert "3 alert(s)" in reasons[0]


def test_assess_nws_cache_clear() -> None:
    state, reasons = _assess_nws_cache({"alert_state": "CLEAR", "alert_count": 0})
    assert state == "NORMAL"
    assert reasons == []


def test_assess_nws_cache_missing_fields() -> None:
    """Defaults to CLEAR/NORMAL when keys are absent."""
    state, reasons = _assess_nws_cache({})
    assert state == "NORMAL"
    assert reasons == []


def test_data_source_cache_nws_alerts_field() -> None:
    cache = DataSourceCache()
    assert cache.nws_alerts is None

    cache.nws_alerts = {"alert_state": "WARNING", "alert_count": 1}
    assert cache.nws_alerts["alert_state"] == "WARNING"
    assert cache.nws_alerts["alert_count"] == 1

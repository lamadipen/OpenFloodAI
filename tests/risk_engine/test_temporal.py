from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from openfloodai.risk_engine.temporal import (
    TemporalConfig,
    TemporalRiskError,
    TemporalWindow,
)


def _window(
    *,
    window_minutes: int = 10,
    watch_sustained: int = 3,
    warning_sustained: int = 5,
    min_samples: int = 3,
) -> TemporalWindow:
    return TemporalWindow(
        config=TemporalConfig(
            window_minutes=window_minutes,
            watch_sustained_minutes=watch_sustained,
            warning_sustained_minutes=warning_sustained,
            min_samples=min_samples,
        ),
    )


def test_insufficient_samples() -> None:
    w = _window(min_samples=5)
    w.add_sample("WATCH", 0.8, 0.3)
    result = w.evaluate()
    assert result["temporal_risk_state"] == "UNKNOWN"


def test_normal_conditions() -> None:
    w = _window()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(5):
        w.add_sample("NORMAL", 0.9, 0.01, timestamp=base + timedelta(minutes=i))
    result = w.evaluate(timestamp=base + timedelta(minutes=5))
    assert result["temporal_risk_state"] == "NORMAL"


def test_sustained_watch() -> None:
    w = _window(watch_sustained=2, min_samples=3)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(5):
        w.add_sample("WATCH", 0.7, 0.2, timestamp=base + timedelta(minutes=i))
    result = w.evaluate(timestamp=base + timedelta(minutes=5))
    assert result["temporal_risk_state"] == "WATCH"


def test_sustained_warning() -> None:
    w = _window(warning_sustained=3, min_samples=3)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(6):
        w.add_sample(
            "WARNING_CANDIDATE",
            0.9,
            0.5,
            timestamp=base + timedelta(minutes=i),
        )
    result = w.evaluate(timestamp=base + timedelta(minutes=6))
    assert result["temporal_risk_state"] == "WARNING_CANDIDATE"


def test_transient_watch_not_escalated() -> None:
    w = _window(watch_sustained=3, min_samples=3)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    w.add_sample("WATCH", 0.7, 0.2, timestamp=base)
    w.add_sample("NORMAL", 0.9, 0.01, timestamp=base + timedelta(minutes=1))
    w.add_sample("WATCH", 0.7, 0.2, timestamp=base + timedelta(minutes=2))
    w.add_sample("NORMAL", 0.9, 0.01, timestamp=base + timedelta(minutes=3))
    w.add_sample("NORMAL", 0.9, 0.01, timestamp=base + timedelta(minutes=4))
    result = w.evaluate(timestamp=base + timedelta(minutes=4))
    assert result["temporal_risk_state"] == "NORMAL"


def test_old_samples_evicted() -> None:
    w = _window(window_minutes=5, min_samples=2)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    w.add_sample("WATCH", 0.7, 0.2, timestamp=base)
    w.add_sample("WATCH", 0.7, 0.2, timestamp=base + timedelta(minutes=1))
    w.add_sample("NORMAL", 0.9, 0.01, timestamp=base + timedelta(minutes=8))
    w.add_sample("NORMAL", 0.9, 0.01, timestamp=base + timedelta(minutes=9))
    result = w.evaluate(timestamp=base + timedelta(minutes=9))
    assert result["temporal_risk_state"] == "NORMAL"
    assert result["sample_count"] == 2


def test_avg_water_ratio() -> None:
    w = _window(min_samples=2)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    w.add_sample("NORMAL", 0.9, 0.1, timestamp=base)
    w.add_sample("NORMAL", 0.9, 0.3, timestamp=base + timedelta(minutes=1))
    result = w.evaluate(timestamp=base + timedelta(minutes=1))
    assert abs(result["avg_water_ratio"] - 0.2) < 0.001  # type: ignore[operator]


def test_invalid_window_minutes() -> None:
    with pytest.raises(TemporalRiskError):
        TemporalConfig(window_minutes=0)


def test_record_fields() -> None:
    w = _window(min_samples=1)
    w.add_sample("NORMAL", 0.9, 0.0)
    result = w.evaluate()
    assert result["contract_version"] == "v1"
    assert result["record_type"] == "temporal_risk_output"
    assert "record_id" in result
    assert "timestamp" in result

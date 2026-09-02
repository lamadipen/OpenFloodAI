from __future__ import annotations

import json
from pathlib import Path

from openfloodai.alerts.buffer import (
    BufferConfig,
    buffer_alert,
    buffer_stats,
    create_buffer,
    flush_buffer,
    should_flush,
)
from openfloodai.alerts.webhook import WebhookConfig


def _webhook() -> WebhookConfig:
    return WebhookConfig(url="https://hooks.example.com/alert")


def test_create_buffer(tmp_path: Path) -> None:
    config, state = create_buffer(BufferConfig(buffer_dir=tmp_path / "alerts"))
    assert config.buffer_dir.exists()
    assert state.buffered_count == 0


def test_buffer_alert_creates_file(tmp_path: Path) -> None:
    config, state = create_buffer(BufferConfig(buffer_dir=tmp_path / "alerts"))
    filepath = buffer_alert(
        config,
        state,
        webhook=_webhook(),
        site_id="test-site",
        camera_id="cam-1",
        risk_state="WARNING_CANDIDATE",
        previous_risk_state="NORMAL",
        reason="Water coverage 45%",
        timestamp="2024-09-15T12:00:00Z",
    )
    assert filepath.exists()
    assert state.buffered_count == 1

    data = json.loads(filepath.read_text())
    assert data["site_id"] == "test-site"
    assert data["risk_state"] == "WARNING_CANDIDATE"
    assert data["retry_count"] == 0


def test_buffer_evicts_oldest_at_capacity(tmp_path: Path) -> None:
    config, state = create_buffer(
        BufferConfig(buffer_dir=tmp_path / "alerts", max_buffered_alerts=2)
    )

    for i in range(3):
        buffer_alert(
            config,
            state,
            webhook=_webhook(),
            site_id=f"site-{i}",
            camera_id="cam",
            risk_state="WATCH",
            previous_risk_state="NORMAL",
            reason="test",
            timestamp=f"2024-09-15T12:0{i}:00Z",
        )

    assert state.dropped_count == 1
    pending = list(config.buffer_dir.glob("alert_*.json"))
    assert len(pending) <= 3


def test_buffer_stats(tmp_path: Path) -> None:
    config, state = create_buffer(BufferConfig(buffer_dir=tmp_path / "alerts"))
    buffer_alert(
        config,
        state,
        webhook=_webhook(),
        site_id="site-1",
        camera_id="cam",
        risk_state="WATCH",
        previous_risk_state="NORMAL",
        reason="test",
        timestamp="2024-09-15T12:00:00Z",
    )

    stats = buffer_stats(config, state)
    assert stats["buffered_count"] == 1
    assert stats["delivered_count"] == 0


def test_should_flush_respects_interval(tmp_path: Path) -> None:
    config, state = create_buffer(
        BufferConfig(buffer_dir=tmp_path / "alerts", retry_interval_seconds=300.0)
    )

    assert not should_flush(config, state)

    buffer_alert(
        config,
        state,
        webhook=_webhook(),
        site_id="site-1",
        camera_id="cam",
        risk_state="WATCH",
        previous_risk_state="NORMAL",
        reason="test",
        timestamp="2024-09-15T12:00:00Z",
    )

    state.last_flush_attempt = 0.0
    assert should_flush(config, state)


def test_flush_drops_after_max_retries(tmp_path: Path) -> None:
    config, state = create_buffer(
        BufferConfig(
            buffer_dir=tmp_path / "alerts",
            max_retry_attempts=2,
        )
    )

    filepath = buffer_alert(
        config,
        state,
        webhook=_webhook(),
        site_id="site-1",
        camera_id="cam",
        risk_state="WATCH",
        previous_risk_state="NORMAL",
        reason="test",
        timestamp="2024-09-15T12:00:00Z",
    )

    data = json.loads(filepath.read_text())
    data["retry_count"] = 5
    filepath.write_text(json.dumps(data))

    flush_buffer(config, state)
    assert not filepath.exists()
    assert state.dropped_count == 1


def test_flush_removes_corrupt_files(tmp_path: Path) -> None:
    config, state = create_buffer(BufferConfig(buffer_dir=tmp_path / "alerts"))

    corrupt = config.buffer_dir / "alert_999_bad.json"
    corrupt.write_text("not valid json {{{")
    state.buffered_count = 1

    flush_buffer(config, state)
    assert not corrupt.exists()
    assert state.buffered_count == 0

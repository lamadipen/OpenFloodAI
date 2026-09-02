from __future__ import annotations

import numpy as np

from openfloodai.common import SiteConfig
from openfloodai.edge.monitor import (
    MonitorConfig,
    build_monitor_config,
    create_monitor,
    process_frame,
)
from openfloodai.ingestion.stream import StreamConfig


def _site() -> SiteConfig:
    return SiteConfig(
        site_id="test-site",
        camera_id="cam-test",
        latitude=27.7,
        longitude=85.3,
    )


def _config() -> MonitorConfig:
    return MonitorConfig(
        site=_site(),
        stream=StreamConfig(url="rtsp://example.com"),
    )


def _blue_frame() -> np.ndarray:
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[:, :, 0] = 180
    frame[:, :, 1] = 100
    frame[:, :, 2] = 50
    return frame


def _green_frame() -> np.ndarray:
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[:, :, 0] = 30
    frame[:, :, 1] = 180
    frame[:, :, 2] = 30
    return frame


def test_create_monitor() -> None:
    state = create_monitor(_config())
    assert state.frames_processed == 0
    assert state.current_risk_state == "UNKNOWN"
    assert state.temporal_window is not None


def test_process_normal_frame() -> None:
    config = _config()
    state = create_monitor(config)
    result = process_frame(_green_frame(), config, state)
    assert result["site_id"] == "test-site"
    assert result["camera_id"] == "cam-test"
    assert state.frames_processed == 1


def test_process_water_frame() -> None:
    config = _config()
    state = create_monitor(config)
    result = process_frame(_blue_frame(), config, state)
    assert result["instant_risk_state"] in ("WATCH", "WARNING_CANDIDATE")
    assert "water_detection" in result
    water = result["water_detection"]
    assert isinstance(water, dict)
    assert water["water_detected"] is True


def test_build_monitor_config() -> None:
    config = build_monitor_config(
        _site(),
        "rtsp://cam.example.com/stream1",
        webhook_urls=["https://hooks.example.com/alert"],
        target_fps=0.5,
        window_minutes=15,
    )
    assert config.stream.url == "rtsp://cam.example.com/stream1"
    assert config.stream.target_fps == 0.5
    assert config.temporal_config.window_minutes == 15
    assert len(config.webhooks) == 1


def test_build_monitor_config_no_webhooks() -> None:
    config = build_monitor_config(_site(), "rtsp://example.com")
    assert config.webhooks == []


def test_multiple_frames_track_state() -> None:
    config = _config()
    state = create_monitor(config)
    for _ in range(5):
        process_frame(_green_frame(), config, state)
    assert state.frames_processed == 5

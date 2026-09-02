from __future__ import annotations

import pytest

from openfloodai.ingestion.stream import (
    StreamConfig,
    StreamError,
    StreamState,
    stream_health_record,
)


def test_stream_config_validates_url() -> None:
    with pytest.raises(StreamError, match="URL must not be empty"):
        StreamConfig(url="")


def test_stream_config_validates_timeout() -> None:
    with pytest.raises(StreamError, match="timeout_seconds must be positive"):
        StreamConfig(url="rtsp://example.com", timeout_seconds=0)


def test_stream_config_validates_fps() -> None:
    with pytest.raises(StreamError, match="target_fps must be positive"):
        StreamConfig(url="rtsp://example.com", target_fps=0)


def test_stream_config_validates_retries() -> None:
    with pytest.raises(StreamError, match="max_retries must be non-negative"):
        StreamConfig(url="rtsp://example.com", max_retries=-1)


def test_stream_state_defaults() -> None:
    state = StreamState()
    assert not state.is_connected
    assert state.consecutive_failures == 0
    assert state.total_frames_read == 0


def test_health_record_disconnected() -> None:
    config = StreamConfig(url="rtsp://example.com")
    state = StreamState()
    state.last_error = "Connection refused"
    record = stream_health_record(state, config, "site1", "cam1")
    assert record["input_quality_state"] == "UNKNOWN"
    assert record["is_usable"] is False
    assert "Connection refused" in str(record["human_summary"])


def test_stream_config_defaults() -> None:
    config = StreamConfig(url="rtsp://example.com/stream1")
    assert config.timeout_seconds == 10.0
    assert config.max_retries == 3
    assert config.target_fps == 1.0

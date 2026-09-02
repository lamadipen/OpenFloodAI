"""Continuous monitoring loop for edge deployment.

This is the core runtime that ties everything together: it reads frames
from a camera stream (or local video), runs water detection and camera
health checks, evaluates risk with temporal aggregation, fetches external
data sources, and fires alerts when conditions escalate.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from openfloodai.alerts.webhook import WebhookConfig, send_alert, should_alert
from openfloodai.common import FrameArray, SiteConfig
from openfloodai.ingestion.stream import (
    StreamConfig,
    StreamState,
    close_stream,
    open_stream,
    read_frame,
    reconnect_stream,
)
from openfloodai.risk_engine.temporal import TemporalConfig, TemporalWindow
from openfloodai.vision.camera_health import (
    FrameHistory,
    HealthThresholds,
    analyze_frame_health,
)
from openfloodai.vision.water_detection import (
    WaterThresholds,
    detect_water_coverage,
)

logger = logging.getLogger("openfloodai.edge")


class MonitorError(RuntimeError):
    """Raised when the monitoring loop cannot proceed."""


@dataclass
class MonitorConfig:
    """Full configuration for the monitoring loop."""

    site: SiteConfig
    stream: StreamConfig
    water_thresholds: WaterThresholds = field(default_factory=WaterThresholds)
    health_thresholds: HealthThresholds = field(default_factory=HealthThresholds)
    temporal_config: TemporalConfig = field(default_factory=TemporalConfig)
    webhooks: list[WebhookConfig] = field(default_factory=list)
    max_reconnect_failures: int = 5
    data_source_interval_seconds: float = 300.0
    log_dir: Path | None = None


@dataclass
class MonitorState:
    """Mutable state for the monitoring loop."""

    stream_state: StreamState | None = None
    frame_history: FrameHistory = field(default_factory=FrameHistory)
    temporal_window: TemporalWindow | None = None
    current_risk_state: str = "UNKNOWN"
    frames_processed: int = 0
    alerts_sent: int = 0
    last_data_source_fetch: float = 0.0
    running: bool = False
    reconnect_failures: int = 0


def create_monitor(config: MonitorConfig) -> MonitorState:
    """Create and initialize monitor state for a site."""

    return MonitorState(
        temporal_window=TemporalWindow(config=config.temporal_config),
    )


def run_monitor(config: MonitorConfig, state: MonitorState) -> None:
    """Run the monitoring loop until stopped or fatally disconnected.

    Sets ``state.running = True`` on entry and resets it on exit.
    Call from a thread or set ``state.running = False`` to stop.
    """

    state.running = True
    logger.info(
        "Starting monitor for %s (%s)",
        config.site.site_id,
        config.stream.url,
    )

    try:
        state.stream_state = open_stream(config.stream)
        logger.info("Connected to stream for %s", config.site.site_id)
    except Exception:
        logger.exception("Failed to open stream for %s", config.site.site_id)
        state.running = False
        raise

    try:
        while state.running:
            _monitor_tick(config, state)
    except KeyboardInterrupt:
        logger.info("Monitor stopped by user for %s", config.site.site_id)
    finally:
        state.running = False
        if state.stream_state is not None:
            close_stream(state.stream_state)
        logger.info(
            "Monitor stopped for %s: %d frames processed, %d alerts sent",
            config.site.site_id,
            state.frames_processed,
            state.alerts_sent,
        )


def process_frame(
    frame: FrameArray,
    config: MonitorConfig,
    state: MonitorState,
) -> dict[str, object]:
    """Process a single frame through the full pipeline.

    Useful for testing or single-frame analysis without the monitoring loop.
    """

    site = config.site
    ts = datetime.now(tz=UTC).isoformat()

    health_record = analyze_frame_health(
        frame,
        state.frame_history,
        site.site_id,
        site.camera_id,
        thresholds=config.health_thresholds,
        timestamp=ts,
    )

    water_record = detect_water_coverage(
        frame,
        site.site_id,
        site.camera_id,
        thresholds=config.water_thresholds,
        timestamp=ts,
    )

    raw_ratio = water_record.get("water_coverage_ratio", 0.0)
    water_ratio = float(raw_ratio) if isinstance(raw_ratio, (int, float)) else 0.0
    water_detected = bool(water_record.get("water_detected", False))
    is_usable = bool(health_record.get("is_usable", False))

    if is_usable and water_detected:
        risk_state = "WATCH"
        confidence = min(water_ratio * 2.0, 1.0)
        if water_ratio > 0.3:
            risk_state = "WARNING_CANDIDATE"
            confidence = min(water_ratio * 1.5, 1.0)
    elif not is_usable:
        risk_state = "UNKNOWN"
        confidence = 0.0
    else:
        risk_state = "NORMAL"
        confidence = 1.0 - water_ratio

    if state.temporal_window is not None:
        state.temporal_window.add_sample(
            risk_state=risk_state,
            confidence=confidence,
            water_ratio=water_ratio,
        )
        temporal_result = state.temporal_window.evaluate()
        temporal_state = str(temporal_result.get("temporal_risk_state", "UNKNOWN"))
    else:
        temporal_state = risk_state

    previous_state = state.current_risk_state
    state.current_risk_state = temporal_state
    state.frames_processed += 1

    if should_alert(temporal_state, previous_state):
        reason = f"Water coverage {water_ratio:.1%}"
        for webhook in config.webhooks:
            try:
                send_alert(
                    webhook,
                    site_id=site.site_id,
                    camera_id=site.camera_id,
                    risk_state=temporal_state,
                    previous_risk_state=previous_state,
                    reason=reason,
                )
                state.alerts_sent += 1
            except Exception:
                logger.exception("Failed to send webhook alert")

    return {
        "site_id": site.site_id,
        "camera_id": site.camera_id,
        "timestamp": ts,
        "health": health_record,
        "water_detection": water_record,
        "instant_risk_state": risk_state,
        "temporal_risk_state": temporal_state,
        "frames_processed": state.frames_processed,
    }


def _monitor_tick(config: MonitorConfig, state: MonitorState) -> None:
    """One iteration of the monitoring loop."""

    if state.stream_state is None or not state.stream_state.is_connected:
        if state.reconnect_failures >= config.max_reconnect_failures:
            logger.error(
                "Too many reconnect failures for %s, stopping",
                config.site.site_id,
            )
            state.running = False
            return

        logger.warning("Reconnecting stream for %s...", config.site.site_id)
        if state.stream_state is None:
            state.stream_state = StreamState()
        if reconnect_stream(state.stream_state, config.stream):
            state.reconnect_failures = 0
            logger.info("Reconnected to %s", config.site.site_id)
        else:
            state.reconnect_failures += 1
            time.sleep(config.stream.retry_delay_seconds)
            return

    frame = read_frame(state.stream_state, config.stream)
    if frame is None:
        if state.stream_state.consecutive_failures >= config.stream.max_retries:
            logger.warning(
                "Stream read failures for %s, will reconnect",
                config.site.site_id,
            )
            close_stream(state.stream_state)
        time.sleep(0.1)
        return

    process_frame(frame, config, state)


def build_monitor_config(
    site: SiteConfig,
    stream_url: str,
    *,
    webhook_urls: list[str] | None = None,
    target_fps: float = 1.0,
    window_minutes: int = 10,
) -> MonitorConfig:
    """Build a MonitorConfig from a site config and stream URL."""

    webhooks = [WebhookConfig(url=u) for u in (webhook_urls or [])]
    return MonitorConfig(
        site=site,
        stream=StreamConfig(url=stream_url, target_fps=target_fps),
        temporal_config=TemporalConfig(window_minutes=window_minutes),
        webhooks=webhooks,
    )

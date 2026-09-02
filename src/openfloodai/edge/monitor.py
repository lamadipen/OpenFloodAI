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

from openfloodai.alerts.buffer import (
    BufferConfig,
    BufferState,
    buffer_alert,
    create_buffer,
    flush_buffer,
    should_flush,
)
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

_RISK_LEVELS: dict[str, int] = {
    "UNKNOWN": -1,
    "NORMAL": 0,
    "WATCH": 1,
    "WARNING_CANDIDATE": 2,
}


class MonitorError(RuntimeError):
    """Raised when the monitoring loop cannot proceed."""


@dataclass
class DataSourceCache:
    """Cached results from external data source queries."""

    earthquake: dict[str, object] | None = None
    eonet: dict[str, object] | None = None
    precipitation: dict[str, object] | None = None
    reliefweb: dict[str, object] | None = None
    usgs_water: dict[str, object] | None = None
    dhm_nepal: dict[str, object] | None = None
    escalation_reasons: list[str] = field(default_factory=list)
    external_risk_state: str = "NORMAL"
    last_fetch: float = 0.0
    sources_available: int = 0


@dataclass
class MonitorConfig:
    """Full configuration for the monitoring loop."""

    site: SiteConfig
    stream: StreamConfig
    water_thresholds: WaterThresholds = field(default_factory=WaterThresholds)
    health_thresholds: HealthThresholds = field(default_factory=HealthThresholds)
    temporal_config: TemporalConfig = field(default_factory=TemporalConfig)
    webhooks: list[WebhookConfig] = field(default_factory=list)
    buffer_config: BufferConfig | None = None
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
    data_sources: DataSourceCache = field(default_factory=DataSourceCache)
    alert_buffer_state: BufferState | None = None


def create_monitor(config: MonitorConfig) -> MonitorState:
    """Create and initialize monitor state for a site."""

    buf_state: BufferState | None = None
    if config.buffer_config is not None:
        _, buf_state = create_buffer(config.buffer_config)

    return MonitorState(
        temporal_window=TemporalWindow(config=config.temporal_config),
        alert_buffer_state=buf_state,
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

    risk_state = _apply_external_escalation(risk_state, state.data_sources)

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
        reason = _build_alert_reason(water_ratio, state.data_sources)
        for webhook in config.webhooks:
            try:
                result = send_alert(
                    webhook,
                    site_id=site.site_id,
                    camera_id=site.camera_id,
                    risk_state=temporal_state,
                    previous_risk_state=previous_state,
                    reason=reason,
                )
                if result.get("delivered"):
                    state.alerts_sent += 1
                elif config.buffer_config is not None and state.alert_buffer_state is not None:
                    buffer_alert(
                        config.buffer_config,
                        state.alert_buffer_state,
                        webhook=webhook,
                        site_id=site.site_id,
                        camera_id=site.camera_id,
                        risk_state=temporal_state,
                        previous_risk_state=previous_state,
                        reason=reason,
                        timestamp=ts,
                    )
            except Exception:
                logger.exception("Failed to send webhook alert")
                if config.buffer_config is not None and state.alert_buffer_state is not None:
                    try:
                        buffer_alert(
                            config.buffer_config,
                            state.alert_buffer_state,
                            webhook=webhook,
                            site_id=site.site_id,
                            camera_id=site.camera_id,
                            risk_state=temporal_state,
                            previous_risk_state=previous_state,
                            reason=reason,
                            timestamp=ts,
                        )
                    except Exception:
                        logger.exception("Failed to buffer alert")

    return {
        "site_id": site.site_id,
        "camera_id": site.camera_id,
        "timestamp": ts,
        "health": health_record,
        "water_detection": water_record,
        "instant_risk_state": risk_state,
        "temporal_risk_state": temporal_state,
        "frames_processed": state.frames_processed,
        "data_sources_active": state.data_sources.sources_available,
        "external_risk_state": state.data_sources.external_risk_state,
    }


def fetch_data_sources(site: SiteConfig) -> DataSourceCache:
    """Query all available external data sources for a site.

    Each source is fetched independently; failures are logged and skipped.
    """

    cache = DataSourceCache(last_fetch=time.monotonic())
    reasons: list[str] = []
    ext_state = "NORMAL"

    if site.latitude is not None and site.longitude is not None:
        cache.earthquake = _fetch_earthquake(site.latitude, site.longitude)
        if cache.earthquake is not None:
            cache.sources_available += 1
            eq_state, eq_reasons = _assess_earthquake(cache.earthquake)
            if _risk_level(eq_state) > _risk_level(ext_state):
                ext_state = eq_state
            reasons.extend(eq_reasons)

        cache.eonet = _fetch_eonet(site.latitude, site.longitude)
        if cache.eonet is not None:
            cache.sources_available += 1
            eo_state, eo_reasons = _assess_eonet_cache(cache.eonet)
            if _risk_level(eo_state) > _risk_level(ext_state):
                ext_state = eo_state
            reasons.extend(eo_reasons)

        cache.precipitation = _fetch_precipitation(site.latitude, site.longitude)
        if cache.precipitation is not None:
            cache.sources_available += 1
            pr_state, pr_reasons = _assess_precipitation_cache(cache.precipitation)
            if _risk_level(pr_state) > _risk_level(ext_state):
                ext_state = pr_state
            reasons.extend(pr_reasons)

    cache.reliefweb = _fetch_reliefweb()
    if cache.reliefweb is not None:
        cache.sources_available += 1
        rw_state, rw_reasons = _assess_reliefweb_cache(cache.reliefweb)
        if _risk_level(rw_state) > _risk_level(ext_state):
            ext_state = rw_state
        reasons.extend(rw_reasons)

    if site.usgs_site_number is not None:
        cache.usgs_water = _fetch_usgs_water(
            site.usgs_site_number,
            site.flood_stage_ft,
        )
        if cache.usgs_water is not None:
            cache.sources_available += 1
            us_state, us_reasons = _assess_usgs_cache(cache.usgs_water, site.flood_stage_ft)
            if _risk_level(us_state) > _risk_level(ext_state):
                ext_state = us_state
            reasons.extend(us_reasons)

    cache.dhm_nepal = _fetch_dhm_nepal()
    if cache.dhm_nepal is not None:
        cache.sources_available += 1
        dh_state, dh_reasons = _assess_dhm_cache(cache.dhm_nepal)
        if _risk_level(dh_state) > _risk_level(ext_state):
            ext_state = dh_state
        reasons.extend(dh_reasons)

    cache.external_risk_state = ext_state
    cache.escalation_reasons = reasons

    logger.info(
        "Data sources refreshed for %s: %d sources, external_state=%s",
        site.site_id,
        cache.sources_available,
        ext_state,
    )

    return cache


def _monitor_tick(config: MonitorConfig, state: MonitorState) -> None:
    """One iteration of the monitoring loop."""

    now = time.monotonic()
    if now - state.last_data_source_fetch >= config.data_source_interval_seconds:
        state.data_sources = fetch_data_sources(config.site)
        state.last_data_source_fetch = now

    if (
        config.buffer_config is not None
        and state.alert_buffer_state is not None
        and should_flush(config.buffer_config, state.alert_buffer_state)
    ):
        delivered = flush_buffer(config.buffer_config, state.alert_buffer_state)
        if delivered > 0:
            state.alerts_sent += delivered
            logger.info("Flushed %d buffered alerts", delivered)

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


def _risk_level(state: str) -> int:
    return _RISK_LEVELS.get(state, -1)


def _apply_external_escalation(
    visual_state: str,
    cache: DataSourceCache,
) -> str:
    """Escalate visual risk based on external data sources."""

    if _risk_level(cache.external_risk_state) > _risk_level(visual_state):
        return cache.external_risk_state
    return visual_state


def _build_alert_reason(
    water_ratio: float,
    cache: DataSourceCache,
) -> str:
    parts = [f"Water coverage {water_ratio:.1%}"]
    if cache.escalation_reasons:
        parts.extend(cache.escalation_reasons[:3])
    return "; ".join(parts)


def _fetch_earthquake(
    lat: float,
    lon: float,
) -> dict[str, object] | None:
    try:
        from openfloodai.data_sources.usgs_earthquake import (
            assess_seismic_flood_risk,
            fetch_nearby_earthquakes,
        )

        quakes = fetch_nearby_earthquakes(lat, lon)
        return assess_seismic_flood_risk(quakes)
    except Exception:
        logger.debug("Earthquake data source unavailable", exc_info=True)
        return None


def _fetch_eonet(
    lat: float,
    lon: float,
) -> dict[str, object] | None:
    try:
        from openfloodai.data_sources.nasa_eonet import (
            fetch_events_near,
            summarize_events,
        )

        events = fetch_events_near(lat, lon)
        return summarize_events(events)
    except Exception:
        logger.debug("EONET data source unavailable", exc_info=True)
        return None


def _fetch_precipitation(
    lat: float,
    lon: float,
) -> dict[str, object] | None:
    try:
        from openfloodai.data_sources.open_meteo import fetch_precipitation

        return fetch_precipitation(lat, lon)
    except Exception:
        logger.debug("Precipitation data source unavailable", exc_info=True)
        return None


def _fetch_reliefweb() -> dict[str, object] | None:
    try:
        from openfloodai.data_sources.reliefweb import (
            fetch_flood_reports,
            summarize_reports,
        )

        reports = fetch_flood_reports(country="Nepal")
        return summarize_reports(reports)
    except Exception:
        logger.debug("ReliefWeb data source unavailable", exc_info=True)
        return None


def _fetch_usgs_water(
    site_number: str,
    flood_stage_ft: float | None,
) -> dict[str, object] | None:
    try:
        from openfloodai.data_sources.usgs_water import fetch_site_conditions

        result = fetch_site_conditions(site_number)
        if flood_stage_ft is not None:
            result["flood_stage_ft"] = flood_stage_ft
        return result
    except Exception:
        logger.debug("USGS water data source unavailable", exc_info=True)
        return None


def _assess_earthquake(
    data: dict[str, object],
) -> tuple[str, list[str]]:
    risk_state = str(data.get("seismic_risk_state", "NONE")).upper()
    max_mag = data.get("max_magnitude", 0)
    reasons: list[str] = []

    if risk_state in {"EXTREME", "HIGH"}:
        reasons.append(f"M{max_mag} earthquake -- GLOF/landslide risk")
        return "WARNING_CANDIDATE", reasons
    if risk_state == "MODERATE":
        reasons.append(f"M{max_mag} earthquake -- monitoring for secondary flooding")
        return "WATCH", reasons
    return "NORMAL", reasons


def _assess_eonet_cache(
    data: dict[str, object],
) -> tuple[str, list[str]]:
    flood_count = data.get("flood_count", 0)
    landslide_count = data.get("landslide_count", 0)
    storm_count = data.get("storm_count", 0)
    reasons: list[str] = []

    if isinstance(flood_count, int) and flood_count > 0:
        reasons.append(f"NASA EONET: {flood_count} active flood event(s)")
        return "WARNING_CANDIDATE", reasons
    if isinstance(landslide_count, int) and landslide_count > 0:
        reasons.append(f"NASA EONET: {landslide_count} landslide event(s)")
        return "WATCH", reasons
    if isinstance(storm_count, int) and storm_count > 0:
        reasons.append(f"NASA EONET: {storm_count} severe storm(s)")
        return "WATCH", reasons
    return "NORMAL", reasons


def _assess_precipitation_cache(
    data: dict[str, object],
) -> tuple[str, list[str]]:
    total_mm = data.get("precipitation_sum_mm")
    reasons: list[str] = []

    if not isinstance(total_mm, (int, float)):
        return "NORMAL", reasons
    if total_mm >= 50.0:
        reasons.append(f"Heavy precipitation forecast: {total_mm:.0f}mm")
        return "WATCH", reasons
    if total_mm >= 25.0:
        reasons.append(f"Moderate precipitation forecast: {total_mm:.0f}mm")
        return "WATCH", reasons
    return "NORMAL", reasons


def _assess_reliefweb_cache(
    data: dict[str, object],
) -> tuple[str, list[str]]:
    report_state = str(data.get("report_state", "CLEAR")).upper()
    report_count = data.get("report_count", 0)
    reasons: list[str] = []

    if report_state == "ACTIVE_DISASTER":
        if isinstance(report_count, int) and report_count >= 5:
            reasons.append(f"ReliefWeb: {report_count} humanitarian reports -- major disaster")
            return "WARNING_CANDIDATE", reasons
        reasons.append("ReliefWeb: active disaster reports")
        return "WATCH", reasons
    return "NORMAL", reasons


def _assess_usgs_cache(
    data: dict[str, object],
    flood_stage_ft: float | None,
) -> tuple[str, list[str]]:
    gage_height = data.get("gage_height_ft")
    reasons: list[str] = []

    if not isinstance(gage_height, (int, float)):
        return "NORMAL", reasons
    if flood_stage_ft is None or flood_stage_ft <= 0:
        return "NORMAL", reasons

    ratio = gage_height / flood_stage_ft
    if ratio >= 0.9:
        reasons.append(f"USGS gage at {ratio:.0%} of flood stage ({gage_height:.1f}ft)")
        return "WARNING_CANDIDATE", reasons
    if ratio >= 0.7:
        reasons.append(f"USGS gage at {ratio:.0%} of flood stage ({gage_height:.1f}ft)")
        return "WATCH", reasons
    return "NORMAL", reasons


def _fetch_dhm_nepal() -> dict[str, object] | None:
    try:
        from openfloodai.data_sources.dhm_nepal import (
            assess_dhm_flood_risk,
            fetch_flood_bulletin,
        )

        stations = fetch_flood_bulletin()
        return assess_dhm_flood_risk(stations)
    except Exception:
        logger.debug("DHM Nepal data source unavailable", exc_info=True)
        return None


def _assess_dhm_cache(
    data: dict[str, object],
) -> tuple[str, list[str]]:
    risk_state = str(data.get("dhm_risk_state", "NONE")).upper()
    reasons: list[str] = []
    highest = data.get("highest_risk_station")

    if risk_state == "DANGER":
        station_name = ""
        if isinstance(highest, dict):
            station_name = str(highest.get("station_name", ""))
        reasons.append(f"DHM Nepal: danger level exceeded at {station_name}")
        return "WARNING_CANDIDATE", reasons
    if risk_state == "WARNING":
        reasons.append("DHM Nepal: warning level exceeded")
        return "WATCH", reasons
    return "NORMAL", reasons

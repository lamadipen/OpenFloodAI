"""Multi-site concurrent monitoring using threading."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from openfloodai.alerts.webhook import WebhookConfig
from openfloodai.common import SiteConfig
from openfloodai.edge.monitor import (
    MonitorConfig,
    MonitorState,
    build_monitor_config,
    create_monitor,
    run_monitor,
)

logger = logging.getLogger("openfloodai.edge.multi_site")


@dataclass
class MultiSiteConfig:
    """Configuration for running multiple site monitors."""

    sites: list[SiteConfig]
    stream_urls: dict[str, str]  # site_id -> stream URL
    webhooks: list[WebhookConfig] = field(default_factory=list)
    target_fps: float = 1.0
    window_minutes: int = 10


@dataclass
class SiteThread:
    """Tracks a running site monitor thread."""

    site_id: str
    thread: threading.Thread
    config: MonitorConfig
    state: MonitorState


def run_multi_site(multi_config: MultiSiteConfig) -> dict[str, SiteThread]:
    """Start monitoring threads for all configured sites.

    Each site runs in its own daemon thread.  Returns a dict of
    site_id -> SiteThread so callers can check status.  Blocks until
    all threads complete or KeyboardInterrupt.
    """

    site_threads: dict[str, SiteThread] = {}

    for site in multi_config.sites:
        stream_url = multi_config.stream_urls.get(site.site_id)
        if stream_url is None:
            logger.warning("No stream URL for site %s, skipping", site.site_id)
            continue

        config = build_monitor_config(
            site,
            stream_url,
            webhook_urls=[w.url for w in multi_config.webhooks],
            target_fps=multi_config.target_fps,
            window_minutes=multi_config.window_minutes,
        )
        state = create_monitor(config)

        thread = threading.Thread(
            target=_run_site_safe,
            args=(config, state),
            name=f"monitor-{site.site_id}",
            daemon=True,
        )

        site_threads[site.site_id] = SiteThread(
            site_id=site.site_id,
            thread=thread,
            config=config,
            state=state,
        )

    if not site_threads:
        logger.error("No sites to monitor")
        return site_threads

    logger.info("Starting %d site monitors...", len(site_threads))
    for st in site_threads.values():
        st.thread.start()
        logger.info("Started monitor thread for %s", st.site_id)

    try:
        while any(st.thread.is_alive() for st in site_threads.values()):
            for st in site_threads.values():
                st.thread.join(timeout=1.0)
    except KeyboardInterrupt:
        logger.info("Stopping all monitors...")
        for st in site_threads.values():
            st.state.running = False
        for st in site_threads.values():
            st.thread.join(timeout=5.0)

    return site_threads


def _run_site_safe(config: MonitorConfig, state: MonitorState) -> None:
    """Run a single site monitor, catching exceptions."""

    try:
        run_monitor(config, state)
    except Exception:
        logger.exception("Monitor for %s crashed", config.site.site_id)

"""Offline alert buffer with disk persistence and automatic retry.

In field deployments -- especially in areas like Nepal's river basins
where connectivity is intermittent -- alerts may fail to deliver.  This
module buffers failed alerts as JSON files on disk and retries them when
the network comes back, ensuring that no critical flood warning is lost
even during connectivity outages.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from openfloodai.alerts.webhook import WebhookConfig, send_alert

logger = logging.getLogger("openfloodai.alerts.buffer")

_DEFAULT_BUFFER_DIR = Path("~/.openfloodai/alert_buffer").expanduser()


class AlertBufferError(RuntimeError):
    """Raised when the alert buffer encounters an unrecoverable error."""


@dataclass(frozen=True)
class BufferConfig:
    """Configuration for the offline alert buffer."""

    buffer_dir: Path = _DEFAULT_BUFFER_DIR
    max_buffered_alerts: int = 500
    max_retry_attempts: int = 10
    retry_interval_seconds: float = 60.0
    flush_batch_size: int = 10

    def __post_init__(self) -> None:
        if self.max_buffered_alerts < 1:
            raise AlertBufferError("max_buffered_alerts must be at least 1")
        if self.max_retry_attempts < 1:
            raise AlertBufferError("max_retry_attempts must be at least 1")
        if self.retry_interval_seconds <= 0:
            raise AlertBufferError("retry_interval_seconds must be positive")


@dataclass
class BufferState:
    """Mutable state for the alert buffer."""

    buffered_count: int = 0
    delivered_count: int = 0
    dropped_count: int = 0
    last_flush_attempt: float = 0.0
    last_flush_delivered: int = 0


@dataclass
class BufferedAlert:
    """A single alert waiting for delivery."""

    webhook_url: str
    webhook_secret: str
    site_id: str
    camera_id: str
    risk_state: str
    previous_risk_state: str
    reason: str
    timestamp: str
    retry_count: int = 0
    extra: dict[str, object] = field(default_factory=dict)


def create_buffer(config: BufferConfig | None = None) -> tuple[BufferConfig, BufferState]:
    """Initialize the alert buffer, creating the buffer directory."""

    cfg = config or BufferConfig()
    cfg.buffer_dir.mkdir(parents=True, exist_ok=True)
    state = BufferState()
    state.buffered_count = _count_pending(cfg)
    return cfg, state


def buffer_alert(
    config: BufferConfig,
    state: BufferState,
    *,
    webhook: WebhookConfig,
    site_id: str,
    camera_id: str,
    risk_state: str,
    previous_risk_state: str,
    reason: str,
    timestamp: str,
    extra: dict[str, object] | None = None,
) -> Path:
    """Save a failed alert to disk for later retry.

    Returns the path to the buffered alert file.
    """

    if state.buffered_count >= config.max_buffered_alerts:
        _evict_oldest(config)
        state.dropped_count += 1

    alert = BufferedAlert(
        webhook_url=webhook.url,
        webhook_secret=webhook.secret,
        site_id=site_id,
        camera_id=camera_id,
        risk_state=risk_state,
        previous_risk_state=previous_risk_state,
        reason=reason,
        timestamp=timestamp,
        extra=extra or {},
    )

    filename = f"alert_{int(time.time() * 1000)}_{site_id}.json"
    filepath = config.buffer_dir / filename

    data = {
        "webhook_url": alert.webhook_url,
        "webhook_secret": alert.webhook_secret,
        "site_id": alert.site_id,
        "camera_id": alert.camera_id,
        "risk_state": alert.risk_state,
        "previous_risk_state": alert.previous_risk_state,
        "reason": alert.reason,
        "timestamp": alert.timestamp,
        "retry_count": alert.retry_count,
        "extra": alert.extra,
    }

    filepath.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    state.buffered_count += 1

    logger.info(
        "Buffered alert for %s (%s -> %s) to %s",
        site_id,
        previous_risk_state,
        risk_state,
        filepath.name,
    )

    return filepath


def flush_buffer(
    config: BufferConfig,
    state: BufferState,
) -> int:
    """Try to deliver all buffered alerts.

    Returns the number of alerts successfully delivered.
    """

    state.last_flush_attempt = time.monotonic()
    delivered = 0

    pending = sorted(config.buffer_dir.glob("alert_*.json"))
    batch = pending[: config.flush_batch_size]

    for filepath in batch:
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt buffer file %s, removing", filepath.name)
            filepath.unlink(missing_ok=True)
            state.buffered_count = max(0, state.buffered_count - 1)
            continue

        retry_count = int(data.get("retry_count", 0))
        if retry_count >= config.max_retry_attempts:
            logger.warning(
                "Alert %s exceeded max retries (%d), dropping",
                filepath.name,
                config.max_retry_attempts,
            )
            filepath.unlink(missing_ok=True)
            state.buffered_count = max(0, state.buffered_count - 1)
            state.dropped_count += 1
            continue

        webhook = WebhookConfig(
            url=str(data.get("webhook_url", "")),
            secret=str(data.get("webhook_secret", "")),
        )

        result = send_alert(
            webhook,
            site_id=str(data.get("site_id", "")),
            camera_id=str(data.get("camera_id", "")),
            risk_state=str(data.get("risk_state", "")),
            previous_risk_state=str(data.get("previous_risk_state", "")),
            reason=str(data.get("reason", "")),
            timestamp=str(data.get("timestamp", "")),
        )

        if result.get("delivered"):
            filepath.unlink(missing_ok=True)
            delivered += 1
            state.buffered_count = max(0, state.buffered_count - 1)
            state.delivered_count += 1
            logger.info("Delivered buffered alert %s", filepath.name)
        else:
            data["retry_count"] = retry_count + 1
            filepath.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            logger.debug(
                "Retry %d failed for %s: %s",
                retry_count + 1,
                filepath.name,
                result.get("error", "unknown"),
            )

    state.last_flush_delivered = delivered
    return delivered


def should_flush(config: BufferConfig, state: BufferState) -> bool:
    """Return True if enough time has passed to attempt another flush."""

    if state.buffered_count == 0:
        return False
    elapsed = time.monotonic() - state.last_flush_attempt
    return elapsed >= config.retry_interval_seconds


def buffer_stats(config: BufferConfig, state: BufferState) -> dict[str, object]:
    """Return current buffer statistics."""

    pending = _count_pending(config)
    return {
        "buffered_count": pending,
        "delivered_count": state.delivered_count,
        "dropped_count": state.dropped_count,
        "last_flush_delivered": state.last_flush_delivered,
        "buffer_dir": str(config.buffer_dir),
    }


def _count_pending(config: BufferConfig) -> int:
    if not config.buffer_dir.exists():
        return 0
    return len(list(config.buffer_dir.glob("alert_*.json")))


def _evict_oldest(config: BufferConfig) -> None:
    pending = sorted(config.buffer_dir.glob("alert_*.json"))
    if pending:
        pending[0].unlink(missing_ok=True)
        logger.warning("Evicted oldest buffered alert %s", pending[0].name)

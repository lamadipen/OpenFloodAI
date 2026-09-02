"""Webhook alert delivery for flood risk notifications.

Sends HTTP POST requests to configured webhook URLs when risk state
changes -- enabling integration with Slack, Telegram bots, SMS gateways,
or custom dashboards used by flood monitoring operators.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime


class WebhookError(RuntimeError):
    """Raised when a webhook delivery fails."""


@dataclass(frozen=True)
class WebhookConfig:
    """Configuration for a single webhook endpoint."""

    url: str
    secret: str = ""
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.url:
            raise WebhookError("Webhook URL must not be empty")
        if self.timeout_seconds <= 0:
            raise WebhookError("timeout_seconds must be positive")


def send_alert(
    config: WebhookConfig,
    *,
    site_id: str,
    camera_id: str,
    risk_state: str,
    previous_risk_state: str,
    reason: str,
    timestamp: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Send a risk-state change alert to a webhook endpoint.

    Returns a delivery record with status and response info.
    """

    ts = timestamp or datetime.now(tz=UTC).isoformat()

    payload: dict[str, object] = {
        "event": "risk_state_change",
        "site_id": site_id,
        "camera_id": camera_id,
        "risk_state": risk_state,
        "previous_risk_state": previous_risk_state,
        "reason": reason,
        "timestamp": ts,
    }
    if extra:
        payload["extra"] = extra

    body = json.dumps(payload).encode("utf-8")
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "User-Agent": "OpenFloodAI/0.1.0",
    }
    if config.secret:
        headers["X-OpenFloodAI-Secret"] = config.secret

    request = urllib.request.Request(
        config.url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as resp:
            status_code = resp.status
            response_body = resp.read().decode("utf-8", errors="replace")[:500]
    except urllib.error.HTTPError as exc:
        return _delivery_record(
            config=config,
            site_id=site_id,
            timestamp=ts,
            success=False,
            status_code=exc.code,
            error=f"HTTP {exc.code}: {exc.reason}",
        )
    except urllib.error.URLError as exc:
        return _delivery_record(
            config=config,
            site_id=site_id,
            timestamp=ts,
            success=False,
            status_code=None,
            error=f"URL error: {exc.reason}",
        )
    except TimeoutError:
        return _delivery_record(
            config=config,
            site_id=site_id,
            timestamp=ts,
            success=False,
            status_code=None,
            error=f"Timed out after {config.timeout_seconds}s",
        )

    return _delivery_record(
        config=config,
        site_id=site_id,
        timestamp=ts,
        success=200 <= status_code < 300,
        status_code=status_code,
        error="" if 200 <= status_code < 300 else f"Unexpected status {status_code}",
        response_preview=response_body,
    )


def format_alert_message(
    *,
    site_id: str,
    risk_state: str,
    reason: str,
    water_ratio: float | None = None,
) -> str:
    """Format a human-readable alert message for notification channels."""

    icon = _risk_icon(risk_state)
    msg = f"{icon} {risk_state} at {site_id}: {reason}"
    if water_ratio is not None:
        msg += f" (water coverage: {water_ratio:.1%})"
    return msg


def should_alert(current_state: str, previous_state: str) -> bool:
    """Return True if a risk-state transition warrants an alert."""

    levels = {"NORMAL": 0, "WATCH": 1, "WARNING_CANDIDATE": 2, "UNKNOWN": -1}
    curr = levels.get(current_state, -1)
    prev = levels.get(previous_state, -1)
    return curr > prev and curr >= 1


def _risk_icon(risk_state: str) -> str:
    icons = {
        "WARNING_CANDIDATE": "[WARNING]",
        "WATCH": "[WATCH]",
        "NORMAL": "[NORMAL]",
        "UNKNOWN": "[UNKNOWN]",
    }
    return icons.get(risk_state, "[ALERT]")


def _delivery_record(
    *,
    config: WebhookConfig,
    site_id: str,
    timestamp: str,
    success: bool,
    status_code: int | None,
    error: str,
    response_preview: str = "",
) -> dict[str, object]:
    return {
        "webhook_url": config.url,
        "site_id": site_id,
        "timestamp": timestamp,
        "delivered": success,
        "status_code": status_code,
        "error": error,
        "response_preview": response_preview,
    }

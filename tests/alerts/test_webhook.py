from __future__ import annotations

import pytest

from openfloodai.alerts.webhook import (
    WebhookConfig,
    WebhookError,
    format_alert_message,
    should_alert,
)


def test_webhook_config_validates_url() -> None:
    with pytest.raises(WebhookError, match="URL must not be empty"):
        WebhookConfig(url="")


def test_webhook_config_validates_timeout() -> None:
    with pytest.raises(WebhookError, match="timeout_seconds must be positive"):
        WebhookConfig(url="https://example.com/hook", timeout_seconds=0)


def test_should_alert_escalation() -> None:
    assert should_alert("WATCH", "NORMAL") is True
    assert should_alert("WARNING_CANDIDATE", "NORMAL") is True
    assert should_alert("WARNING_CANDIDATE", "WATCH") is True


def test_should_not_alert_deescalation() -> None:
    assert should_alert("NORMAL", "WATCH") is False
    assert should_alert("WATCH", "WARNING_CANDIDATE") is False


def test_should_not_alert_same_state() -> None:
    assert should_alert("WATCH", "WATCH") is False
    assert should_alert("NORMAL", "NORMAL") is False


def test_should_not_alert_unknown() -> None:
    assert should_alert("UNKNOWN", "NORMAL") is False


def test_format_alert_message() -> None:
    msg = format_alert_message(
        site_id="koshi-chatara",
        risk_state="WARNING_CANDIDATE",
        reason="Water level rising",
    )
    assert "WARNING" in msg
    assert "koshi-chatara" in msg


def test_format_alert_message_with_ratio() -> None:
    msg = format_alert_message(
        site_id="site1",
        risk_state="WATCH",
        reason="test",
        water_ratio=0.35,
    )
    assert "35.0%" in msg


def test_webhook_config_with_secret() -> None:
    config = WebhookConfig(url="https://example.com/hook", secret="s3cret")
    assert config.secret == "s3cret"

from __future__ import annotations

import pytest

from openfloodai.evidence.hosted_sam_credentials import (
    ENV_VAR,
    CredentialError,
    HostedSamCredentials,
    mask,
)

KEY = "sk-test-0123456789abcdef"


def test_fresh_holder_has_no_key_and_no_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    status = HostedSamCredentials().status()

    assert status["configured"] is False
    assert status["masked"] is None
    assert status["upload_acknowledged"] is False


def test_status_masks_the_key_and_never_returns_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    holder = HostedSamCredentials()
    holder.set_session_key(f"  {KEY}  ")

    status = holder.status()

    assert status["configured"] is True and status["source"] == "session"
    assert str(status["masked"]).endswith(KEY[-4:])
    assert KEY not in repr(status)
    assert holder.api_key() == KEY


def test_remove_clears_the_key_and_the_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    holder = HostedSamCredentials()
    holder.set_session_key(KEY)
    holder.acknowledge_upload()

    holder.remove_session_key()

    assert holder.api_key() is None
    assert holder.status()["upload_acknowledged"] is False


def test_replacing_a_key_uses_the_new_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    holder = HostedSamCredentials()
    holder.set_session_key(KEY)
    holder.set_session_key("sk-test-replacement-9999")

    assert holder.api_key() == "sk-test-replacement-9999"


@pytest.mark.parametrize(
    "bad", ["", "short", "has space inside!!", "line\nbreak12345", "x" * 600, None, 12345678]
)
def test_unusable_keys_are_rejected_without_echoing_them(bad: object) -> None:
    with pytest.raises(CredentialError) as raised:
        HostedSamCredentials().set_session_key(bad)
    assert str(bad) not in str(raised.value) or str(bad) == ""


def test_environment_key_is_used_when_no_session_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, KEY)
    holder = HostedSamCredentials()

    assert holder.api_key() == KEY and holder.source() == "environment"
    holder.remove_session_key()  # removing the session copy cannot erase the operator's env key
    assert holder.source() == "environment"


def test_a_session_key_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "sk-env-aaaaaaaaaaaaaaaa")
    holder = HostedSamCredentials()
    holder.set_session_key(KEY)

    assert holder.api_key() == KEY and holder.source() == "session"


def test_short_keys_are_fully_hidden() -> None:
    assert mask("abcdefghij") == "•" * 8
    assert mask(None) is None

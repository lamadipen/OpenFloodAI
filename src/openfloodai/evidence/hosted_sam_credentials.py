"""Where the user's hosted-SAM API key lives while the app runs (Issue #210).

The key is held only in this process's memory, or read from an environment
variable by a local operator. It is never written to a site, manifest, run
folder, settings file, log, or browser storage, and this module never returns
it: callers get a masked hint and a configured flag. Removing it clears the
memory copy; an environment key is the operator's and can only be reported.

The upload acknowledgement lives here too, also in memory only: it must be
given again after the app restarts, and clearing the credential clears it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from threading import RLock

ENV_VAR = "OPENFLOODAI_SAM_API_KEY"
_MIN_LENGTH = 8
_MAX_LENGTH = 512


class CredentialError(ValueError):
    """The submitted key is not usable; the message never contains the key."""


class HostedSamCredentials:
    """A process-local credential holder. One instance per running server."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._session_key: str | None = None
        self._acknowledged_at: str | None = None

    def set_session_key(self, key: object) -> None:
        if not isinstance(key, str):
            raise CredentialError("Enter your API key as text.")
        cleaned = key.strip()
        if not _MIN_LENGTH <= len(cleaned) <= _MAX_LENGTH or any(
            ch.isspace() or not ch.isprintable() for ch in cleaned
        ):
            raise CredentialError("That does not look like an API key. Paste it exactly as issued.")
        with self._lock:
            self._session_key = cleaned

    def remove_session_key(self) -> None:
        with self._lock:
            self._session_key = None
            self._acknowledged_at = None

    def api_key(self) -> str | None:
        """The key for one outbound request. Only the segmentation runner calls this."""

        with self._lock:
            if self._session_key:
                return self._session_key
        env_key = os.environ.get(ENV_VAR, "").strip()
        return env_key or None

    def source(self) -> str | None:
        with self._lock:
            if self._session_key:
                return "session"
        return "environment" if os.environ.get(ENV_VAR, "").strip() else None

    def acknowledge_upload(self) -> str:
        with self._lock:
            self._acknowledged_at = datetime.now(tz=UTC).isoformat()
            return self._acknowledged_at

    def acknowledged_at(self) -> str | None:
        with self._lock:
            return self._acknowledged_at

    def status(self) -> dict[str, object]:
        """Safe to send to the browser: never the key itself."""

        key = self.api_key()
        return {
            "configured": key is not None,
            "source": self.source(),
            "masked": mask(key),
            "upload_acknowledged": self.acknowledged_at() is not None,
            "upload_acknowledged_at": self.acknowledged_at(),
        }


def mask(key: str | None) -> str | None:
    """Last four characters only, and only when the key is long enough to hide the rest."""

    if not key:
        return None
    return f"{'•' * 8}{key[-4:]}" if len(key) >= 12 else "•" * 8

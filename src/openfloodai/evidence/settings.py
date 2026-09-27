"""Global and per-site enable/disable settings for known evidence adapters.

Resolution order for one adapter, at one site: a per-site override (if the
site has one) wins; otherwise the global setting (if ever changed from the
catalog's shipped default) wins; otherwise the catalog's own is_default
applies. This mirrors an ordinary settings precedence (site > global >
built-in default) rather than introducing a new concept.

Storage is deliberately plain JSON, one file, matching the convention
already used for river registries (a file under the reference directory)
-- no database, no migrations.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openfloodai.evidence.catalog import KNOWN_ADAPTERS, default_enabled_by_id, known_adapter_ids

_SETTINGS_FILENAME = "evidence-adapter-settings.json"


class EvidenceSettingsError(ValueError):
    """Raised when adapter settings on disk or in a request are invalid."""


def _settings_path(reference_dir: Path) -> Path:
    return reference_dir / _SETTINGS_FILENAME


def read_global_adapter_overrides(reference_dir: Path) -> dict[str, bool]:
    """Read {plugin_id: enabled} overrides that differ from the catalog default.

    A missing file uses defaults -- nobody has changed anything yet. But an
    *existing* file that fails to parse is not the same as no file: it means
    someone's explicit choice (e.g. disabling this adapter) may be sitting in
    there unreadable, and silently falling back to the catalog default could
    silently re-enable something a user turned off on purpose. So this raises
    instead of guessing, unlike an unrecognized plugin_id key within an
    otherwise well-formed file, which is genuinely fine to ignore (forward/
    backward compatibility with a catalog that has since changed).
    """

    path = _settings_path(reference_dir)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceSettingsError(
            f"Could not read evidence adapter settings at {path}: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise EvidenceSettingsError(f"Evidence adapter settings at {path} must be a JSON object")
    overrides = raw.get("adapters")
    if not isinstance(overrides, dict):
        raise EvidenceSettingsError(
            f"Evidence adapter settings at {path} must have an 'adapters' object"
        )

    known_ids = known_adapter_ids()
    result: dict[str, bool] = {}
    for plugin_id, enabled in overrides.items():
        if not isinstance(plugin_id, str) or plugin_id not in known_ids:
            continue
        if not isinstance(enabled, bool):
            raise EvidenceSettingsError(
                f"Evidence adapter settings at {path}: {plugin_id!r} must be a boolean"
            )
        result[plugin_id] = enabled
    return result


def write_global_adapter_setting(reference_dir: Path, plugin_id: str, enabled: bool) -> None:
    """Persist one adapter's global enabled/disabled state.

    Written atomically (temp file + os.replace) so a crash or a concurrent
    read can never observe a half-written file -- one further way a
    previously-disabled adapter could otherwise appear to have reset.
    """

    if plugin_id not in known_adapter_ids():
        raise EvidenceSettingsError(f"Unknown plugin_id: {plugin_id!r}")

    reference_dir.mkdir(parents=True, exist_ok=True)
    overrides = read_global_adapter_overrides(reference_dir)
    overrides[plugin_id] = bool(enabled)

    path = _settings_path(reference_dir)
    payload = json.dumps({"adapters": overrides}, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(dir=reference_dir, prefix=f".{_SETTINGS_FILENAME}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def resolve_global_adapter_settings(reference_dir: Path) -> dict[str, bool]:
    """Every known adapter's effective global enabled state (default, then override)."""

    resolved = default_enabled_by_id()
    resolved.update(read_global_adapter_overrides(reference_dir))
    return resolved


def resolve_effective_adapter_settings(
    reference_dir: Path, site_overrides: Mapping[str, bool] | None = None
) -> dict[str, bool]:
    """Every known adapter's effective enabled state at one site: site > global > default."""

    resolved = resolve_global_adapter_settings(reference_dir)
    if site_overrides:
        for plugin_id, enabled in site_overrides.items():
            if plugin_id in resolved:
                resolved[plugin_id] = bool(enabled)
    return resolved


def describe_adapters_for_settings_ui(
    reference_dir: Path, site_overrides: Mapping[str, bool] | None = None
) -> list[dict[str, Any]]:
    """One row per known adapter: identity, global state, site override, and the result."""

    global_settings = resolve_global_adapter_settings(reference_dir)
    site_overrides = site_overrides or {}
    rows: list[dict[str, Any]] = []
    for adapter in KNOWN_ADAPTERS:
        site_override = site_overrides.get(adapter.plugin_id)
        effective = (
            site_override if site_override is not None else global_settings[adapter.plugin_id]
        )
        row = adapter.to_dict()
        row["global_enabled"] = global_settings[adapter.plugin_id]
        row["site_override"] = site_override
        row["effective_enabled"] = effective
        rows.append(row)
    return rows

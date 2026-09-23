from __future__ import annotations

from pathlib import Path

import pytest

from openfloodai.evidence.settings import (
    EvidenceSettingsError,
    describe_adapters_for_settings_ui,
    read_global_adapter_overrides,
    resolve_effective_adapter_settings,
    resolve_global_adapter_settings,
    write_global_adapter_setting,
)

_PLUGIN_ID = "pixel_change_region_v1"


def test_resolve_global_adapter_settings_defaults_to_catalog(tmp_path: Path) -> None:
    resolved = resolve_global_adapter_settings(tmp_path)

    assert resolved[_PLUGIN_ID] is True


def test_write_global_adapter_setting_persists_and_reads_back(tmp_path: Path) -> None:
    write_global_adapter_setting(tmp_path, _PLUGIN_ID, False)

    assert read_global_adapter_overrides(tmp_path) == {_PLUGIN_ID: False}
    assert resolve_global_adapter_settings(tmp_path)[_PLUGIN_ID] is False


def test_write_global_adapter_setting_rejects_unknown_plugin_id(tmp_path: Path) -> None:
    with pytest.raises(EvidenceSettingsError):
        write_global_adapter_setting(tmp_path, "not-a-real-adapter", True)


def test_read_global_adapter_overrides_ignores_a_missing_file(tmp_path: Path) -> None:
    assert read_global_adapter_overrides(tmp_path) == {}


def test_read_global_adapter_overrides_ignores_malformed_json(tmp_path: Path) -> None:
    (tmp_path / "evidence-adapter-settings.json").write_text("not json", encoding="utf-8")

    assert read_global_adapter_overrides(tmp_path) == {}


def test_read_global_adapter_overrides_ignores_unknown_plugin_ids(tmp_path: Path) -> None:
    (tmp_path / "evidence-adapter-settings.json").write_text(
        '{"adapters": {"not-a-real-adapter": true, "pixel_change_region_v1": false}}',
        encoding="utf-8",
    )

    assert read_global_adapter_overrides(tmp_path) == {_PLUGIN_ID: False}


def test_resolve_effective_adapter_settings_site_override_wins_over_global(tmp_path: Path) -> None:
    write_global_adapter_setting(tmp_path, _PLUGIN_ID, False)

    effective = resolve_effective_adapter_settings(tmp_path, site_overrides={_PLUGIN_ID: True})

    assert effective[_PLUGIN_ID] is True


def test_resolve_effective_adapter_settings_falls_back_to_global_without_a_site_override(
    tmp_path: Path,
) -> None:
    write_global_adapter_setting(tmp_path, _PLUGIN_ID, False)

    assert resolve_effective_adapter_settings(tmp_path)[_PLUGIN_ID] is False


def test_describe_adapters_for_settings_ui_reports_identity_and_effective_state(
    tmp_path: Path,
) -> None:
    rows = describe_adapters_for_settings_ui(tmp_path, site_overrides={_PLUGIN_ID: False})

    assert len(rows) == 1
    row = rows[0]
    assert row["plugin_id"] == _PLUGIN_ID
    assert row["is_default"] is True
    assert row["global_enabled"] is True
    assert row["site_override"] is False
    assert row["effective_enabled"] is False


def test_describe_adapters_for_settings_ui_without_a_site_override(tmp_path: Path) -> None:
    rows = describe_adapters_for_settings_ui(tmp_path)

    row = rows[0]
    assert row["site_override"] is None
    assert row["effective_enabled"] is True

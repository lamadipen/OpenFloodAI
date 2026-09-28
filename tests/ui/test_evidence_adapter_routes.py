from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from test_home_server import get_json, post_json, serve_home_ui

_PLUGIN_ID = "pixel_change_region_v1"


def _write_site(sites_dir: Path, folder_name: str = "site-one") -> Path:
    site_dir = sites_dir / folder_name
    (site_dir / "configs").mkdir(parents=True)
    config_path = site_dir / "configs" / f"{folder_name}.json"
    config_path.write_text(
        json.dumps(
            {
                "site_id": "site-demo-01",
                "camera_id": "camera-demo-01",
                "site_name": "Demo Site",
                "input_type": "local_video",
            }
        ),
        encoding="utf-8",
    )
    return site_dir


def test_get_evidence_adapters_reports_the_catalog_default(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    with serve_home_ui(sites_dir) as base_url:
        payload = get_json(f"{base_url}/api/evidence-adapters")

    assert len(payload["adapters"]) == 1
    row = payload["adapters"][0]
    assert row["plugin_id"] == _PLUGIN_ID
    assert row["is_default"] is True
    assert row["global_enabled"] is True
    assert row["site_override"] is None
    assert row["effective_enabled"] is True


def test_set_global_adapter_setting_updates_the_default(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    with serve_home_ui(sites_dir) as base_url:
        result = post_json(
            f"{base_url}/api/set-evidence-adapter-enabled",
            {"scope": "global", "plugin_id": _PLUGIN_ID, "enabled": False},
        )
        followup = get_json(f"{base_url}/api/evidence-adapters")

    assert result["success"] is True
    row = result["adapters"][0]
    assert row["global_enabled"] is False
    assert row["effective_enabled"] is False
    assert followup["adapters"][0]["global_enabled"] is False


def test_set_site_override_wins_over_a_disabled_global_default(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    _write_site(sites_dir)

    with serve_home_ui(sites_dir) as base_url:
        post_json(
            f"{base_url}/api/set-evidence-adapter-enabled",
            {"scope": "global", "plugin_id": _PLUGIN_ID, "enabled": False},
        )
        result = post_json(
            f"{base_url}/api/set-evidence-adapter-enabled",
            {
                "scope": "site",
                "folder_name": "site-one",
                "plugin_id": _PLUGIN_ID,
                "enabled": True,
            },
        )
        site_view = get_json(f"{base_url}/api/evidence-adapters?folder_name=site-one")
        global_view = get_json(f"{base_url}/api/evidence-adapters")

    row = result["adapters"][0]
    assert row["global_enabled"] is False
    assert row["site_override"] is True
    assert row["effective_enabled"] is True
    assert site_view["adapters"][0]["effective_enabled"] is True
    # The global default, and any other site, is unaffected.
    assert global_view["adapters"][0]["effective_enabled"] is False


def test_set_site_override_can_be_cleared_with_a_null_enabled(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    _write_site(sites_dir)

    with serve_home_ui(sites_dir) as base_url:
        post_json(
            f"{base_url}/api/set-evidence-adapter-enabled",
            {
                "scope": "site",
                "folder_name": "site-one",
                "plugin_id": _PLUGIN_ID,
                "enabled": False,
            },
        )
        result = post_json(
            f"{base_url}/api/set-evidence-adapter-enabled",
            {
                "scope": "site",
                "folder_name": "site-one",
                "plugin_id": _PLUGIN_ID,
                "enabled": None,
            },
        )

    row = result["adapters"][0]
    assert row["site_override"] is None
    assert row["effective_enabled"] is True  # back to following the (default) global setting


def test_set_evidence_adapter_enabled_rejects_a_null_enabled_for_global_scope(
    tmp_path: Path,
) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    with serve_home_ui(sites_dir) as base_url:
        result = post_json(
            f"{base_url}/api/set-evidence-adapter-enabled",
            {"scope": "global", "plugin_id": _PLUGIN_ID, "enabled": None},
        )
    assert result["success"] is False


def test_set_evidence_adapter_enabled_rejects_an_unknown_scope(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    with serve_home_ui(sites_dir) as base_url:
        result = post_json(
            f"{base_url}/api/set-evidence-adapter-enabled",
            {"scope": "not-a-real-scope", "plugin_id": _PLUGIN_ID, "enabled": True},
        )
    assert result["success"] is False


def test_set_evidence_adapter_enabled_requires_folder_name_for_site_scope(
    tmp_path: Path,
) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    with serve_home_ui(sites_dir) as base_url:
        result = post_json(
            f"{base_url}/api/set-evidence-adapter-enabled",
            {"scope": "site", "plugin_id": _PLUGIN_ID, "enabled": True},
        )
    assert result["success"] is False


def test_get_evidence_adapters_reports_404_for_an_unknown_site(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    with serve_home_ui(sites_dir) as base_url:
        with pytest.raises(HTTPError) as excinfo:
            get_json(f"{base_url}/api/evidence-adapters?folder_name=does-not-exist")
    assert excinfo.value.code == 404

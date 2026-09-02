from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.common.site_config import (
    SiteConfig,
    SiteConfigError,
    find_site,
    load_site_config,
    save_site_config,
)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_valid_config(tmp_path: Path) -> None:
    config_file = tmp_path / "sites.json"
    _write_json(
        config_file,
        [
            {
                "site_id": "s1",
                "camera_id": "c1",
                "latitude": 38.9,
                "longitude": -77.0,
                "usgs_site_number": "01646500",
            },
        ],
    )
    configs = load_site_config(config_file)
    assert len(configs) == 1
    assert configs[0].site_id == "s1"
    assert configs[0].usgs_site_number == "01646500"
    assert configs[0].flood_stage_ft is None


def test_load_multiple_sites(tmp_path: Path) -> None:
    config_file = tmp_path / "sites.json"
    _write_json(
        config_file,
        [
            {"site_id": "s1", "camera_id": "c1", "latitude": 0.0, "longitude": 0.0},
            {"site_id": "s2", "camera_id": "c2", "latitude": 1.0, "longitude": 1.0},
        ],
    )
    configs = load_site_config(config_file)
    assert len(configs) == 2


def test_load_rejects_non_list(tmp_path: Path) -> None:
    config_file = tmp_path / "sites.json"
    _write_json(config_file, {"site_id": "s1"})
    with pytest.raises(SiteConfigError, match="JSON array"):
        load_site_config(config_file)


def test_load_rejects_non_dict_entry(tmp_path: Path) -> None:
    config_file = tmp_path / "sites.json"
    _write_json(config_file, ["not-a-dict"])
    with pytest.raises(SiteConfigError, match="must be an object"):
        load_site_config(config_file)


def test_load_rejects_invalid_fields(tmp_path: Path) -> None:
    config_file = tmp_path / "sites.json"
    _write_json(config_file, [{"site_id": "s1", "bad_field": True}])
    with pytest.raises(SiteConfigError, match="invalid fields"):
        load_site_config(config_file)


def test_load_missing_file() -> None:
    with pytest.raises(SiteConfigError, match="Cannot read"):
        load_site_config(Path("/nonexistent/sites.json"))


def test_load_invalid_json(tmp_path: Path) -> None:
    config_file = tmp_path / "sites.json"
    config_file.write_text("{bad json", encoding="utf-8")
    with pytest.raises(SiteConfigError, match="Invalid JSON"):
        load_site_config(config_file)


def test_save_and_reload(tmp_path: Path) -> None:
    config_file = tmp_path / "sub" / "sites.json"
    original = [
        SiteConfig(
            site_id="s1",
            camera_id="c1",
            latitude=30.0,
            longitude=-97.0,
            usgs_site_number="08158000",
            flood_stage_ft=21.0,
        ),
    ]
    save_site_config(original, config_file)
    assert config_file.exists()
    reloaded = load_site_config(config_file)
    assert reloaded[0].site_id == "s1"
    assert reloaded[0].flood_stage_ft == 21.0


def test_find_site_returns_match() -> None:
    configs = [
        SiteConfig(site_id="a", camera_id="c1", latitude=0.0, longitude=0.0),
        SiteConfig(site_id="b", camera_id="c2", latitude=1.0, longitude=1.0),
    ]
    result = find_site(configs, "b")
    assert result is not None
    assert result.camera_id == "c2"


def test_find_site_returns_none_for_missing() -> None:
    configs = [
        SiteConfig(site_id="a", camera_id="c1", latitude=0.0, longitude=0.0),
    ]
    assert find_site(configs, "nope") is None


def test_site_config_is_frozen() -> None:
    cfg = SiteConfig(site_id="s", camera_id="c", latitude=0.0, longitude=0.0)
    with pytest.raises(AttributeError):
        cfg.site_id = "other"  # type: ignore[misc]

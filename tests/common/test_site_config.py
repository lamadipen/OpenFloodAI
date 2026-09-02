from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.common.site_config import (
    ReferenceRegion,
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


def test_load_single_object_auto_wrapped(tmp_path: Path) -> None:
    config_file = tmp_path / "site.json"
    _write_json(config_file, {"site_id": "s1", "camera_id": "c1"})
    configs = load_site_config(config_file)
    assert len(configs) == 1
    assert configs[0].site_id == "s1"


def test_load_rejects_non_dict_entry(tmp_path: Path) -> None:
    config_file = tmp_path / "sites.json"
    _write_json(config_file, ["not-a-dict"])
    with pytest.raises(SiteConfigError, match="must be an object"):
        load_site_config(config_file)


def test_load_rejects_unsupported_fields(tmp_path: Path) -> None:
    config_file = tmp_path / "sites.json"
    _write_json(
        config_file,
        [{"site_id": "s1", "camera_id": "c1", "bad_field": True}],
    )
    with pytest.raises(SiteConfigError, match="unsupported"):
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


def test_save_omits_none_and_empty(tmp_path: Path) -> None:
    config_file = tmp_path / "sites.json"
    configs = [SiteConfig(site_id="s1", camera_id="c1")]
    save_site_config(configs, config_file)
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert "latitude" not in data[0]
    assert "site_name" not in data[0]


def test_find_site_returns_match() -> None:
    configs = [
        SiteConfig(site_id="a", camera_id="c1"),
        SiteConfig(site_id="b", camera_id="c2"),
    ]
    result = find_site(configs, "b")
    assert result is not None
    assert result.camera_id == "c2"


def test_find_site_returns_none_for_missing() -> None:
    configs = [
        SiteConfig(site_id="a", camera_id="c1"),
    ]
    assert find_site(configs, "nope") is None


def test_site_config_is_frozen() -> None:
    cfg = SiteConfig(site_id="s", camera_id="c")
    with pytest.raises(AttributeError):
        cfg.site_id = "other"  # type: ignore[misc]


def test_unified_config_has_all_fields() -> None:
    cfg = SiteConfig(
        site_id="test",
        camera_id="cam",
        latitude=27.7,
        longitude=85.3,
        site_name="Test River",
        public_location="Test Town",
        description="A test site",
        input_type="camera_stream",
        reference_region=ReferenceRegion(x=0, y=50, width=100, height=50),
        privacy_notes="Test only",
        usgs_site_number="01646500",
        nws_zone="MDZ013",
        flood_stage_ft=10.0,
    )
    assert cfg.site_id == "test"
    assert cfg.latitude == 27.7
    assert cfg.site_name == "Test River"
    assert cfg.input_type == "camera_stream"
    assert cfg.reference_region is not None
    assert cfg.usgs_site_number == "01646500"


def test_load_with_reference_region(tmp_path: Path) -> None:
    config_file = tmp_path / "site.json"
    _write_json(
        config_file,
        {
            "site_id": "s1",
            "camera_id": "c1",
            "input_type": "local_video",
            "reference_region": {"x": 10, "y": 20, "width": 30, "height": 40},
        },
    )
    configs = load_site_config(config_file)
    region = configs[0].reference_region
    assert region is not None
    assert region.x == 10
    assert region.width == 30

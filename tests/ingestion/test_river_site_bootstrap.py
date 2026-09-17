from __future__ import annotations

import json
from pathlib import Path

from openfloodai.ingestion.river_site_bootstrap import bootstrap_camera_site


def test_bootstrap_creates_new_site_when_folder_absent(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    result = bootstrap_camera_site(
        sites_base_dir=sites_dir,
        folder_name="colorado-river-cameo",
        camera_id="CO_Colorado_River_near_Cameo",
        site_name="Colorado River near Cameo",
    )

    assert result.status == "created"
    config_path = sites_dir / "colorado-river-cameo" / "configs" / "colorado-river-cameo.json"
    assert config_path.is_file()
    config = json.loads(config_path.read_text())
    assert config["camera_id"] == "CO_Colorado_River_near_Cameo"


def test_bootstrap_reuses_existing_site_with_same_camera_id_without_modifying_it(
    tmp_path: Path,
) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    bootstrap_camera_site(
        sites_base_dir=sites_dir,
        folder_name="colorado-river-cameo",
        camera_id="CO_Colorado_River_near_Cameo",
        site_name="Colorado River near Cameo",
    )
    config_path = sites_dir / "colorado-river-cameo" / "configs" / "colorado-river-cameo.json"
    config_path.write_text(
        config_path.read_text().replace('"broad public location only."', '"custom note kept."')
    )
    before = config_path.read_text()

    result = bootstrap_camera_site(
        sites_base_dir=sites_dir,
        folder_name="colorado-river-cameo",
        camera_id="CO_Colorado_River_near_Cameo",
        site_name="Colorado River near Cameo",
    )

    assert result.status == "reused"
    assert config_path.read_text() == before


def test_bootstrap_reports_conflict_on_mismatched_camera_id_without_touching_config(
    tmp_path: Path,
) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    bootstrap_camera_site(
        sites_base_dir=sites_dir,
        folder_name="colorado-river-cameo",
        camera_id="CO_Colorado_River_near_Cameo",
        site_name="Colorado River near Cameo",
    )
    config_path = sites_dir / "colorado-river-cameo" / "configs" / "colorado-river-cameo.json"
    before = config_path.read_text()

    result = bootstrap_camera_site(
        sites_base_dir=sites_dir,
        folder_name="colorado-river-cameo",
        camera_id="SOME_OTHER_CAMERA_ID",
        site_name="Colorado River near Cameo",
    )

    assert result.status == "conflict"
    assert "different camera_id" in result.message
    assert config_path.read_text() == before


def test_bootstrap_reports_conflict_when_config_missing(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir = sites_dir / "colorado-river-cameo"
    site_dir.mkdir(parents=True)

    result = bootstrap_camera_site(
        sites_base_dir=sites_dir,
        folder_name="colorado-river-cameo",
        camera_id="CO_Colorado_River_near_Cameo",
        site_name="Colorado River near Cameo",
    )

    assert result.status == "conflict"
    assert "config is missing" in result.message

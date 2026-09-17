from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from test_home_server import get_json, get_text, serve_home_ui

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_registry(reference_dir: Path) -> None:
    rivers_dir = reference_dir / "rivers"
    rivers_dir.mkdir(parents=True)
    payload = {
        "river_id": "test-river",
        "display_name": "Test River",
        "cameras": [
            {
                "river_id": "test-river",
                "camera_id": "TEST_CAMERA_ONE",
                "nwis_id": "09999999",
                "state": "CO",
                "latitude": 40.0,
                "longitude": -105.0,
                "display_name": "Test Camera One",
                "folder_name": "test-river-one",
                "gage_relationship": "same_site",
                "timezone": "America/Denver",
            }
        ],
    }
    (rivers_dir / "test-river.json").write_text(json.dumps(payload), encoding="utf-8")


def test_river_tracker_page_loads(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    ui_path = REPO_ROOT / "tools" / "openfloodai-home-ui.html"
    with serve_home_ui(sites_dir, ui_path=ui_path) as base_url:
        status, content_type, body = get_text(f"{base_url}/river-tracker.html")

    assert status == 200
    assert "text/html" in content_type
    assert "<title>River Camera Tracker · OpenFloodAI</title>" in body


def test_api_river_tracker_returns_rows_for_registry_cameras(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    _write_registry(tmp_path / "reference")

    with serve_home_ui(sites_dir) as base_url:
        payload = get_json(f"{base_url}/api/river-tracker?river=test-river")

    assert payload["river_id"] == "test-river"
    assert len(payload["sites"]) == 1
    row = payload["sites"][0]
    assert row["camera_id"] == "TEST_CAMERA_ONE"
    assert row["camera_availability"] == "not_created"


def test_api_river_tracker_requires_river_param(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    with serve_home_ui(sites_dir) as base_url:
        with pytest.raises(HTTPError) as excinfo:
            get_json(f"{base_url}/api/river-tracker")
    assert excinfo.value.code == 400


def test_api_river_tracker_reports_404_for_unknown_river(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    (tmp_path / "reference" / "rivers").mkdir(parents=True)

    with serve_home_ui(sites_dir) as base_url:
        with pytest.raises(HTTPError) as excinfo:
            get_json(f"{base_url}/api/river-tracker?river=does-not-exist")
    assert excinfo.value.code == 404

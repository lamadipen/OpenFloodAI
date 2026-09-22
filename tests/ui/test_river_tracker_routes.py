from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from test_home_server import get_json, get_text, post_json, serve_home_ui

from openfloodai.ingestion import river_images as river
from openfloodai.ingestion import usgs_gage_data as gage

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMERA_ID = "TEST_CAMERA_ONE"


def _listing_xml() -> bytes:
    key = f"720/{CAMERA_ID}/{CAMERA_ID}___2026-06-18T19-00-00Z.jpg"
    return (
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<Contents><Key>{key}</Key><Size>10</Size></Contents>"
        "</ListBucketResult>"
    ).encode()


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


def test_api_rivers_lists_available_registries(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    _write_registry(tmp_path / "reference")

    with serve_home_ui(sites_dir) as base_url:
        payload = get_json(f"{base_url}/api/rivers")

    assert payload["rivers"] == [
        {"river_id": "test-river", "display_name": "Test River", "camera_count": 1}
    ]


def test_api_rivers_returns_empty_list_when_no_registries_exist(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    with serve_home_ui(sites_dir) as base_url:
        payload = get_json(f"{base_url}/api/rivers")

    assert payload["rivers"] == []


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


def test_bootstrap_endpoint_preview_reports_counts_without_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        assert "?" in url, "preview must not fetch any image bytes"
        return _listing_xml(), "application/xml"

    monkeypatch.setattr(river, "_fetch", fetch)
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    _write_registry(tmp_path / "reference")

    with serve_home_ui(sites_dir) as base_url:
        payload = post_json(
            f"{base_url}/api/bootstrap-river-sites",
            {
                "river": "test-river",
                "start_date": "2026-06-18",
                "end_date": "2026-06-18",
                "sampling_mode": "one_daylight_image_per_day",
                "cameras": [CAMERA_ID],
                "preview": True,
            },
        )

    assert payload["success"] is True
    assert payload["preview"]["cameras"][0]["camera_id"] == CAMERA_ID
    assert not (sites_dir / "test-river-one").exists()


def test_bootstrap_endpoint_run_creates_site_and_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jpeg = b"\xff\xd8\xff\xe0test\xff\xd9"

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        if "?" in url:
            return _listing_xml(), "application/xml"
        return jpeg, "image/jpeg"

    monkeypatch.setattr(river, "_fetch", fetch)
    monkeypatch.setattr(gage, "_fetch_json", lambda url: {"value": {"timeSeries": []}})

    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    _write_registry(tmp_path / "reference")

    with serve_home_ui(sites_dir) as base_url:
        payload = post_json(
            f"{base_url}/api/bootstrap-river-sites",
            {
                "river": "test-river",
                "start_date": "2026-06-18",
                "end_date": "2026-06-18",
                "sampling_mode": "one_daylight_image_per_day",
                "cameras": [CAMERA_ID],
                "preview": False,
            },
        )

    assert payload["success"] is True
    outcome = payload["outcomes"][0]
    assert outcome["camera_id"] == CAMERA_ID
    assert outcome["site_status"] == "created"
    assert outcome["downloaded_count"] == 1
    assert (sites_dir / "test-river-one" / "configs" / "test-river-one.json").is_file()


def test_bootstrap_endpoint_rejects_unknown_camera(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    _write_registry(tmp_path / "reference")

    with serve_home_ui(sites_dir) as base_url:
        payload = post_json(
            f"{base_url}/api/bootstrap-river-sites",
            {
                "river": "test-river",
                "start_date": "2026-06-18",
                "end_date": "2026-06-18",
                "cameras": ["NOT_A_REAL_CAMERA"],
                "preview": True,
            },
        )

    assert payload["success"] is False
    assert "Unknown camera id" in payload["message"]

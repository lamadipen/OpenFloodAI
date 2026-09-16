from __future__ import annotations

import json
from datetime import datetime
from importlib import resources
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from test_home_server import get_json, get_text, serve_home_ui

from openfloodai.ingestion import river_images as river
from openfloodai.ui import home_server


def test_downloader_and_home_have_return_navigation(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path / "sites") as base:
        assert 'href="/river-images.html"' in get_text(base + "/")[2]
        status, content_type, page = get_text(base + "/river-images.html")
    assert status == 200 and "text/html" in content_type
    assert 'href="/openfloodai-home-ui.html"' in page
    assert 'id="downloadSpinner"' in page


def test_download_endpoint_saves_separate_batches_and_serves_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def archive(slug: str, timestamp: datetime) -> tuple[str, datetime]:
        stamp = timestamp.strftime("%Y-%m-%dT%H-%M-%SZ")
        return f"{river.ARCHIVE_URL}720/{slug}/{slug}___{stamp}.jpg", timestamp

    monkeypatch.setattr(river, "archive_image", archive)
    monkeypatch.setattr(
        river, "_fetch", lambda *args, **kwargs: (b"\xff\xd8\xfftest", "image/jpeg")
    )
    sites = tmp_path / "sites"
    payload = {
        "camera_url": river.DEFAULT_CAMERA_URL,
        "local_hour": "2026-09-06 09",
        "timezone": "UTC",
        "output_root": str(tmp_path / "untrusted"),
    }
    with serve_home_ui(sites) as base:
        request = Request(
            base + "/api/download-river-images",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            result = json.load(response)
        assert result["success"] is True
        assert Path(result["output_directory"]).parent == tmp_path / "river-images"
        query = urlencode(
            {"batch_id": result["batch_id"], "filename": result["images"][0]["filename"]}
        )
        with urlopen(base + "/api/river-image?" + query) as response:
            assert response.headers.get_content_type() == "image/jpeg"
            assert response.read().startswith(b"\xff\xd8\xff")
        assert get_json(base + "/api/sites")["sites"] == []
    assert not (tmp_path / "untrusted").exists()
    assert not list(tmp_path.rglob("manifest.jsonl"))


@pytest.mark.parametrize(
    "headers, status",
    [
        ({"Content-Type": "text/plain"}, 400),
        ({"Content-Type": "application/json", "Origin": "https://other.example"}, 403),
    ],
)
def test_download_rejects_cross_origin_and_non_json_requests(
    tmp_path: Path, headers: dict[str, str], status: int
) -> None:
    with serve_home_ui(tmp_path / "sites") as base:
        request = Request(base + "/api/download-river-images", data=b"{}", headers=headers)
        with pytest.raises(HTTPError) as error:
            urlopen(request)
    assert error.value.code == status
    assert not (tmp_path / "river-images").exists()


def test_packaged_page_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "package"
    (package / "static").mkdir(parents=True)
    (package / "static" / "openfloodai-river-images.html").write_text("<h1>Packaged page</h1>")
    monkeypatch.setattr(resources, "files", lambda name: package)
    with serve_home_ui(tmp_path / "sites", ui_path=tmp_path / "absent" / "home.html") as base:
        assert get_text(base + "/river-images.html")[2] == "<h1>Packaged page</h1>"


def test_invalid_camera_request_does_not_contact_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_fetch(*args: object, **kwargs: object) -> None:
        pytest.fail("Invalid camera URLs must be rejected before any network request")

    monkeypatch.setattr(river, "_fetch", unexpected_fetch)
    with serve_home_ui(tmp_path / "sites") as base:
        request = Request(
            base + "/api/download-river-images",
            data=json.dumps({"camera_url": "http://127.0.0.1/private"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)
    assert error.value.code == 400
    assert not (tmp_path / "river-images").exists()


def test_latest_video_route_ignores_image_dates_and_supports_playback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    movie = b"fake local MP4 bytes for routing"

    def download(*, camera_url: str, output_root: Path) -> dict[str, object]:
        assert camera_url == river.DEFAULT_CAMERA_URL
        batch = output_root / ("b" * 32)
        batch.mkdir(parents=True)
        payload = {
            "success": True,
            "kind": "latest_timelapse",
            "batch_id": batch.name,
            "filename": "camera_720.mp4",
            "output_directory": str(batch),
        }
        (batch / "camera_720.mp4").write_bytes(movie)
        (batch / "download.json").write_text(json.dumps(payload))
        return payload

    monkeypatch.setattr(home_server, "download_latest_timelapse", download)
    with serve_home_ui(tmp_path / "sites") as base:
        data = {"camera_url": river.DEFAULT_CAMERA_URL, "local_hour": "invalid"}
        request = Request(
            base + "/api/download-river-timelapse",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            payload = json.load(response)
        query = urlencode({"batch_id": payload["batch_id"], "filename": payload["filename"]})
        range_request = Request(base + "/api/river-video?" + query, headers={"Range": "bytes=0-3"})
        with urlopen(range_request) as response:
            assert response.status == 206
            assert response.read() == movie[:4]
            assert response.headers["Content-Range"] == f"bytes 0-3/{len(movie)}"
        with urlopen(base + "/api/river-video?" + query + "&download=1") as response:
            assert response.read() == movie
            assert response.headers["Content-Type"] == "video/mp4"
            assert response.headers["Content-Disposition"].startswith("attachment;")
        assert get_json(base + "/api/sites")["sites"] == []


def test_create_video_route_uses_only_local_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def create(*, root: Path, source_batch_id: str) -> dict[str, object]:
        assert root == tmp_path / "river-images"
        assert source_batch_id == "a" * 32
        return {"success": True, "kind": "image_test_timelapse"}

    monkeypatch.setattr(home_server, "create_image_test_video", create)
    with serve_home_ui(tmp_path / "sites") as base:
        request = Request(
            base + "/api/create-river-test-video",
            data=json.dumps({"batch_id": "a" * 32, "output_root": "/untrusted"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            assert json.load(response)["kind"] == "image_test_timelapse"
        assert get_json(base + "/api/sites")["sites"] == []

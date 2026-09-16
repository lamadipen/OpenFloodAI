from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from test_home_server import get_json, serve_home_ui

from openfloodai.ingestion import river_images as river

SLUG = river.camera_slug(river.DEFAULT_CAMERA_URL)
JPEG = b"\xff\xd8\xff\xe0test-image\xff\xd9"


def _listing() -> bytes:
    key = f"720/{SLUG}/{SLUG}___2026-09-01T09-00-00Z.jpg"
    return (
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<Contents><Key>{key}</Key><Size>10</Size></Contents>"
        "</ListBucketResult>"
    ).encode()


def _fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
    if "?" in url:
        return _listing(), "application/xml"
    return JPEG, "image/jpeg"


def _post(base: str, path: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request) as response:
        result: dict[str, object] = json.load(response)
        return result


def test_preview_endpoint_reports_counts_without_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        assert "?" in url, "preview must not fetch any image bytes"
        return _listing(), "application/xml"

    monkeypatch.setattr(river, "_fetch", fetch)
    with serve_home_ui(tmp_path / "sites") as base:
        result = _post(
            base,
            "/api/preview-image-sequence",
            {
                "camera_url": river.DEFAULT_CAMERA_URL,
                "start_date": "2026-09-01",
                "end_date": "2026-09-01",
                "timezone": "UTC",
                "sampling_mode": "all",
            },
        )
    assert result["success"] is True
    assert result["candidate_count"] == 1
    assert result["sampled_count"] == 1
    assert result["estimated_bytes"] == 10


def test_download_endpoint_saves_into_the_site_and_lists_and_serves_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(river, "_fetch", _fetch)
    sites_dir = tmp_path / "sites"
    site_dir = sites_dir / "example-site"
    site_dir.mkdir(parents=True)

    with serve_home_ui(sites_dir) as base:
        result = _post(
            base,
            "/api/download-image-sequence",
            {
                "folder_name": "example-site",
                "camera_url": river.DEFAULT_CAMERA_URL,
                "start_date": "2026-09-01",
                "end_date": "2026-09-01",
                "timezone": "UTC",
                "sampling_mode": "all",
                "site_id": "example-site-id",
            },
        )
        assert result["success"] is True
        sequence_id = cast(str, result["sequence_id"])

        sequences = get_json(f"{base}/api/site-image-sequences?folder_name=example-site")
        assert len(sequences["sequences"]) == 1
        assert sequences["sequences"][0]["sequence_id"] == sequence_id

        records = cast("list[dict[str, str]]", result["records"])
        filename = next(
            record["filename"] for record in records if record["download_status"] == "downloaded"
        )
        query = urlencode(
            {
                "folder_name": "example-site",
                "sequence_id": sequence_id,
                "filename": filename,
            }
        )
        with urlopen(f"{base}/api/image-sequence-image?{query}") as response:
            assert response.headers.get_content_type() == "image/jpeg"
            assert response.read() == JPEG

    assert (site_dir / "inputs" / "image-sequences" / sequence_id / "images" / filename).is_file()


def test_download_endpoint_rejects_folder_outside_sites_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_fetch(*args: object, **kwargs: object) -> None:
        pytest.fail("An invalid folder_name must be rejected before any network request")

    monkeypatch.setattr(river, "_fetch", unexpected_fetch)
    with serve_home_ui(tmp_path / "sites") as base:
        with pytest.raises(HTTPError) as error:
            _post(
                base,
                "/api/download-image-sequence",
                {
                    "folder_name": "../escape",
                    "camera_url": river.DEFAULT_CAMERA_URL,
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-01",
                    "timezone": "UTC",
                    "sampling_mode": "all",
                },
            )
    assert error.value.code == 400


@pytest.mark.parametrize("path", ["/api/preview-image-sequence", "/api/download-image-sequence"])
def test_endpoints_reject_cross_origin_and_non_json_requests(tmp_path: Path, path: str) -> None:
    with serve_home_ui(tmp_path / "sites") as base:
        request = Request(
            base + path,
            data=b"{}",
            headers={"Content-Type": "text/plain"},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)
    assert error.value.code == 400


def test_site_image_sequences_returns_empty_list_for_a_site_with_none(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    (sites_dir / "example-site").mkdir(parents=True)
    with serve_home_ui(sites_dir) as base:
        result = get_json(f"{base}/api/site-image-sequences?folder_name=example-site")
    assert result["sequences"] == []


def test_image_sequence_image_rejects_unknown_files(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    (sites_dir / "example-site").mkdir(parents=True)
    with serve_home_ui(sites_dir) as base:
        query = urlencode(
            {
                "folder_name": "example-site",
                "sequence_id": "usgs-x-2026-09-01-2026-09-01",
                "filename": "x___2026-09-01T09-00-00Z.jpg",
            }
        )
        with pytest.raises(HTTPError) as error:
            urlopen(f"{base}/api/image-sequence-image?{query}")
    assert error.value.code == 404

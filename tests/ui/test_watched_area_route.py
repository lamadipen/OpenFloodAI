"""Tests for setting the watched area on a video that is already in a site."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from test_home_server import serve_home_ui

VIDEO_BYTES = b"fake mp4 bytes for a local test video"


def make_site(site_dir: Path, *, reference_region: bool = False) -> Path:
    """Build a site that already holds one video, with or without a watched area."""

    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    config: dict[str, Any] = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo River Bridge",
        "public_location": "Demo River near Example Town",
        "input_type": "local_video",
        "privacy_notes": "Keep this local.",
    }
    if reference_region:
        config["reference_region"] = {"x": 0, "y": 50, "width": 100, "height": 50}
    (site_dir / "configs" / "site-config.json").write_text(json.dumps(config), encoding="utf-8")
    (site_dir / "inputs" / "videos" / "river-001.mp4").write_bytes(VIDEO_BYTES)
    return site_dir


def read_config(site_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (site_dir / "configs" / "site-config.json").read_text(encoding="utf-8")
    )
    return payload


def post_watched_area(base_url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = Request(
        f"{base_url}/api/set-watched-area",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return int(response.status), json.loads(response.read())
    except HTTPError as error:
        return int(error.code), json.loads(error.read())


def video_url(base_url: str, folder_name: str, video_id: str) -> str:
    query = urlencode({"folder_name": folder_name, "video_id": video_id})
    return f"{base_url}/api/site-video?{query}"


def test_watched_area_is_saved_without_importing_the_video_again(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post_watched_area(
            base_url,
            {
                "folder_name": "example-site",
                "video_id": "river-001",
                "reference_region": {"x": 10, "y": 20, "width": 30, "height": 40},
            },
        )

    assert status == 200
    assert payload["success"] is True
    assert read_config(site_dir)["reference_region"] == {
        "x": 10.0,
        "y": 20.0,
        "width": 30.0,
        "height": 40.0,
    }
    videos = sorted(path.name for path in (site_dir / "inputs" / "videos").iterdir())
    assert videos == ["river-001.mp4"]


def test_saving_the_watched_area_keeps_the_other_config_fields(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")
    before = read_config(site_dir)

    with serve_home_ui(tmp_path) as base_url:
        post_watched_area(
            base_url,
            {
                "folder_name": "example-site",
                "video_id": "river-001",
                "reference_region": {"x": 5, "y": 5, "width": 10, "height": 10},
            },
        )

    after = read_config(site_dir)
    assert after.pop("reference_region") == {"x": 5.0, "y": 5.0, "width": 10.0, "height": 10.0}
    assert after == before


def test_an_existing_watched_area_is_replaced(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site", reference_region=True)

    with serve_home_ui(tmp_path) as base_url:
        status, _ = post_watched_area(
            base_url,
            {
                "folder_name": "example-site",
                "video_id": "river-001",
                "reference_region": {"x": 1, "y": 2, "width": 3, "height": 4},
            },
        )

    assert status == 200
    assert read_config(site_dir)["reference_region"] == {
        "x": 1.0,
        "y": 2.0,
        "width": 3.0,
        "height": 4.0,
    }


def test_a_missing_watched_area_is_refused(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post_watched_area(
            base_url, {"folder_name": "example-site", "video_id": "river-001"}
        )

    assert status == 400
    assert payload["success"] is False
    assert payload["message"] == "Draw the watched area on the video first."


@pytest.mark.parametrize("folder_name", ["", "../outside-site", "example-site/configs"])
def test_a_folder_outside_the_sites_directory_is_refused(tmp_path: Path, folder_name: str) -> None:
    make_site(tmp_path / "example-site")
    outside = tmp_path.parent / "outside-site" / "configs"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "site-config.json").write_text("{}", encoding="utf-8")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post_watched_area(
            base_url,
            {
                "folder_name": folder_name,
                "reference_region": {"x": 1, "y": 2, "width": 3, "height": 4},
            },
        )

    assert status == 400
    assert payload["success"] is False
    assert "must stay inside the sites directory" in payload["message"]
    assert json.loads((outside / "site-config.json").read_text(encoding="utf-8")) == {}


def test_a_site_video_is_served_so_the_browser_can_draw_on_a_frame(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        with urlopen(video_url(base_url, "example-site", "river-001"), timeout=5) as response:
            status = int(response.status)
            content_type = str(response.headers.get("Content-Type", ""))
            body = response.read()

    assert status == 200
    assert content_type == "video/mp4"
    assert body == VIDEO_BYTES


def test_a_site_video_can_be_read_in_byte_ranges(tmp_path: Path) -> None:
    """Browsers ask for ranges before they will seek in a video."""

    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        request = Request(
            video_url(base_url, "example-site", "river-001"),
            headers={"Range": "bytes=5-9"},
        )
        with urlopen(request, timeout=5) as response:
            status = int(response.status)
            content_range = str(response.headers.get("Content-Range", ""))
            body = response.read()

    assert status == 206
    assert body == VIDEO_BYTES[5:10]
    assert content_range == f"bytes 5-9/{len(VIDEO_BYTES)}"


@pytest.mark.parametrize(
    ("folder_name", "video_id"),
    [
        ("example-site", "../../../../etc/passwd"),
        ("../..", "river-001"),
        ("example-site", "site-config"),
        ("example-site", "missing-video"),
        ("", "river-001"),
    ],
)
def test_the_video_route_refuses_anything_outside_the_site_videos(
    tmp_path: Path, folder_name: str, video_id: str
) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        with pytest.raises(HTTPError) as error:
            urlopen(video_url(base_url, folder_name, video_id), timeout=5)

    assert error.value.code == 404


def test_the_site_becomes_ready_for_validation_once_the_area_is_saved(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        with urlopen(f"{base_url}/api/sites", timeout=5) as response:
            before = json.loads(response.read())["sites"][0]
        post_watched_area(
            base_url,
            {
                "folder_name": "example-site",
                "video_id": "river-001",
                "reference_region": {"x": 1, "y": 2, "width": 3, "height": 4},
            },
        )
        with urlopen(f"{base_url}/api/sites", timeout=5) as response:
            after = json.loads(response.read())["sites"][0]

    def watched_area_step(site: dict[str, Any]) -> dict[str, Any]:
        steps: list[dict[str, Any]] = site["workflow_steps"]
        return next(step for step in steps if step["key"] == "watched_area")

    assert before["reference_region_found"] is False
    assert watched_area_step(before)["status"] == "missing"
    assert watched_area_step(before)["required_for_validation"] is True
    assert before["ready_for_validation"] is False

    assert after["reference_region_found"] is True
    assert watched_area_step(after)["status"] == "complete"
    assert after["ready_for_validation"] is True


def test_saving_without_a_video_id_is_refused(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post_watched_area(
            base_url,
            {
                "folder_name": "example-site",
                "reference_region": {"x": 1, "y": 2, "width": 3, "height": 4},
            },
        )

    assert status == 400
    assert payload["success"] is False
    assert "existing video" in payload["message"]
    assert "reference_region" not in read_config(site_dir)


@pytest.mark.parametrize("video_id", ["not-a-real-video", "../river-001", "river-001.mp4"])
def test_a_video_outside_this_site_is_refused(tmp_path: Path, video_id: str) -> None:
    site_dir = make_site(tmp_path / "example-site")
    other_site = make_site(tmp_path / "other-site")
    (other_site / "inputs" / "videos" / "elsewhere-001.mp4").write_bytes(VIDEO_BYTES)

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post_watched_area(
            base_url,
            {
                "folder_name": "example-site",
                "video_id": video_id,
                "reference_region": {"x": 1, "y": 2, "width": 3, "height": 4},
            },
        )

    assert status == 400
    assert payload["success"] is False
    assert "existing video" in payload["message"]
    assert "reference_region" not in read_config(site_dir)


def test_a_video_from_another_site_is_refused(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")
    other_site = make_site(tmp_path / "other-site")
    (other_site / "inputs" / "videos" / "elsewhere-001.mp4").write_bytes(VIDEO_BYTES)

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post_watched_area(
            base_url,
            {
                "folder_name": "example-site",
                "video_id": "elsewhere-001",
                "reference_region": {"x": 1, "y": 2, "width": 3, "height": 4},
            },
        )

    assert status == 400
    assert payload["success"] is False
    assert "reference_region" not in read_config(site_dir)

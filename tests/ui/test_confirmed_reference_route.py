"""Tests for confirming a riverbank reference inside a site's watched area."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_home_server import serve_home_ui

VIDEO_BYTES = b"fake mp4 bytes for a local test video"


def make_site(site_dir: Path, *, reference_region: bool = True) -> Path:
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


def post(base_url: str, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return int(response.status), json.loads(response.read())
    except HTTPError as error:
        return int(error.code), json.loads(error.read())


def confirmed_reference_request(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "folder_name": "example-site",
        "video_id": "river-001",
        "video_time_seconds": 4.5,
        "region": {"x": 10, "y": 55, "width": 20, "height": 15},
        "normal_condition": True,
        "notes": "Clear view of the bridge pillar.",
        "markers": [],
        "status": "draft",
    }
    payload.update(overrides)
    return payload


def test_confirmed_reference_is_saved_as_draft(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url, "/api/set-confirmed-reference", confirmed_reference_request()
        )

    assert status == 200
    assert payload["success"] is True
    saved = read_config(site_dir)["confirmed_reference"]
    assert saved["status"] == "draft"
    assert saved["confirmed_at"] is None
    assert saved["site_id"] == "site-demo-01"
    assert saved["camera_id"] == "camera-demo-01"


def test_confirmed_reference_confirmed_status_sets_confirmed_at(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, _ = post(
            base_url,
            "/api/set-confirmed-reference",
            confirmed_reference_request(status="confirmed"),
        )

    assert status == 200
    saved = read_config(site_dir)["confirmed_reference"]
    assert saved["status"] == "confirmed"
    assert saved["confirmed_at"] is not None


def test_confirmed_reference_with_markers_is_saved(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, _ = post(
            base_url,
            "/api/set-confirmed-reference",
            confirmed_reference_request(
                markers=[
                    {
                        "label": "bridge pillar",
                        "region": {"x": 5, "y": 60, "width": 5, "height": 5},
                    }
                ]
            ),
        )

    assert status == 200
    saved = read_config(site_dir)["confirmed_reference"]
    assert saved["markers"] == [
        {"label": "bridge pillar", "region": {"x": 5.0, "y": 60.0, "width": 5.0, "height": 5.0}}
    ]


def test_confirmed_reference_requires_existing_watched_area(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site", reference_region=False)

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url, "/api/set-confirmed-reference", confirmed_reference_request()
        )

    assert status == 400
    assert payload["success"] is False
    assert "watched area" in payload["message"]


def test_confirmed_reference_region_outside_watched_area_is_refused(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/set-confirmed-reference",
            confirmed_reference_request(region={"x": 0, "y": 0, "width": 20, "height": 15}),
        )

    assert status == 400
    assert "watched area" in payload["message"]


def test_confirmed_reference_video_must_already_be_in_the_site(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/set-confirmed-reference",
            confirmed_reference_request(video_id="not-a-real-video"),
        )

    assert status == 400
    assert "existing video" in payload["message"]


@pytest.mark.parametrize("folder_name", ["", "../outside-site", "example-site/configs"])
def test_confirmed_reference_folder_outside_sites_directory_is_refused(
    tmp_path: Path, folder_name: str
) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/set-confirmed-reference",
            confirmed_reference_request(folder_name=folder_name),
        )

    assert status == 400
    assert "must stay inside the sites directory" in payload["message"]


def test_invalidate_confirmed_reference(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        post(
            base_url,
            "/api/set-confirmed-reference",
            confirmed_reference_request(status="confirmed"),
        )
        status, payload = post(
            base_url,
            "/api/invalidate-confirmed-reference",
            {
                "folder_name": "example-site",
                "invalidation_reason": "camera_moved",
                "notes": "Tilted after storm.",
            },
        )

    assert status == 200
    assert payload["success"] is True
    saved = read_config(site_dir)["confirmed_reference"]
    assert saved["status"] == "invalid"
    assert saved["invalidation_reason"] == "camera_moved"
    assert saved["invalidated_at"] is not None


def test_invalidate_without_existing_record_is_refused(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/invalidate-confirmed-reference",
            {"folder_name": "example-site", "invalidation_reason": "camera_moved"},
        )

    assert status == 400
    assert "no confirmed reference" in payload["message"]


def test_workflow_step_transitions_through_draft_confirmed_invalid(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    def step(sites_payload: dict[str, Any]) -> dict[str, Any]:
        steps: list[dict[str, Any]] = sites_payload["sites"][0]["workflow_steps"]
        return next(item for item in steps if item["key"] == "confirmed_reference")

    with serve_home_ui(tmp_path) as base_url:
        with urlopen(f"{base_url}/api/sites", timeout=5) as response:
            before = json.loads(response.read())
        assert step(before)["status"] == "missing"
        assert step(before)["required_for_validation"] is False

        post(base_url, "/api/set-confirmed-reference", confirmed_reference_request())
        with urlopen(f"{base_url}/api/sites", timeout=5) as response:
            after_draft = json.loads(response.read())
        assert step(after_draft)["status"] == "needs_review"

        post(
            base_url,
            "/api/set-confirmed-reference",
            confirmed_reference_request(status="confirmed"),
        )
        with urlopen(f"{base_url}/api/sites", timeout=5) as response:
            after_confirmed = json.loads(response.read())
        assert step(after_confirmed)["status"] == "complete"

        post(
            base_url,
            "/api/invalidate-confirmed-reference",
            {"folder_name": "example-site", "invalidation_reason": "bank_changed"},
        )
        with urlopen(f"{base_url}/api/sites", timeout=5) as response:
            after_invalid = json.loads(response.read())
        assert step(after_invalid)["status"] == "needs_review"

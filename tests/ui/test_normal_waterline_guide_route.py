"""Tests for saving a normal-waterline guide inside a site's watched area."""

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


def normal_waterline_guide_request(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "folder_name": "example-site",
        "video_id": "river-001",
        "video_time_seconds": 4.5,
        "id": "left_bank_normal_waterline",
        "label": "left bank normal waterline",
        "points": [{"x": 10, "y": 55}, {"x": 20, "y": 60}, {"x": 30, "y": 62}],
        "normal_condition": True,
        "notes": "Clear view of the bridge pillar.",
        "status": "draft",
    }
    payload.update(overrides)
    return payload


def test_normal_waterline_guide_is_saved_as_draft(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url, "/api/set-normal-waterline-guide", normal_waterline_guide_request()
        )

    assert status == 200
    assert payload["success"] is True
    saved = read_config(site_dir)["normal_waterline_guides"][0]
    assert saved["status"] == "draft"
    assert saved["confirmed_at"] is None
    assert saved["site_id"] == "site-demo-01"
    assert saved["camera_id"] == "camera-demo-01"


def test_normal_waterline_guide_confirmed_status_sets_confirmed_at(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, _ = post(
            base_url,
            "/api/set-normal-waterline-guide",
            normal_waterline_guide_request(status="confirmed"),
        )

    assert status == 200
    saved = read_config(site_dir)["normal_waterline_guides"][0]
    assert saved["status"] == "confirmed"
    assert saved["confirmed_at"] is not None


def test_normal_waterline_guide_requires_existing_watched_area(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site", reference_region=False)

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url, "/api/set-normal-waterline-guide", normal_waterline_guide_request()
        )

    assert status == 400
    assert payload["success"] is False
    assert "watched area" in payload["message"]


def test_normal_waterline_guide_point_outside_watched_area_is_refused(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/set-normal-waterline-guide",
            normal_waterline_guide_request(points=[{"x": 0, "y": 0}, {"x": 10, "y": 10}]),
        )

    assert status == 400
    assert "watched area" in payload["message"]


def test_normal_waterline_guide_video_must_already_be_in_the_site(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/set-normal-waterline-guide",
            normal_waterline_guide_request(video_id="not-a-real-video"),
        )

    assert status == 400
    assert "existing video" in payload["message"]


@pytest.mark.parametrize("folder_name", ["", "../outside-site", "example-site/configs"])
def test_normal_waterline_guide_folder_outside_sites_directory_is_refused(
    tmp_path: Path, folder_name: str
) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/set-normal-waterline-guide",
            normal_waterline_guide_request(folder_name=folder_name),
        )

    assert status == 400
    assert "must stay inside the sites directory" in payload["message"]


def test_invalidate_normal_waterline_guide(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        post(
            base_url,
            "/api/set-normal-waterline-guide",
            normal_waterline_guide_request(status="confirmed"),
        )
        status, payload = post(
            base_url,
            "/api/invalidate-normal-waterline-guide",
            {
                "folder_name": "example-site",
                "guide_id": "left_bank_normal_waterline",
                "invalidation_reason": "camera_moved",
                "notes": "Tilted after storm.",
            },
        )

    assert status == 200
    assert payload["success"] is True
    saved = read_config(site_dir)["normal_waterline_guides"][0]
    assert saved["status"] == "invalid"
    assert saved["invalidation_reason"] == "camera_moved"
    assert saved["invalidated_at"] is not None


def test_invalidate_without_existing_record_is_refused(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/invalidate-normal-waterline-guide",
            {
                "folder_name": "example-site",
                "guide_id": "left_bank_normal_waterline",
                "invalidation_reason": "camera_moved",
            },
        )

    assert status == 400
    assert "no normal waterline guide" in payload["message"]


def normal_waterline_guides_bulk_request(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "folder_name": "example-site",
        "video_id": "river-001",
        "guides": [
            {
                "id": "left_bank_normal_waterline",
                "label": "left bank normal waterline",
                "points": [{"x": 10, "y": 55}, {"x": 20, "y": 60}],
                "video_time_seconds": 4.5,
                "normal_condition": True,
                "notes": "",
                "status": "confirmed",
            },
            {
                "id": "right_bank_normal_waterline",
                "label": "right bank normal waterline",
                "points": [{"x": 40, "y": 55}, {"x": 50, "y": 60}],
                "video_time_seconds": 4.5,
                "normal_condition": True,
                "notes": "",
                "status": "draft",
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_set_normal_waterline_guides_saves_all_rows_in_one_request(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url, "/api/set-normal-waterline-guides", normal_waterline_guides_bulk_request()
        )

    assert status == 200
    assert payload["success"] is True
    saved = read_config(site_dir)["normal_waterline_guides"]
    assert {guide["id"]: guide["status"] for guide in saved} == {
        "left_bank_normal_waterline": "confirmed",
        "right_bank_normal_waterline": "draft",
    }


def test_set_normal_waterline_guides_requires_at_least_one_guide(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/set-normal-waterline-guides",
            normal_waterline_guides_bulk_request(guides=[]),
        )

    assert status == 400
    assert payload["success"] is False


def test_set_normal_waterline_guides_supports_invalid_status_with_reason(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/set-normal-waterline-guides",
            normal_waterline_guides_bulk_request(
                guides=[
                    {
                        "id": "left_bank_normal_waterline",
                        "label": "left bank normal waterline",
                        "points": [{"x": 10, "y": 55}, {"x": 20, "y": 60}],
                        "video_time_seconds": 4.5,
                        "normal_condition": True,
                        "notes": "",
                        "status": "invalid",
                        "invalidation_reason": "camera_moved",
                    }
                ]
            ),
        )

    assert status == 200
    assert payload["success"] is True
    saved = read_config(site_dir)["normal_waterline_guides"][0]
    assert saved["status"] == "invalid"
    assert saved["invalidation_reason"] == "camera_moved"


def test_delete_normal_waterline_guide_route(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        post(base_url, "/api/set-normal-waterline-guides", normal_waterline_guides_bulk_request())
        status, payload = post(
            base_url,
            "/api/delete-normal-waterline-guide",
            {"folder_name": "example-site", "guide_id": "left_bank_normal_waterline"},
        )

    assert status == 200
    assert payload["success"] is True
    saved = read_config(site_dir)["normal_waterline_guides"]
    assert [guide["id"] for guide in saved] == ["right_bank_normal_waterline"]


def test_delete_normal_waterline_guide_route_rejects_unknown_id(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/delete-normal-waterline-guide",
            {"folder_name": "example-site", "guide_id": "left_bank_normal_waterline"},
        )

    assert status == 400
    assert "no normal waterline guide" in payload["message"]


def test_workflow_step_transitions_through_draft_confirmed_invalid(tmp_path: Path) -> None:
    make_site(tmp_path / "example-site")

    def step(sites_payload: dict[str, Any]) -> dict[str, Any]:
        steps: list[dict[str, Any]] = sites_payload["sites"][0]["workflow_steps"]
        return next(item for item in steps if item["key"] == "normal_waterline_guide")

    with serve_home_ui(tmp_path) as base_url:
        with urlopen(f"{base_url}/api/sites", timeout=5) as response:
            before = json.loads(response.read())
        assert step(before)["status"] == "missing"
        assert step(before)["required_for_validation"] is False

        post(base_url, "/api/set-normal-waterline-guide", normal_waterline_guide_request())
        with urlopen(f"{base_url}/api/sites", timeout=5) as response:
            after_draft = json.loads(response.read())
        assert step(after_draft)["status"] == "needs_review"

        post(
            base_url,
            "/api/set-normal-waterline-guide",
            normal_waterline_guide_request(status="confirmed"),
        )
        with urlopen(f"{base_url}/api/sites", timeout=5) as response:
            after_confirmed = json.loads(response.read())
        assert step(after_confirmed)["status"] == "complete"

        post(
            base_url,
            "/api/invalidate-normal-waterline-guide",
            {
                "folder_name": "example-site",
                "guide_id": "left_bank_normal_waterline",
                "invalidation_reason": "bank_changed",
            },
        )
        with urlopen(f"{base_url}/api/sites", timeout=5) as response:
            after_invalid = json.loads(response.read())
        assert step(after_invalid)["status"] == "needs_review"

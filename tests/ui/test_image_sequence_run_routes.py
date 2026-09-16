"""Route tests for image-sequence validation runs (issue #182)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import cv2
import numpy as np
import pytest
from test_home_server import get_json, serve_home_ui

SEQUENCE_ID = "usgs-camera-demo-2026-09-01-2026-09-01-all"


def make_site(site_dir: Path, *, reference_region: bool = True) -> None:
    (site_dir / "configs").mkdir(parents=True)
    config: dict[str, object] = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo Site",
        "input_type": "local_video",
    }
    if reference_region:
        config["reference_region"] = {"x": 0, "y": 0, "width": 100, "height": 100}
    (site_dir / "configs" / "site.json").write_text(json.dumps(config), encoding="utf-8")


def write_frame(path: Path, value: int, *, bottom_third_value: int | None = None) -> None:
    frame = np.full((30, 18, 3), value, dtype=np.uint8)
    if bottom_third_value is not None:
        frame[20:, :, :] = bottom_third_value
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), frame)


def write_sequence(site_dir: Path, sequence_id: str = SEQUENCE_ID) -> None:
    sequence_dir = site_dir / "inputs" / "image-sequences" / sequence_id
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "baseline.jpg", 30)
    write_frame(images_dir / "changed.jpg", 30, bottom_third_value=220)
    records = [
        {
            "site_id": "site-demo-01",
            "camera_id": "camera-demo-01",
            "source_url": f"https://example.test/{name}",
            "captured_at_utc": captured,
            "local_time": captured,
            "filename": name,
            "file_size_bytes": 100,
            "download_status": "downloaded",
            "source_system": "usgs_nims",
        }
        for name, captured in (
            ("baseline.jpg", "2026-09-01T00:00:00+00:00"),
            ("changed.jpg", "2026-09-01T01:00:00+00:00"),
        )
    ]
    with (sequence_dir / "sequence-manifest.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def post(base_url: str, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
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


def test_run_image_sequence_validation_route_saves_a_run(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    make_site(site_dir)
    write_sequence(site_dir)

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/run-image-sequence-validation",
            {"folder_name": "example-site", "sequence_id": SEQUENCE_ID},
        )
        assert status == 200
        assert payload["success"] is True
        run_id = cast(str, payload["run_id"])
        counts = cast("dict[str, int]", payload["counts"])
        assert counts["possible_water_level_change"] == 1

        runs = get_json(
            f"{base_url}/api/image-sequence-runs?"
            f"{urlencode({'folder_name': 'example-site', 'sequence_id': SEQUENCE_ID})}"
        )
        assert len(runs["runs"]) == 1
        assert runs["runs"][0]["run_id"] == run_id

        detail = get_json(
            f"{base_url}/api/image-sequence-run-detail?"
            f"{urlencode({'folder_name': 'example-site', 'run_id': run_id})}"
        )
        assert detail["summary"]["run_id"] == run_id
        assert len(detail["records"]) == 1
        assert detail["review_images"]

        image_query = urlencode(
            {
                "folder_name": "example-site",
                "run_id": run_id,
                "filename": detail["review_images"][0],
            }
        )
        with urlopen(f"{base_url}/api/image-sequence-run-image?{image_query}") as response:
            assert response.headers.get_content_type() == "image/png"
            assert response.read()


def test_run_image_sequence_validation_requires_a_watched_area(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    make_site(site_dir, reference_region=False)
    write_sequence(site_dir)

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/run-image-sequence-validation",
            {"folder_name": "example-site", "sequence_id": SEQUENCE_ID},
        )

    assert status == 400
    assert payload["success"] is False
    assert "watched area" in cast(str, payload["message"])


def test_run_image_sequence_validation_rejects_folder_outside_sites_directory(
    tmp_path: Path,
) -> None:
    with serve_home_ui(tmp_path / "sites") as base_url:
        status, payload = post(
            base_url,
            "/api/run-image-sequence-validation",
            {"folder_name": "../escape", "sequence_id": SEQUENCE_ID},
        )

    assert status == 400
    assert payload["success"] is False


def test_image_sequence_runs_route_returns_empty_list_for_a_site_with_no_runs(
    tmp_path: Path,
) -> None:
    site_dir = tmp_path / "example-site"
    make_site(site_dir)

    with serve_home_ui(tmp_path) as base_url:
        result = get_json(
            f"{base_url}/api/image-sequence-runs?"
            f"{urlencode({'folder_name': 'example-site', 'sequence_id': SEQUENCE_ID})}"
        )

    assert result["runs"] == []


def test_image_sequence_run_detail_rejects_unknown_run(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    make_site(site_dir)

    with serve_home_ui(tmp_path) as base_url:
        with pytest.raises(HTTPError) as error:
            urlopen(
                f"{base_url}/api/image-sequence-run-detail?"
                f"{urlencode({'folder_name': 'example-site', 'run_id': 'nope'})}"
            )

    assert error.value.code == 404


def test_image_sequence_run_image_rejects_unknown_file(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    make_site(site_dir)
    write_sequence(site_dir)

    with serve_home_ui(tmp_path) as base_url:
        status, payload = post(
            base_url,
            "/api/run-image-sequence-validation",
            {"folder_name": "example-site", "sequence_id": SEQUENCE_ID},
        )
        run_id = payload["run_id"]
        query = urlencode(
            {"folder_name": "example-site", "run_id": run_id, "filename": "../../secret.png"}
        )
        with pytest.raises(HTTPError) as error:
            urlopen(f"{base_url}/api/image-sequence-run-image?{query}")

    assert status == 200
    assert error.value.code == 404

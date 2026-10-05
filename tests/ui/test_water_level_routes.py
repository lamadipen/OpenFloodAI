"""Water-level sampling HTTP routes with mocked gauge and image services."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from openfloodai.ingestion import river_images, usgs_gage_data
from openfloodai.ingestion import water_level_discovery as wld
from openfloodai.ingestion.river_images import ImageSequenceCandidate
from openfloodai.ingestion.usgs_gage_data import GageReading, GageSeries
from openfloodai.ui.home_server import OpenFloodAIHomeHandler

CAMERA = "CO_Test_Camera"
URL = f"https://apps.usgs.gov/hivis/camera/{CAMERA}"
UI_PATH = Path(__file__).resolve().parents[2] / "tools" / "openfloodai-home-ui.html"


def day(n: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, 1, 12, minute, tzinfo=UTC) + timedelta(days=n - 1)


def fake_series(site: str, start: str, end: str) -> GageSeries:
    readings = [GageReading(day(d).isoformat(), float(d), ("A",), "approved") for d in range(1, 61)]
    return GageSeries(
        site, "00065", "gage height", "ft", False, readings, "https://usgs.example/iv"
    )


def fake_images(slug: str, start: datetime, end: datetime) -> list[ImageSequenceCandidate]:
    out = []
    for d in range(1, 61):
        when = day(d, 5)
        stamp = when.strftime("%Y-%m-%dT%H-%M-%SZ")
        out.append(
            ImageSequenceCandidate(f"https://x.test/720/{slug}/{slug}___{stamp}.jpg", when, 10)
        )
    return out


@contextmanager
def serve(sites_dir: Path) -> Iterator[str]:
    OpenFloodAIHomeHandler.sites_dir = sites_dir
    OpenFloodAIHomeHandler.ui_path = UI_PATH
    server = ThreadingHTTPServer(("127.0.0.1", 0), OpenFloodAIHomeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post(
    url: str, data: dict[str, Any], headers: dict[str, str] | None = None
) -> tuple[int, dict[str, Any]]:
    request = Request(
        url,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return int(response.status), json.loads(response.read().decode())
    except HTTPError as error:
        return int(error.code), json.loads(error.read().decode())


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    sites = tmp_path / "sites"
    site = sites / "demo"
    (site / "configs").mkdir(parents=True)
    (site / "configs" / "site.json").write_text(
        json.dumps(
            {
                "site_id": "site-demo-01",
                "camera_id": CAMERA,
                "site_name": "Demo",
                "input_type": "local_video",
            }
        ),
        encoding="utf-8",
    )
    reference = tmp_path / "reference"
    (reference / "rivers").mkdir(parents=True)
    (reference / "rivers" / "test.json").write_text(
        json.dumps(
            {
                "river_id": "test",
                "display_name": "Test",
                "source": "https://example.test/registry",
                "cameras": [
                    {
                        "river_id": "test",
                        "camera_id": CAMERA,
                        "nwis_id": "09999999",
                        "state": "CO",
                        "latitude": 39.0,
                        "longitude": -107.0,
                        "display_name": "Test",
                        "folder_name": "demo",
                        "gage_relationship": "same_site",
                        "timezone": "America/Denver",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fetched: list[str] = []

    def fake_fetch(url: str, **_: Any) -> tuple[bytes, str]:
        fetched.append(url)
        return b"\xff\xd8\xff" + b"0" * 20, "image/jpeg"

    monkeypatch.setattr(wld, "fetch_gage_readings", fake_series)
    monkeypatch.setattr(usgs_gage_data, "fetch_gage_readings", fake_series)
    monkeypatch.setattr(wld, "list_archive_images_between", fake_images)
    monkeypatch.setattr(river_images, "_fetch", fake_fetch)
    return {"sites": sites, "site": site, "fetched": fetched}


BASE = {
    "camera_url": URL,
    "start_date": "2026-03-01",
    "end_date": "2026-04-29",
    "timezone": "America/Denver",
    "groups": ["low", "high"],
    "images_per_group": 2,
}


def refs(proposal: dict[str, Any], group: str) -> list[dict[str, str]]:
    samples = next(g for g in proposal["selection"]["groups"] if g["group"] == group)["samples"]
    return [
        {
            "group": group,
            "reading_datetime_utc": s["motivating_reading"]["datetime_utc"],
            "filename": s["image"]["filename"],
        }
        for s in samples
    ]


def test_preview_proposes_samples_and_downloads_no_images(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        code, out = post(f"{base}/api/preview-water-level-sampling", BASE)

    assert code == 200 and out["state"] == "ok"
    assert [g["group"] for g in out["selection"]["groups"]] == ["low", "high"]
    assert out["selection"]["groups"][1]["samples"][0]["motivating_reading"]["value"] == 60.0
    assert env["fetched"] == []  # discovery used listings and gauge readings only


def test_preview_explains_an_unregistered_camera(env: dict[str, Any], tmp_path: Path) -> None:
    for path in (tmp_path / "reference" / "rivers").glob("*.json"):
        path.unlink()
    with serve(env["sites"]) as base:
        code, out = post(f"{base}/api/preview-water-level-sampling", BASE)

    assert code == 200 and out["state"] == "no_station_association"


def test_preview_validates_the_request(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        bad_group = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "groups": ["extreme"]}
        )
        too_many = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "images_per_group": 99}
        )
        bad_url = post(
            f"{base}/api/preview-water-level-sampling",
            {**BASE, "camera_url": "https://evil.test/x"},
        )
        bool_count = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "images_per_group": True}
        )

    for code, body in (bad_group, too_many, bad_url, bool_count):
        assert code == 400 and body["success"] is False


def test_a_cross_origin_post_is_refused(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        code, _ = post(
            f"{base}/api/preview-water-level-sampling", BASE, {"Origin": "http://evil.example"}
        )
    assert code == 403


def test_download_needs_exact_confirmation_then_fetches_only_approved_images(
    env: dict[str, Any],
) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        approved = refs(proposal, "high")[:1] + refs(proposal, "low")[:1]
        body = {**BASE, "folder_name": "demo", "approved": approved, "declined": []}
        unconfirmed = post(f"{base}/api/download-water-level-sampling", body)
        wrong_count = post(
            f"{base}/api/download-water-level-sampling",
            {**body, "confirmed": True, "confirmed_count": 5},
        )
        assert env["fetched"] == []
        code, out = post(
            f"{base}/api/download-water-level-sampling",
            {**body, "confirmed": True, "confirmed_count": 2},
        )

    assert unconfirmed[0] == 400 and "Confirm" in unconfirmed[1]["message"]
    assert wrong_count[0] == 400
    assert code == 200 and out["downloaded_count"] == 2 and out["sampling_mode"] == "water_level"
    assert len(env["fetched"]) == 2  # only the approved images, not the whole proposal
    sequence = env["site"] / "inputs" / "image-sequences" / out["sequence_id"]
    selection = json.loads((sequence / "water-level-selection.json").read_text())
    assert (
        len(selection["samples"]) == 2 and selection["policy_version"] == "water-level-sampling-v1"
    )
    assert (sequence / "gauge-readings.json").is_file()  # existing gauge source for run evidence


def test_download_refuses_a_stale_or_edited_approval(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        approved = refs(proposal, "high")[:1]
        approved[0]["group"] = "low"  # a tampered group
        code, out = post(
            f"{base}/api/download-water-level-sampling",
            {
                **BASE,
                "folder_name": "demo",
                "approved": approved,
                "confirmed": True,
                "confirmed_count": 1,
            },
        )

    assert code == 400 and "Find samples again" in out["message"]
    assert env["fetched"] == []


def test_the_regular_download_route_still_rejects_water_level_mode(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        code, out = post(
            f"{base}/api/download-image-sequence",
            {
                "folder_name": "demo",
                "camera_url": URL,
                "start_date": "2026-03-01",
                "end_date": "2026-03-05",
                "timezone": "America/Denver",
                "sampling_mode": "water_level",
            },
        )
    assert code == 400 and "water-level sample" in out["message"]


def test_time_of_day_is_validated_and_returned_with_the_preview(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        ok = post(f"{base}/api/preview-water-level-sampling", {**BASE, "time_of_day": "daytime"})
        bad = post(f"{base}/api/preview-water-level-sampling", {**BASE, "time_of_day": "dusk"})
        default = post(f"{base}/api/preview-water-level-sampling", BASE)

    assert ok[0] == 200
    assert ok[1]["request"]["time_of_day"]["mode"] == "daytime"
    assert ok[1]["selection"]["policy"]["time_of_day"]["window_local_hours"] == [10, 14]
    assert bad[0] == 400 and bad[1]["success"] is False
    assert default[1]["request"]["time_of_day"]["mode"] == "any"


def test_downloading_again_never_hits_an_already_exists_error(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        high = refs(proposal, "high")[:2]
        low = refs(proposal, "low")[:1]

        def download(approved: list[dict[str, str]]) -> tuple[int, dict[str, Any]]:
            return post(
                f"{base}/api/download-water-level-sampling",
                {
                    **BASE,
                    "folder_name": "demo",
                    "approved": approved,
                    "confirmed": True,
                    "confirmed_count": len(approved),
                },
            )

        first = download(high)
        same = download(high)  # the exact same approved images again
        other = download(low)  # a different selection for the same camera and dates

    assert first[0] == same[0] == other[0] == 200
    assert same[1]["sequence_id"] == first[1]["sequence_id"]
    assert other[1]["sequence_id"] != first[1]["sequence_id"]
    sequences = env["site"] / "inputs" / "image-sequences"
    assert {p.name for p in sequences.iterdir()} == {
        first[1]["sequence_id"],
        other[1]["sequence_id"],
    }


def test_a_camera_url_for_a_different_camera_is_refused_before_anything_is_fetched(
    env: dict[str, Any],
) -> None:
    other = {
        **BASE,
        "camera_url": "https://apps.usgs.gov/hivis/camera/CO_Other_Camera",
        "folder_name": "demo",
    }
    with serve(env["sites"]) as base:
        preview = post(f"{base}/api/preview-water-level-sampling", other)
        _, proposal = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "folder_name": "demo"}
        )
        approved = refs(proposal, "high")[:1]
        download = post(
            f"{base}/api/download-water-level-sampling",
            {**other, "approved": approved, "confirmed": True, "confirmed_count": 1},
        )

    for code, body in (preview, download):
        assert code == 400 and body["success"] is False
        assert "CO_Other_Camera" in body["message"] and CAMERA in body["message"]
    assert env["fetched"] == []
    assert not (env["site"] / "inputs" / "image-sequences").exists()


def test_the_site_is_required_to_download_and_a_matching_camera_works(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        approved = refs(proposal, "high")[:1]
        no_site = post(
            f"{base}/api/download-water-level-sampling",
            {**BASE, "approved": approved, "confirmed": True, "confirmed_count": 1},
        )
        ok = post(
            f"{base}/api/download-water-level-sampling",
            {
                **BASE,
                "folder_name": "demo",
                "approved": approved,
                "confirmed": True,
                "confirmed_count": 1,
            },
        )

    assert no_site[0] == 400 and "site" in no_site[1]["message"]
    assert ok[0] == 200


def test_one_low_image_requested_cannot_download_three_high_images(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "images_per_group": 3}
        )
        three_high = refs(proposal, "high")[:3]
        assert len(three_high) == 3
        wrong_group = post(
            f"{base}/api/download-water-level-sampling",
            {
                **BASE,
                "groups": ["low"],
                "images_per_group": 1,
                "folder_name": "demo",
                "approved": three_high,
                "confirmed": True,
                "confirmed_count": 3,
            },
        )
        too_many = post(
            f"{base}/api/download-water-level-sampling",
            {
                **BASE,
                "groups": ["high"],
                "images_per_group": 1,
                "folder_name": "demo",
                "approved": three_high,
                "confirmed": True,
                "confirmed_count": 3,
            },
        )

    for code, body in (wrong_group, too_many):
        assert code == 400 and "Run Find samples again" in body["message"]
    assert env["fetched"] == []
    assert not (env["site"] / "inputs" / "image-sequences").exists()

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


def get(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return dict(json.loads(response.read().decode("utf-8")))


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
        return b"\xff\xd8\xff" + b"0" * 7, "image/jpeg"

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
    selection = json.loads((sequence / "sampling-batches" / "batch-0001.json").read_text())
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
    assert code == 400 and "Find samples" in out["message"]


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


def test_repeating_a_download_makes_a_separate_sequence_and_never_an_already_exists_error(
    env: dict[str, Any],
) -> None:
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
    ids = {first[1]["sequence_id"], same[1]["sequence_id"], other[1]["sequence_id"]}
    assert len(ids) == 3  # every request is its own, uniquely named sequence
    sequences = env["site"] / "inputs" / "image-sequences"
    assert {p.name for p in sequences.iterdir() if not p.name.startswith(".")} == ids


def set_site_camera_label(env: dict[str, Any], label: str) -> None:
    config_path = env["site"] / "configs" / "site.json"
    config = json.loads(config_path.read_text())
    config["camera_id"] = label
    config_path.write_text(json.dumps(config))


def test_a_site_whose_internal_camera_label_differs_still_works_with_a_notice(
    env: dict[str, Any],
) -> None:
    # The site's camera_id is an internal label (here with a suffix), not the USGS camera id.
    set_site_camera_label(env, f"{CAMERA}_camid")
    with serve(env["sites"]) as base:
        code, preview = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "folder_name": "demo"}
        )
        approved = refs(preview, "high")[:1]
        body = {**BASE, "folder_name": "demo", "approved": approved}
        plan = post(f"{base}/api/plan-water-level-intake", body)
        destinations = post(f"{base}/api/water-level-destinations", body)
        done = post(
            f"{base}/api/download-water-level-sampling",
            {**body, "confirmed": True, "confirmed_count": 1},
        )

    assert code == 200 and preview["state"] == "ok"
    assert f"{CAMERA}_camid" in preview["camera_notice"] and CAMERA in preview["camera_notice"]
    assert plan[0] == 200 and destinations[0] == 200 and done[0] == 200
    sequence = env["site"] / "inputs" / "image-sequences" / done[1]["sequence_id"]
    rows = [json.loads(x) for x in (sequence / "sequence-manifest.jsonl").read_text().splitlines()]
    assert {r["camera_id"] for r in rows} == {CAMERA}  # saved as the USGS camera, from the URL
    source = json.loads((sequence / "gauge-readings.json").read_text())
    assert source["association"]["nwis_site_id"] == "09999999"  # the station for that same camera


def test_no_notice_when_the_site_camera_id_matches(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, preview = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "folder_name": "demo"}
        )
    assert "camera_notice" not in preview


def test_a_site_that_already_holds_another_camera_refuses_a_different_camera_url(
    env: dict[str, Any],
) -> None:
    set_site_camera_label(env, "internal_label")
    other = {
        **BASE,
        "camera_url": "https://apps.usgs.gov/hivis/camera/CO_Other_Camera",
        "folder_name": "demo",
    }
    with serve(env["sites"]) as base:
        _, proposal = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "folder_name": "demo"}
        )
        first = post(
            f"{base}/api/download-water-level-sampling",
            {
                **BASE,
                "folder_name": "demo",
                "approved": refs(proposal, "high")[:1],
                "confirmed": True,
                "confirmed_count": 1,
            },
        )
        fetched = len(env["fetched"])
        preview = post(f"{base}/api/preview-water-level-sampling", other)
        download = post(
            f"{base}/api/download-water-level-sampling",
            {
                **other,
                "approved": refs(proposal, "high")[:1],
                "confirmed": True,
                "confirmed_count": 1,
            },
        )
        again = post(f"{base}/api/preview-water-level-sampling", {**BASE, "folder_name": "demo"})

    assert first[0] == 200
    for code, body in (preview, download):
        assert code == 400 and body["success"] is False
        assert CAMERA in body["message"] and "CO_Other_Camera" in body["message"]
        assert "already holds images" in body["message"]
    assert len(env["fetched"]) == fetched  # nothing was fetched for the other camera
    assert again[0] == 200 and "camera_notice" not in again[1]  # the site's own camera still works


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


DESTINATIONS = "/api/water-level-destinations"
PLAN = "/api/plan-water-level-intake"
DOWNLOAD = "/api/download-water-level-sampling"


def intake_body(
    proposal: dict[str, Any], count: int = 2, group: str = "high", **extra: Any
) -> dict[str, Any]:
    return {**BASE, "folder_name": "demo", "approved": refs(proposal, group)[:count], **extra}


def confirm(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "confirmed": True,
        "confirmed_plan": {k: plan[k] for k in ("new", "duplicates", "conflicts")},
    }


def test_a_new_sequence_with_a_custom_name_is_listed_by_name_with_its_stable_id(
    env: dict[str, Any],
) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        body = intake_body(proposal, destination={"mode": "new", "name": "  Windy Gap 2026 "})
        plan = post(f"{base}{PLAN}", body)[1]["plan"]
        code, out = post(f"{base}{DOWNLOAD}", {**body, **confirm(plan)})
        listing = get(f"{base}/api/site-image-sequences?folder_name=demo")

    assert code == 200 and out["display_name"] == "Windy Gap 2026" and out["mode"] == "new"
    assert out["sequence_id"].count("water_level-") == 1 and "Windy" not in out["sequence_id"]
    assert "Added 2 new image(s) to Windy Gap 2026." in out["message"]
    row = next(r for r in listing["sequences"] if r["sequence_id"] == out["sequence_id"])
    assert row["display_name"] == "Windy Gap 2026" and row["label"] == "Windy Gap 2026"


def test_a_blank_name_keeps_the_generated_default(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        body = intake_body(proposal, destination={"mode": "new", "name": "   "})
        plan = post(f"{base}{PLAN}", body)[1]["plan"]
        out = post(f"{base}{DOWNLOAD}", {**body, **confirm(plan)})[1]

    assert out["display_name"] is None and out["label"] == out["sequence_id"]


@pytest.mark.parametrize("bad_name", ["x" * 81, "line\nbreak", 12345])
def test_an_invalid_name_is_refused_before_anything_is_fetched(
    env: dict[str, Any], bad_name: Any
) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        body = intake_body(proposal, destination={"mode": "new", "name": bad_name})
        code, out = post(f"{base}{DOWNLOAD}", {**body, "confirmed": True, "confirmed_count": 2})

    assert code == 400 and "name" in out["message"]
    assert env["fetched"] == []
    assert not (env["site"] / "inputs" / "image-sequences").exists()


def test_destinations_list_compatible_sequences_and_explain_exclusions(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        good = post(
            f"{base}{DOWNLOAD}",
            {
                **intake_body(proposal, destination={"mode": "new", "name": "Good"}),
                "confirmed": True,
                "confirmed_count": 2,
            },
        )[1]
        foreign = post(
            f"{base}{DOWNLOAD}",
            {**intake_body(proposal, 1, "low"), "confirmed": True, "confirmed_count": 1},
        )[1]
        manifest_path = (
            env["site"]
            / "inputs"
            / "image-sequences"
            / foreign["sequence_id"]
            / "sequence-manifest.jsonl"
        )
        manifest_path.write_text(manifest_path.read_text().replace(CAMERA, "CO_Other_Camera"))
        rows = {
            r["sequence_id"]: r
            for r in post(f"{base}{DESTINATIONS}", {**BASE, "folder_name": "demo"})[1][
                "destinations"
            ]
        }

    assert (
        rows[good["sequence_id"]]["compatible"] is True
        and rows[good["sequence_id"]]["label"] == "Good"
    )
    assert rows[foreign["sequence_id"]]["compatible"] is False
    assert "different camera" in rows[foreign["sequence_id"]]["reasons"][0]
    assert (
        rows[foreign["sequence_id"]]["label"] == foreign["sequence_id"]
    )  # unnamed: shown by its stable id


def test_the_plan_counts_new_images_duplicates_and_conflicts_without_changing_anything(
    env: dict[str, Any],
) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "images_per_group": 3}
        )
        first = post(
            f"{base}{DOWNLOAD}",
            {**intake_body(proposal, 1), "confirmed": True, "confirmed_count": 1},
        )[1]
        destination = {"mode": "append", "sequence_id": first["sequence_id"]}
        body = intake_body(proposal, 3, destination=destination, images_per_group=3)
        before = sorted(
            p.name
            for p in (env["site"] / "inputs" / "image-sequences" / first["sequence_id"]).rglob("*")
        )
        plan = post(f"{base}{PLAN}", body)[1]["plan"]
        after = sorted(
            p.name
            for p in (env["site"] / "inputs" / "image-sequences" / first["sequence_id"]).rglob("*")
        )

    assert (plan["new"], plan["duplicates"], plan["conflicts"]) == (2, 1, 0)
    assert sorted(i["status"] for i in plan["items"]) == ["duplicate", "new", "new"]
    assert before == after  # a plan changes nothing


def test_append_adds_only_new_images_after_the_exact_confirmation(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "images_per_group": 3}
        )
        first = post(
            f"{base}{DOWNLOAD}",
            {
                **intake_body(proposal, 1, destination={"mode": "new", "name": "Mine"}),
                "confirmed": True,
                "confirmed_count": 1,
            },
        )[1]
        fetched_before = len(env["fetched"])
        body = intake_body(
            proposal,
            3,
            destination={"mode": "append", "sequence_id": first["sequence_id"]},
            images_per_group=3,
        )
        plan = post(f"{base}{PLAN}", body)[1]["plan"]
        stale = post(
            f"{base}{DOWNLOAD}",
            {
                **body,
                "confirmed": True,
                "confirmed_plan": {"new": 3, "duplicates": 0, "conflicts": 0},
            },
        )
        unconfirmed = post(f"{base}{DOWNLOAD}", body)
        assert (
            len(env["fetched"]) == fetched_before
        )  # nothing fetched without the right confirmation
        code, out = post(f"{base}{DOWNLOAD}", {**body, **confirm(plan)})
        listing = get(f"{base}/api/site-image-sequences?folder_name=demo")

    assert stale[0] == 400 and "add 2 new image(s), skip 1 already present" in stale[1]["message"]
    assert unconfirmed[0] == 400
    assert code == 200 and out["mode"] == "append" and out["sequence_id"] == first["sequence_id"]
    assert (out["added_count"], out["duplicate_count"], out["conflict_count"]) == (2, 1, 0)
    assert "Added 2 new image(s) to Mine. Skipped 1 already present." in out["message"]
    assert len(env["fetched"]) - fetched_before == 2  # only the two new images were downloaded
    assert out["batch_number"] == 2
    rows = [r for r in listing["sequences"] if not r["sequence_id"].startswith(".")]
    assert len(rows) == 1 and rows[0]["downloaded_count"] == 3 and rows[0]["label"] == "Mine"


def test_an_all_duplicate_append_is_a_clear_no_op(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        first = post(
            f"{base}{DOWNLOAD}",
            {**intake_body(proposal, 2), "confirmed": True, "confirmed_count": 2},
        )[1]
        directory = env["site"] / "inputs" / "image-sequences" / first["sequence_id"]
        snapshot = {str(p): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        fetched = len(env["fetched"])
        body = intake_body(
            proposal, 2, destination={"mode": "append", "sequence_id": first["sequence_id"]}
        )
        plan = post(f"{base}{PLAN}", body)[1]["plan"]
        code, out = post(f"{base}{DOWNLOAD}", {**body, **confirm(plan)})

    assert plan["new"] == 0 and plan["duplicates"] == 2
    assert (
        code == 200
        and out["no_op"] is True
        and out["added_count"] == 0
        and "Nothing changed." in out["message"]
    )
    assert len(env["fetched"]) == fetched
    assert snapshot == {str(p): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    assert len([p for p in directory.parent.iterdir() if not p.name.startswith(".")]) == 1


def test_a_destination_for_another_camera_or_an_unknown_sequence_is_refused_on_the_server(
    env: dict[str, Any],
) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        first = post(
            f"{base}{DOWNLOAD}",
            {**intake_body(proposal, 1), "confirmed": True, "confirmed_count": 1},
        )[1]
        manifest_path = (
            env["site"]
            / "inputs"
            / "image-sequences"
            / first["sequence_id"]
            / "sequence-manifest.jsonl"
        )
        manifest_path.write_text(manifest_path.read_text().replace(CAMERA, "CO_Other_Camera"))
        fetched = len(env["fetched"])
        results = []
        for sequence_id in (
            first["sequence_id"],
            "usgs-nope-2026-03-01-2026-04-29-all",
            "../../etc",
        ):
            body = intake_body(
                proposal, 2, destination={"mode": "append", "sequence_id": sequence_id}
            )
            results.append(post(f"{base}{PLAN}", body))
            results.append(
                post(
                    f"{base}{DOWNLOAD}",
                    {
                        **body,
                        "confirmed": True,
                        "confirmed_plan": {"new": 2, "duplicates": 0, "conflicts": 0},
                    },
                )
            )

    assert all(code == 400 and out["success"] is False for code, out in results)
    assert "different camera" in results[0][1]["message"]
    assert len(env["fetched"]) == fetched


def test_a_bad_destination_shape_is_rejected(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(f"{base}/api/preview-water-level-sampling", BASE)
        for destination in (
            "append",
            {"mode": "merge"},
            {"mode": "append"},
            {"mode": "append", "sequence_id": 7},
        ):
            code, out = post(f"{base}{PLAN}", intake_body(proposal, 1, destination=destination))
            assert code == 400 and out["success"] is False, destination


def test_a_conflict_is_reported_in_the_plan_and_never_overwritten(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        _, proposal = post(
            f"{base}/api/preview-water-level-sampling", {**BASE, "images_per_group": 3}
        )
        first = post(
            f"{base}{DOWNLOAD}",
            {**intake_body(proposal, 1), "confirmed": True, "confirmed_count": 1},
        )[1]
        directory = env["site"] / "inputs" / "image-sequences" / first["sequence_id"]
        name = first["added"][0]
        (directory / "images" / name).write_bytes(b"\xff\xd8\xff-different-and-longer")
        body = intake_body(
            proposal, 1, destination={"mode": "append", "sequence_id": first["sequence_id"]}
        )
        plan = post(f"{base}{PLAN}", body)[1]["plan"]
        code, out = post(f"{base}{DOWNLOAD}", {**body, **confirm(plan)})

    assert (plan["new"], plan["duplicates"], plan["conflicts"]) == (0, 0, 1)
    assert code == 200 and out["conflict_count"] == 1 and out["no_op"] is True
    assert (directory / "images" / name).read_bytes() == b"\xff\xd8\xff-different-and-longer"

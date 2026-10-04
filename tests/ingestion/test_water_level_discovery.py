"""Water-level discovery and download with mocked gauge and image services."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from openfloodai.ingestion import water_level_discovery as wld
from openfloodai.ingestion import water_level_sampling as wls
from openfloodai.ingestion.river_images import (
    WATER_LEVEL_SELECTION_FILENAME,
    ImageSequenceCandidate,
    RiverImageError,
    download_river_image_sequence,
)
from openfloodai.ingestion.usgs_gage_data import GageDataError, GageReading, GageSeries

CAMERA = "CO_Test_Camera"
URL = f"https://apps.usgs.gov/hivis/camera/{CAMERA}"
START, END = "2026-03-01", "2026-04-29"


def day(n: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 3, 1, hour, minute, tzinfo=UTC) + timedelta(days=n - 1)


def series(
    values: dict[int, float] | None = None, *, parameter: str = "00065", fallback: bool = False
) -> GageSeries:
    values = values if values is not None else {d: float(d) for d in range(1, 61)}
    readings = [
        GageReading(
            day(d).isoformat(),
            v,
            ("P",) if d == 60 else ("A",),
            "provisional" if d == 60 else "approved",
        )
        for d, v in values.items()
    ]
    return GageSeries(
        "09999999",
        parameter,
        "gage height" if parameter == "00065" else "discharge",
        "ft" if parameter == "00065" else "ft3/s",
        fallback,
        readings,
        "https://waterservices.example/iv",
        2,
    )


def images() -> list[ImageSequenceCandidate]:
    out = []
    for d in range(1, 61):
        when = day(d, minute=5)
        stamp = when.strftime("%Y-%m-%dT%H-%M-%SZ")
        out.append(
            ImageSequenceCandidate(
                f"https://example.test/720/{CAMERA}/{CAMERA}___{stamp}.jpg", when, 100
            )
        )
    return out


def write_registry(tmp_path: Path, *, relationship: str = "same_site") -> Path:
    reference = tmp_path / "reference"
    (reference / "rivers").mkdir(parents=True)
    camera = {
        "river_id": "test",
        "camera_id": CAMERA,
        "nwis_id": "09999999",
        "state": "CO",
        "latitude": 39.0,
        "longitude": -107.0,
        "display_name": "Test",
        "folder_name": "test-site",
        "gage_relationship": relationship,
        "timezone": "America/Denver",
    }
    if relationship == "nearby":
        camera["gage_relationship_note"] = "Upstream of the camera."
    (reference / "rivers" / "test.json").write_text(
        json.dumps(
            {
                "river_id": "test",
                "display_name": "Test River",
                "source": "https://example.test/registry",
                "source_checked": "2026-05-01",
                "cameras": [camera],
            }
        ),
        encoding="utf-8",
    )
    return reference


def context(tmp_path: Path, **kwargs: Any) -> wld.DiscoveryContext:
    return wld.build_context(URL, START, END, "", write_registry(tmp_path, **kwargs))


def run(ctx: wld.DiscoveryContext, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("fetch_gauge", lambda *_: series())
    kwargs.setdefault("list_images", lambda *_: images())
    kwargs.setdefault("groups", ["low", "middle", "high"])
    kwargs.setdefault("images_per_group", 3)
    return wld.discover(ctx, **kwargs)


def test_discovery_proposes_samples_with_the_stations_association_and_policy(
    tmp_path: Path,
) -> None:
    out = run(context(tmp_path))

    assert out["state"] == "ok" and out["policy_version"] == wls.POLICY_VERSION
    assert out["association"]["nwis_site_id"] == "09999999"
    assert out["association"]["source"] == "https://example.test/registry"
    assert out["gauge"]["parameter_code"] == "00065" and out["gauge"]["unit"] == "ft"
    assert out["gauge"]["rejected_reading_count"] == 2
    groups = {g["group"]: g for g in out["selection"]["groups"]}
    assert [s["motivating_reading"]["value"] for s in groups["high"]["samples"]] == [
        60.0,
        57.0,
        54.0,
    ]
    assert groups["high"]["samples"][0]["motivating_reading"]["quality_status"] == "provisional"
    assert "relative" in out["note"]


def test_the_time_zone_comes_from_the_registry_when_the_form_leaves_it_blank(
    tmp_path: Path,
) -> None:
    assert context(tmp_path).timezone == "America/Denver"


def test_a_camera_without_a_usgs_association_is_unavailable_and_nothing_is_fetched(
    tmp_path: Path,
) -> None:
    ctx = wld.build_context(URL, START, END, "America/Denver", tmp_path / "empty")

    def boom(*_: Any) -> Any:
        raise AssertionError("must not be called")

    out = run(ctx, fetch_gauge=boom, list_images=boom)

    assert out["state"] == "no_station_association" and "never guessed" in out["message"]


def test_a_registry_entry_marked_unavailable_is_treated_as_no_association(tmp_path: Path) -> None:
    out = run(context(tmp_path, relationship="unavailable"))
    assert out["state"] == "no_station_association"


def test_a_nearby_gauge_is_allowed_but_flagged_with_usgs_note(tmp_path: Path) -> None:
    out = run(context(tmp_path, relationship="nearby"))
    assert out["state"] == "ok" and "nearby" in out["warning"] and "Upstream" in out["warning"]


def test_discharge_only_is_never_used_as_water_level(tmp_path: Path) -> None:
    out = run(
        context(tmp_path),
        fetch_gauge=lambda *_: series(parameter="00060", fallback=True),
    )

    assert out["state"] == "gauge_height_unavailable"
    assert "discharge" in out["message"] and "never used" in out["message"]
    assert "selection" not in out


def test_a_gauge_service_failure_is_its_own_state(tmp_path: Path) -> None:
    def fail(*_: Any) -> Any:
        raise GageDataError("down")

    out = run(context(tmp_path), fetch_gauge=fail)
    assert out["state"] == "gauge_service_unavailable"


def test_an_empty_archive_is_its_own_state(tmp_path: Path) -> None:
    assert run(context(tmp_path), list_images=lambda *_: [])["state"] == "no_images_in_range"


def test_only_readings_inside_the_requested_range_are_used(tmp_path: Path) -> None:
    ctx = wld.build_context(
        URL, "2026-03-10", "2026-03-20", "America/Denver", write_registry(tmp_path)
    )
    out = run(ctx)  # the fetcher returns all 60 days; only 11 are in range
    assert out["gauge"]["valid_reading_count"] == 11


def test_the_fetch_range_is_padded_by_a_day_for_site_local_dates(tmp_path: Path) -> None:
    asked: list[tuple[str, str, str]] = []

    def fetch(site: str, start: str, end: str) -> GageSeries:
        asked.append((site, start, end))
        return series()

    run(context(tmp_path), fetch_gauge=fetch)
    assert asked == [("09999999", "2026-02-28", "2026-04-30")]


def test_replacement_keeps_approved_samples_and_skips_declined_images(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    first = run(ctx, groups=["high"])
    samples = first["selection"]["groups"][0]["samples"]
    kept = [
        {
            "group": "high",
            "reading_datetime_utc": s["motivating_reading"]["datetime_utc"],
            "filename": s["image"]["filename"],
        }
        for s in samples[:2]
    ]
    declined = [samples[2]["image"]["filename"]]

    redo = run(ctx, groups=["high"], kept=kept, declined=declined)

    redo_samples = redo["selection"]["groups"][0]["samples"]
    assert [s["motivating_reading"]["value"] for s in redo_samples[:2]] == [60.0, 57.0]
    assert redo_samples[2]["image"]["filename"] != declined[0]
    assert redo["declined_images"] == declined


def approved_from(out: dict[str, Any], group: str = "high", count: int = 2) -> list[dict[str, str]]:
    samples = next(g for g in out["selection"]["groups"] if g["group"] == group)["samples"][:count]
    return [
        {
            "group": group,
            "reading_datetime_utc": s["motivating_reading"]["datetime_utc"],
            "filename": s["image"]["filename"],
        }
        for s in samples
    ]


def fake_download(captured: dict[str, Any]) -> Any:
    def download(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return "result"

    return download


def test_only_approved_images_are_downloaded_with_verified_provenance(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    proposal = run(ctx)
    approved = approved_from(proposal, "high", 2) + approved_from(proposal, "low", 1)
    captured: dict[str, Any] = {}

    result, provenance = wld.download_approved(
        ctx,
        approved=approved,
        declined=["x.jpg"],
        groups=["low", "high"],
        images_per_group=3,
        site_id="site-1",
        site_dir=tmp_path / "site",
        fetch_gauge=lambda *_: series(),
        list_images=lambda *_: images(),
        download=fake_download(captured),
    )

    assert str(result) == "result"
    assert captured["sampling_mode"] == "water_level"
    sent = {c.source_url.rsplit("/", 1)[-1] for c in captured["selected_candidates"]}
    assert sent == {a["filename"] for a in approved}  # only the approved set, not the proposal
    assert len(captured["selected_candidates"]) == 3
    assert provenance["policy_version"] == wls.POLICY_VERSION
    assert provenance["association"]["source"] == "https://example.test/registry"
    assert provenance["gauge"]["parameter_code"] == "00065"
    assert provenance["declined_images"] == ["x.jpg"]
    assert len(provenance["samples"]) == 3
    by_group = {g["group"]: g for g in provenance["groups"]}
    assert by_group["high"]["approved"] == 2 and by_group["high"]["shortfall"]["missing"] == 1
    first = provenance["samples"][0]
    assert {
        "motivating_reading",
        "image_reading",
        "gap_seconds",
        "image_reading_gap_seconds",
        "filename",
    } <= set(first)


def test_a_sample_that_no_longer_qualifies_blocks_the_download(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    approved = approved_from(run(ctx))
    revised = series({d: float(d) for d in range(1, 60)} | {60: 1.0})  # the peak was corrected away

    with pytest.raises(RiverImageError, match="Find samples again"):
        wld.download_approved(
            ctx,
            approved=approved,
            declined=[],
            groups=["high"],
            images_per_group=3,
            site_id="s",
            site_dir=tmp_path / "site",
            fetch_gauge=lambda *_: revised,
            list_images=lambda *_: images(),
            download=fake_download({}),
        )


def test_a_download_needs_at_least_one_approved_sample(tmp_path: Path) -> None:
    with pytest.raises(RiverImageError, match="Approve at least one"):
        wld.download_approved(
            context(tmp_path),
            approved=[],
            declined=[],
            groups=["high"],
            images_per_group=3,
            site_id="s",
            site_dir=tmp_path / "site",
        )


def test_the_real_intake_saves_selection_evidence_and_never_rewrites_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openfloodai.ingestion import river_images

    ctx = context(tmp_path)
    approved = approved_from(run(ctx), "high", 2)
    jpeg = b"\xff\xd8\xff" + b"0" * 20
    monkeypatch.setattr(river_images, "_fetch", lambda url, **_: (jpeg, "image/jpeg"))
    site = tmp_path / "site"

    def go(**kwargs: Any) -> Any:
        return wld.download_approved(
            ctx,
            approved=approved,
            declined=[],
            groups=["high"],
            images_per_group=2,
            site_id="site-1",
            site_dir=site,
            fetch_gauge=lambda *_: series(),
            list_images=lambda *_: images(),
            download=download_river_image_sequence,
            **kwargs,
        )

    result, provenance = go()

    sequence = result.directory
    assert result.sequence_id.endswith("-water_level")
    saved = json.loads((sequence / WATER_LEVEL_SELECTION_FILENAME).read_text())
    assert saved["policy_version"] == wls.POLICY_VERSION and len(saved["samples"]) == 2
    manifest = [
        json.loads(line) for line in (sequence / "sequence-manifest.jsonl").read_text().splitlines()
    ]
    assert [r["download_status"] for r in manifest] == ["downloaded", "downloaded"]
    assert not any(r["download_status"] == "missing" for r in manifest)
    before = (sequence / WATER_LEVEL_SELECTION_FILENAME).read_bytes()

    # The same sequence again is refused by the existing intake rules, never silently replaced.
    with pytest.raises(RiverImageError, match="already exists"):
        go()
    # A resume of the SAME approved images works and leaves the saved evidence untouched.
    go(resume=True)
    assert (sequence / WATER_LEVEL_SELECTION_FILENAME).read_bytes() == before
    # A DIFFERENT approved set cannot slip in without an explicit overwrite.
    other = approved_from(run(ctx), "low", 1)
    with pytest.raises(RiverImageError, match="different images"):
        wld.download_approved(
            ctx,
            approved=other,
            declined=[],
            groups=["low"],
            images_per_group=1,
            site_id="site-1",
            site_dir=site,
            resume=True,
            fetch_gauge=lambda *_: series(),
            list_images=lambda *_: images(),
            download=download_river_image_sequence,
        )


def test_regular_sampling_still_rejects_the_water_level_mode_and_stray_selections() -> None:
    from openfloodai.ingestion.river_images import sample_image_sequence_candidates

    with pytest.raises(RiverImageError, match="Find samples"):
        sample_image_sequence_candidates([], "water_level")
    with pytest.raises(RiverImageError, match="only used for water-level"):
        download_river_image_sequence(
            camera_url=URL,
            start_date=START,
            end_date=END,
            timezone_name="America/Denver",
            sampling_mode="all",
            site_id="s",
            site_dir=Path("/nonexistent"),
            selected_candidates=[],
        )


def test_listing_exposes_each_images_group_for_the_baseline_picker(tmp_path: Path) -> None:
    from openfloodai.ingestion.river_images import list_site_image_sequences

    water = tmp_path / "inputs" / "image-sequences" / "usgs-cam-2026-03-01-2026-04-29-water_level"
    regular = tmp_path / "inputs" / "image-sequences" / "usgs-cam-2026-03-01-2026-04-29-all"
    for folder in (water, regular):
        folder.mkdir(parents=True)
        (folder / "download-summary.json").write_text(json.dumps({"sequence_id": folder.name}))
    (water / "water-level-selection.json").write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "filename": "a.jpg",
                        "group": "high",
                        "motivating_reading": {"value": 9.0, "unit": "ft"},
                        "image_reading": {
                            "value": 8.9,
                            "unit": "ft",
                            "quality_status": "provisional",
                        },
                    },
                    {
                        "filename": "b.jpg",
                        "group": "low",
                        "motivating_reading": {
                            "value": 1.5,
                            "unit": "ft",
                            "quality_status": "approved",
                        },
                        "image_reading": None,
                    },
                ]
            }
        )
    )

    by_id = {row["sequence_id"]: row for row in list_site_image_sequences(tmp_path)}

    assert by_id[water.name]["water_level_groups"] == {"a.jpg": "high", "b.jpg": "low"}
    samples = by_id[water.name]["water_level_samples"]
    # the image's own reading is preferred; the motivating reading is the fallback
    assert samples["a.jpg"] == {
        "group": "high",
        "level": 8.9,
        "unit": "ft",
        "quality_status": "provisional",
    }
    assert samples["b.jpg"] == {
        "group": "low",
        "level": 1.5,
        "unit": "ft",
        "quality_status": "approved",
    }
    assert (
        "water_level_groups" not in by_id[regular.name]
        and "water_level_samples" not in by_id[regular.name]
    )


def counting_lister(calls: list[tuple[datetime, datetime]]) -> Any:
    everything = images()

    def lister(slug: str, start: datetime, end: datetime) -> list[ImageSequenceCandidate]:
        calls.append((start, end))
        return [i for i in everything if start <= i.captured_utc < end]

    return lister


def test_discovery_checks_the_archive_only_around_candidate_readings(tmp_path: Path) -> None:
    calls: list[tuple[datetime, datetime]] = []

    out = run(context(tmp_path), list_images=counting_lister(calls))

    assert out["state"] == "ok"
    # 60 days of readings, three groups of three: a handful of day listings, never one per day.
    assert 0 < len(calls) <= 30
    assert out["archive"]["days_checked"] == len({c[0] for c in calls})
    assert out["archive"]["images_seen"] > 0 and "no image was downloaded" in out["archive"]["note"]
    # every request is a single UTC day plus the 15-minute margins -- never the whole range
    assert all(timedelta(hours=24) < (end - start) < timedelta(hours=26) for start, end in calls)


def test_a_huge_range_never_lists_the_whole_archive(tmp_path: Path) -> None:
    ctx = wld.build_context(
        URL, "2026-01-01", "2026-12-31", "America/Denver", write_registry(tmp_path)
    )
    big = [
        GageReading(
            (datetime(2026, 1, 1, 12, tzinfo=UTC) + timedelta(days=d)).isoformat(),
            float(d),
            ("A",),
            "approved",
        )
        for d in range(365)
    ]
    big_series = GageSeries("09999999", "00065", "gage height", "ft", False, big, "https://u")
    calls: list[tuple[datetime, datetime]] = []

    def lister(slug: str, start: datetime, end: datetime) -> list[ImageSequenceCandidate]:
        calls.append((start, end))
        d = start + timedelta(minutes=15)
        stamp = (d + timedelta(hours=12, minutes=5)).strftime("%Y-%m-%dT%H-%M-%SZ")
        when = d + timedelta(hours=12, minutes=5)
        return [ImageSequenceCandidate(f"https://x/{CAMERA}___{stamp}.jpg", when, 1)]

    out = wld.discover(
        ctx,
        groups=["low", "middle", "high"],
        images_per_group=3,
        fetch_gauge=lambda *_: big_series,
        list_images=lister,
    )

    assert out["state"] == "ok"
    assert len(calls) < 60  # a year of days, but only the candidate days were checked


def test_day_finder_covers_a_midnight_boundary_and_caches_each_day() -> None:
    calls: list[tuple[datetime, datetime]] = []
    near_midnight = datetime(2026, 3, 2, 0, 10, tzinfo=UTC)
    before_midnight = datetime(2026, 3, 1, 23, 50, tzinfo=UTC)
    pool = [
        ImageSequenceCandidate(f"https://x/a___{t:%Y-%m-%dT%H-%M-%SZ}.jpg", t, 1)
        for t in (before_midnight, near_midnight)
    ]

    def lister(slug: str, start: datetime, end: datetime) -> list[ImageSequenceCandidate]:
        calls.append((start, end))
        return [i for i in pool if start <= i.captured_utc < end]

    finder = wld.ArchiveDayFinder("a", lister)
    epoch = datetime(2026, 3, 2, 0, 0, tzinfo=UTC).timestamp()

    found = finder(epoch)
    assert [i.captured_utc for i in found] == [before_midnight, near_midnight]  # both days used
    assert len(calls) == 2
    finder(epoch)
    finder(epoch + 60)
    assert len(calls) == 2  # each day is listed once


def test_the_day_finder_stops_after_its_day_limit_and_the_group_says_so() -> None:
    finder = wld.ArchiveDayFinder("a", lambda *_: [], max_days=2)
    base = datetime(2026, 3, 1, 12, tzinfo=UTC)
    finder(base.timestamp())
    finder((base + timedelta(days=5)).timestamp())
    with pytest.raises(wls.LookupLimitReached):
        finder((base + timedelta(days=9)).timestamp())

    # In a selection, an archive with no usable images hits the limit and reports it.
    readings = [
        GageReading((base + timedelta(days=d)).isoformat(), float(d), ("A",), "approved")
        for d in range(60)
    ]
    result = wls.select_samples(
        readings,
        wld.ArchiveDayFinder("a", lambda *_: [], max_days=4),
        groups=["high"],
        images_per_group=3,
        timezone_name="America/Denver",
    )
    high = result.groups[0]
    assert high.selected == [] and high.shortfall_reason == wls.SHORTFALL_LOOKUP_LIMIT

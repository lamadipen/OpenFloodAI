"""Sampling by month: each chosen month is its own period with its own low / middle / high."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from openfloodai.ingestion import water_level_discovery as wld
from openfloodai.ingestion import water_level_sampling as wls
from openfloodai.ingestion.river_images import ImageSequenceCandidate, RiverImageError
from openfloodai.ingestion.usgs_gage_data import GageReading, GageSeries

CAMERA = "CO_Test_Camera"
URL = f"https://apps.usgs.gov/hivis/camera/{CAMERA}"
DENVER = ZoneInfo("America/Denver")
FIRST = datetime(2026, 1, 1, 19, 0, tzinfo=UTC)  # noon local
DAYS = 120  # 1 Jan .. 30 Apr 2026


def when(n: int, minute: int = 0) -> datetime:
    return FIRST + timedelta(days=n) + timedelta(minutes=minute)


def month_of(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(DENVER).strftime("%Y-%m")


def level(n: int) -> float:
    """Each month has its own scale, so month-relative bands differ from range-wide ones."""

    month = month_of(when(n).isoformat())
    base = {"2026-01": 0, "2026-02": 50, "2026-03": 100, "2026-04": 150}[month]
    return float(base + when(n).astimezone(DENVER).day)


def series() -> GageSeries:
    readings = [GageReading(when(n).isoformat(), level(n), ("A",), "approved") for n in range(DAYS)]
    return GageSeries(
        "09999999", "00065", "gage height", "ft", False, readings, "https://usgs.test"
    )


def images(*_: Any) -> list[ImageSequenceCandidate]:
    out = []
    for n in range(DAYS):
        t = when(n, 5)
        stamp = t.strftime("%Y-%m-%dT%H-%M-%SZ")
        out.append(
            ImageSequenceCandidate(f"https://x.test/720/{CAMERA}/{CAMERA}___{stamp}.jpg", t, 9)
        )
    return out


def registry(tmp_path: Path) -> Path:
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
        "gage_relationship": "same_site",
        "timezone": "America/Denver",
    }
    (reference / "rivers" / "test.json").write_text(
        json.dumps(
            {
                "river_id": "test",
                "display_name": "T",
                "source": "https://example.test/registry",
                "source_checked": "2026-05-01",
                "cameras": [camera],
            }
        ),
        encoding="utf-8",
    )
    return reference


def ctx(tmp_path: Path, start: str = "2026-01-01", end: str = "2026-04-30") -> wld.DiscoveryContext:
    return wld.build_context(URL, start, end, "", registry(tmp_path))


def run(c: wld.DiscoveryContext, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("fetch_gauge", lambda *_: series())
    kwargs.setdefault("list_images", images)
    kwargs.setdefault("groups", ["low", "middle", "high"])
    kwargs.setdefault("images_per_group", 3)
    return wld.discover(c, **kwargs)


def refs(out: dict[str, Any], month: str, group: str, count: int = 2) -> list[dict[str, str]]:
    found = next(
        g for g in out["selection"]["groups"] if g["group"] == group and g.get("month") == month
    )
    return [
        {
            "group": group,
            "month": month,
            "reading_datetime_utc": s["motivating_reading"]["datetime_utc"],
            "filename": s["image"]["filename"],
        }
        for s in found["samples"][:count]
    ]


# ---------------------------------------------------------------- periods


def test_chosen_months_become_local_month_periods_clipped_to_the_range(tmp_path: Path) -> None:
    c = ctx(tmp_path, "2026-01-15", "2026-03-10")
    periods = wls.month_periods([1, 3], c.start_utc, c.end_utc, "America/Denver")
    assert [p.key for p in periods] == ["2026-01", "2026-03"]
    assert periods[0].start_utc == c.start_utc  # January is cut at the range start
    assert periods[0].end_utc == datetime(2026, 2, 1, tzinfo=DENVER).astimezone(UTC)
    assert periods[1].start_utc == datetime(2026, 3, 1, tzinfo=DENVER).astimezone(UTC)
    assert periods[1].end_utc == c.end_utc  # March is cut at the range end
    assert periods[0].label == "January 2026"


def test_a_range_over_several_years_gives_each_matching_month_oldest_first() -> None:
    start = datetime(2024, 12, 1, 7, tzinfo=UTC)
    end = datetime(2026, 2, 1, 7, tzinfo=UTC)
    periods = wls.month_periods([1, 12], start, end, "America/Denver")
    assert [p.key for p in periods] == ["2024-12", "2025-01", "2025-12", "2026-01"]


def test_months_are_validated_and_bounded() -> None:
    start, end = datetime(2024, 1, 1, tzinfo=UTC), datetime(2026, 12, 31, tzinfo=UTC)
    for bad in ([0], [13], ["1"], [True], [1.5]):
        with pytest.raises(wls.SamplingError, match="Months must be"):
            wls.validate_months(bad)
    assert wls.validate_months([3, 1, 3]) == [1, 3]
    with pytest.raises(wls.SamplingError, match="fall inside"):
        wls.month_periods(
            [7], datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC), "UTC"
        )
    with pytest.raises(wls.SamplingError, match="limit is 24"):
        wls.month_periods(list(range(1, 13)), start, end, "America/Denver")
    assert wls.month_periods([], start, end, "UTC")[0].key == ""  # no months = whole range


# ---------------------------------------------------------------- discovery


def test_each_chosen_month_gets_its_own_bands_and_count_for_every_group(tmp_path: Path) -> None:
    out = run(ctx(tmp_path), months=[1, 2, 4])
    selection = out["selection"]
    groups = selection["groups"]
    assert [(g["month"], g["group"]) for g in groups] == [
        (m, g) for m in ("2026-01", "2026-02", "2026-04") for g in ("low", "middle", "high")
    ]
    # Up to three images per month per group; the 3-day spacing rule can leave a narrow band
    # (a month's few lowest days) with fewer, which is reported as a shortfall, not padded.
    assert all(g["found"] <= 3 for g in groups)
    assert {(g["month"], g["group"]): g["found"] for g in groups}[("2026-01", "high")] == 3
    assert {(g["month"], g["group"]): g["found"] for g in groups}[("2026-01", "low")] == 3
    assert all(g["shortfall"] for g in groups if g["found"] < 3)
    assert selection["thresholds"] is None and selection["policy"]["scope"] == "per_month"
    assert [m["month"] for m in selection["months"]] == ["2026-01", "2026-02", "2026-04"]
    assert out["request"]["months"] == [1, 2, 4]
    assert out["request"]["periods"] == ["2026-01", "2026-02", "2026-04"]
    for group in groups:  # every pick really is inside its own month
        for sample in group["samples"]:
            assert sample["month"] == group["month"]
            assert month_of(sample["motivating_reading"]["datetime_utc"]) == group["month"]
            assert month_of(sample["image"]["captured_at_utc"]) == group["month"]
    assert not any(g["month"] == "2026-03" for g in groups)  # March was not chosen


def test_high_and_low_are_decided_inside_the_month_not_across_the_range(tmp_path: Path) -> None:
    out = run(ctx(tmp_path), months=[1, 4])
    january = {g["group"]: g for g in out["selection"]["groups"] if g["month"] == "2026-01"}
    april = {g["group"]: g for g in out["selection"]["groups"] if g["month"] == "2026-04"}
    january_high = [s["motivating_reading"]["value"] for s in january["high"]["samples"]]
    april_low = [s["motivating_reading"]["value"] for s in april["low"]["samples"]]
    assert max(january_high) <= 31 and min(january_high) >= 25  # January's own top, not April's
    assert min(april_low) >= 151 and max(april_low) <= 160  # April's own bottom
    thresholds = {m["month"]: m["thresholds"] for m in out["selection"]["months"]}
    assert thresholds["2026-01"]["maximum"] == 31 and thresholds["2026-04"]["minimum"] == 151


def test_without_months_nothing_changes(tmp_path: Path) -> None:
    c = ctx(tmp_path)
    plain = run(c)
    explicit = run(c, months=[])
    assert plain["selection"] == explicit["selection"] or [
        g["samples"] for g in plain["selection"]["groups"]
    ] == [g["samples"] for g in explicit["selection"]["groups"]]
    assert "months" not in plain["request"] and "months" not in plain["selection"]
    assert all("month" not in g for g in plain["selection"]["groups"])
    assert plain["selection"]["thresholds"] is not None
    sample = plain["selection"]["groups"][0]["samples"][0]
    assert "month" not in sample


def test_a_month_outside_the_range_is_reported_not_invented(tmp_path: Path) -> None:
    c = ctx(tmp_path, "2026-01-01", "2026-02-28")
    with pytest.raises(wls.SamplingError, match="None of the chosen months"):
        run(c, months=[8])
    out = run(c, months=[2, 8])
    assert [m["month"] for m in out["selection"]["months"]] == ["2026-02"]


def test_a_month_with_no_gauge_readings_is_a_shortfall_for_that_month_only(tmp_path: Path) -> None:
    sparse = GageSeries(
        "09999999",
        "00065",
        "gage height",
        "ft",
        False,
        [r for r in series().readings if month_of(r.datetime_utc) != "2026-02"],
        "https://usgs.test",
    )
    out = run(ctx(tmp_path), months=[1, 2], fetch_gauge=lambda *_: sparse)
    by = {(g["month"], g["group"]): g for g in out["selection"]["groups"]}
    assert by[("2026-02", "high")]["found"] == 0
    assert by[("2026-02", "high")]["shortfall"]["reason"] == wls.SHORTFALL_NO_READINGS
    assert by[("2026-01", "high")]["found"] == 3


def test_replacing_one_month_slot_leaves_other_months_alone(tmp_path: Path) -> None:
    c = ctx(tmp_path)
    first = run(c, months=[1, 2])
    keep = refs(first, "2026-01", "high", 2)
    replaced = keep[0]["filename"]
    out = run(
        c,
        months=[1, 2],
        only_period="2026-01",
        groups=["high"],
        kept=[keep[1]],
        declined=[replaced],
    )
    groups = out["selection"]["groups"]
    assert [(g["month"], g["group"]) for g in groups] == [("2026-01", "high")]
    names = [s["image"]["filename"] for s in groups[0]["samples"]]
    # The kept image stays; the declined one is gone. The 3-day spacing rule decides how many
    # other readings of the month still fit, so the count may be short and says so.
    assert replaced not in names and keep[1]["filename"] in names and len(names) >= 2
    with pytest.raises(wls.SamplingError, match="not part of this request"):
        run(c, months=[1, 2], only_period="2026-03", groups=["high"])


# ---------------------------------------------------------------- approval rules


def test_approved_samples_must_name_a_requested_month_and_respect_the_count_per_month() -> None:
    item = {"group": "high", "month": "2026-01", "reading_datetime_utc": "x", "filename": "f"}
    wls.validate_approved_against_request([item], ["high"], 1, ["2026-01", "2026-02"])
    with pytest.raises(wls.SamplingError, match="month that was not requested"):
        wls.validate_approved_against_request([item], ["high"], 1, ["2026-02"])
    with pytest.raises(wls.SamplingError, match="month that was not requested"):
        wls.validate_approved_against_request([{**item, "month": ""}], ["high"], 1, ["2026-01"])
    with pytest.raises(wls.SamplingError, match="month that was not requested"):
        wls.validate_approved_against_request([item], ["high"], 1, None)  # whole-range request
    with pytest.raises(wls.SamplingError, match="in 2026-01"):
        wls.validate_approved_against_request(
            [item, {**item, "filename": "g"}], ["high"], 1, ["2026-01"]
        )
    # the same count in two different months is fine
    wls.validate_approved_against_request(
        [item, {**item, "month": "2026-02"}], ["high"], 1, ["2026-01", "2026-02"]
    )


# ---------------------------------------------------------------- download


def jpeg(calls: list[str]) -> Any:
    def fetch(url: str) -> bytes:
        calls.append(url)
        return b"\xff\xd8\xff" + url.encode()[-20:]

    return fetch


def test_only_the_approved_monthly_images_are_downloaded_with_month_provenance(
    tmp_path: Path,
) -> None:
    c = ctx(tmp_path)
    proposal = run(c, months=[1, 2])
    approved = refs(proposal, "2026-01", "high", 2) + refs(proposal, "2026-02", "low", 1)
    fetched: list[str] = []
    result, provenance = wld.download_approved(
        c,
        approved=approved,
        declined=[],
        groups=["low", "middle", "high"],
        images_per_group=3,
        months=[1, 2],
        site_id="site-1",
        site_dir=tmp_path / "site",
        fetch_gauge=lambda *_: series(),
        list_images=images,
        fetch_image=jpeg(fetched),
    )
    assert {u.rsplit("/", 1)[-1] for u in fetched} == {a["filename"] for a in approved}
    assert len(result.added) == 3
    assert provenance["request"]["periods"] == ["2026-01", "2026-02"]
    assert {s["month"] for s in provenance["samples"]} == {"2026-01", "2026-02"}
    assert provenance["thresholds"] is None and len(provenance["months"]) == 2
    counts = {(g["month"], g["group"]): g["approved"] for g in provenance["groups"]}
    assert counts[("2026-01", "high")] == 2 and counts[("2026-02", "low")] == 1
    assert counts[("2026-01", "low")] == 0


def test_a_sample_moved_to_the_wrong_month_is_refused_at_download(tmp_path: Path) -> None:
    c = ctx(tmp_path)
    approved = refs(run(c, months=[1, 2]), "2026-01", "high", 1)
    forged = [{**approved[0], "month": "2026-02"}]  # a January image claimed for February
    with pytest.raises(RiverImageError, match="Find samples again"):
        wld.download_approved(
            c,
            approved=forged,
            declined=[],
            groups=["high"],
            images_per_group=3,
            months=[1, 2],
            site_id="s",
            site_dir=tmp_path / "site",
            fetch_gauge=lambda *_: series(),
            list_images=images,
            fetch_image=jpeg([]),
        )


def test_a_monthly_approval_cannot_be_used_for_a_whole_range_download(tmp_path: Path) -> None:
    c = ctx(tmp_path)
    approved = refs(run(c, months=[1]), "2026-01", "high", 1)
    with pytest.raises(RiverImageError, match="month that was not requested"):
        wld.download_approved(
            c,
            approved=approved,
            declined=[],
            groups=["high"],
            images_per_group=3,
            site_id="s",
            site_dir=tmp_path / "site",
            fetch_gauge=lambda *_: series(),
            list_images=images,
            fetch_image=jpeg([]),
        )

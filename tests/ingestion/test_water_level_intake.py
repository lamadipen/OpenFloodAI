"""Create-or-append intake for water-level samples (mocked archive and gauge)."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from openfloodai.ingestion import sequence_store as store
from openfloodai.ingestion import water_level_intake as intake
from openfloodai.ingestion.river_images import ImageSequenceCandidate, RiverImageError
from openfloodai.ingestion.usgs_gage_data import GageReading, GageSeries, load_gauge_source

WRITE_TEXT = "openfloodai.ingestion.water_level_intake.atomic_write_text"
SLUG = "CO_Test_Camera"
TZ = "America/Denver"
SITE = "site-1"
STATION = "09999999"
ASSOCIATION = {
    "camera_id": SLUG,
    "nwis_site_id": STATION,
    "relationship": "same_site",
    "relationship_note": None,
    "source": "https://example.test/registry",
}


def moment(day: int, hour: int = 18, minute: int = 0, month: int = 3) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def candidate(when: datetime, size: int = 30) -> ImageSequenceCandidate:
    stamp = when.strftime("%Y-%m-%dT%H-%M-%SZ")
    return ImageSequenceCandidate(f"https://x.test/720/{SLUG}/{SLUG}___{stamp}.jpg", when, size)


def body_for(url: str, size: int = 30) -> bytes:
    return (b"\xff\xd8\xff" + hashlib.sha256(url.encode()).digest() * 4)[:size].ljust(size, b"0")


def fetcher(sizes: dict[str, int] | None = None, fail: set[str] | None = None) -> Any:
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        if fail and any(name in url for name in fail):
            raise RiverImageError("The archive could not be reached.")
        return body_for(url, (sizes or {}).get(url, 30))

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def series(values: dict[int, float] | None = None, *, code: str = "00065") -> GageSeries:
    values = values if values is not None else {d: float(d) for d in range(1, 29)}
    readings = [
        GageReading(moment(d).isoformat(), v, ("A",), "approved") for d, v in values.items()
    ]
    return GageSeries(
        STATION, code, "gage height", "ft", False, readings, "https://usgs.example/iv", 0
    )


def provenance(cands: list[ImageSequenceCandidate], group: str = "high") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy_version": "water-level-sampling-v1",
        "selected_at_utc": "2026-10-06T00:00:00+00:00",
        "camera_id": SLUG,
        "timezone": TZ,
        "request": {
            "start_date": "2026-03-01",
            "end_date": "2026-03-28",
            "groups": [group],
            "images_per_group": 3,
        },
        "association": ASSOCIATION,
        "gauge": {"parameter_code": "00065", "unit": "ft"},
        "thresholds": {"median": 14.0},
        "samples": [
            {
                "filename": c.source_url.rsplit("/", 1)[-1],
                "group": group,
                "motivating_reading": {"value": 1.0},
                "image_reading": {"value": 1.0},
            }
            for c in cands
        ],
        "groups": [{"group": group, "requested": 3, "approved": len(cands)}],
    }


def make(tmp_path: Path, days: list[int], **kwargs: Any) -> tuple[Path, intake.IntakeResult]:
    site = tmp_path / "site"
    cands = [candidate(moment(d)) for d in days]
    result = intake.create_sequence(
        site_dir=site,
        site_id=SITE,
        camera_slug=SLUG,
        timezone_name=TZ,
        start_date="2026-03-01",
        end_date="2026-03-28",
        candidates=cands,
        provenance=provenance(cands),
        series=series(),
        gage_relationship="same_site",
        gage_relationship_note=None,
        fetch=kwargs.pop("fetch", fetcher()),
        **kwargs,
    )
    return site, result


def append(
    site: Path, sequence_id: str, cands: list[ImageSequenceCandidate], **kwargs: Any
) -> intake.IntakeResult:
    return intake.append_to_sequence(
        site_dir=site,
        sequence_id=sequence_id,
        site_id=SITE,
        camera_slug=SLUG,
        timezone_name=TZ,
        nwis_site_id=STATION,
        start_date=kwargs.pop("start", "2026-03-01"),
        end_date=kwargs.pop("end", "2026-03-28"),
        candidates=cands,
        provenance=kwargs.pop("prov", provenance(cands, "low")),
        series=kwargs.pop("series", series()),
        gage_relationship="same_site",
        gage_relationship_note=None,
        fetch=kwargs.pop("fetch", fetcher()),
        **kwargs,
    )


def visible(directory: Path) -> list[str]:
    """Sequence folders only: hidden helper folders (locks, staging) are not sequences."""

    return [p.name for p in sorted(directory.iterdir()) if not p.name.startswith(".")]


def seq_dir(site: Path, sequence_id: str) -> Path:
    return site / "inputs" / "image-sequences" / sequence_id


def manifest(site: Path, sequence_id: str) -> list[dict[str, Any]]:
    path = seq_dir(site, sequence_id) / "sequence-manifest.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def tree_bytes(path: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()
    }


# ---- create --------------------------------------------------------------------------------


def test_a_blank_name_keeps_the_generated_unique_id(tmp_path: Path) -> None:
    site, result = make(tmp_path, [3, 6])

    assert re.fullmatch(
        rf"usgs-{SLUG}-2026-03-01-2026-03-28-water_level-[0-9a-f]{{8}}", result.sequence_id
    )
    assert result.display_name is None and result.to_dict()["label"] == result.sequence_id
    directory = seq_dir(site, result.sequence_id)
    assert not (directory / store.SEQUENCE_META_FILENAME).exists()
    assert [r["download_status"] for r in manifest(site, result.sequence_id)] == ["downloaded"] * 2
    assert (directory / "sampling-batches" / "batch-0001.json").is_file()
    assert (directory / "download-summary.json").is_file() and (
        directory / "gauge-readings.json"
    ).is_file()
    assert not [p for p in directory.parent.iterdir() if p.name.startswith(".")]  # staging is gone


def test_a_custom_name_is_metadata_and_the_id_stays_unique_and_safe(tmp_path: Path) -> None:
    site, result = make(tmp_path, [3], display_name="  Windy Gap   2026 ")

    assert result.display_name == "Windy Gap 2026" and result.to_dict()["label"] == "Windy Gap 2026"
    assert "Windy" not in result.sequence_id and result.sequence_id.endswith(
        result.sequence_id[-8:]
    )
    summary = json.loads((seq_dir(site, result.sequence_id) / "download-summary.json").read_text())
    assert (
        summary["display_name"] == "Windy Gap 2026" and summary["sequence_id"] == result.sequence_id
    )
    assert store.read_display_name(seq_dir(site, result.sequence_id)) == "Windy Gap 2026"


@pytest.mark.parametrize("bad", ["x" * 81, "new\nline", "nul\x00"])
def test_an_invalid_name_is_rejected_before_anything_is_downloaded(
    tmp_path: Path, bad: str
) -> None:
    fetch = fetcher()
    with pytest.raises(store.SequenceStoreError):
        make(tmp_path, [3], display_name=bad, fetch=fetch)
    assert fetch.calls == [] and not (tmp_path / "site").exists()


def test_html_and_path_like_names_are_stored_as_plain_text_and_cannot_move_files(
    tmp_path: Path,
) -> None:
    site, result = make(tmp_path, [3], display_name="../../x<img src=x onerror=1>")

    root = site / "inputs" / "image-sequences"
    assert visible(root) == [result.sequence_id]  # nothing outside the sequence
    assert store.read_display_name(root / result.sequence_id) == "../../x<img src=x onerror=1>"


def test_repeated_identical_requests_and_repeated_names_create_separate_sequences(
    tmp_path: Path,
) -> None:
    site, first = make(tmp_path, [3, 6], display_name="Same name")
    cands = [candidate(moment(d)) for d in (3, 6)]
    second = intake.create_sequence(
        site_dir=site,
        site_id=SITE,
        camera_slug=SLUG,
        timezone_name=TZ,
        start_date="2026-03-01",
        end_date="2026-03-28",
        candidates=cands,
        provenance=provenance(cands),
        series=series(),
        gage_relationship="same_site",
        gage_relationship_note=None,
        display_name="Same name",
        fetch=fetcher(),
    )

    assert first.sequence_id != second.sequence_id  # distinguishable by their stable IDs
    assert (seq_dir(site, first.sequence_id) / "images").is_dir() and (
        seq_dir(site, second.sequence_id) / "images"
    ).is_dir()


def test_a_creation_with_no_downloadable_image_leaves_nothing_behind(tmp_path: Path) -> None:
    site = tmp_path / "site"
    cands = [candidate(moment(3))]

    with pytest.raises(RiverImageError, match="None of the approved"):
        intake.create_sequence(
            site_dir=site,
            site_id=SITE,
            camera_slug=SLUG,
            timezone_name=TZ,
            start_date="2026-03-01",
            end_date="2026-03-28",
            candidates=cands,
            provenance=provenance(cands),
            series=series(),
            gage_relationship="same_site",
            gage_relationship_note=None,
            fetch=fetcher(fail={"2026-03-03"}),
        )

    assert visible(site / "inputs" / "image-sequences") == []


def test_a_partial_creation_keeps_only_the_images_that_arrived(tmp_path: Path) -> None:
    site, result = make(tmp_path, [3, 6, 9], fetch=fetcher(fail={"2026-03-06"}))

    assert len(result.added) == 2 and [f["filename"][-24:] for f in result.failed] == [
        "2026-03-06T18-00-00Z.jpg"
    ]
    rows = manifest(site, result.sequence_id)
    assert len(rows) == 2 and all(
        (seq_dir(site, result.sequence_id) / "images" / r["filename"]).is_file() for r in rows
    )
    batch = json.loads(
        (seq_dir(site, result.sequence_id) / "sampling-batches" / "batch-0001.json").read_text()
    )
    assert len(batch["samples"]) == 2 and len(batch["failed"]) == 1


def test_each_new_image_keeps_its_own_timestamp_and_the_gauge_source_has_the_station(
    tmp_path: Path,
) -> None:
    site, result = make(tmp_path, [3, 6])

    for row in manifest(site, result.sequence_id):
        captured = datetime.fromisoformat(row["captured_at_utc"])
        assert (
            row["local_time"]
            == captured.astimezone(__import__("zoneinfo").ZoneInfo(TZ)).isoformat()
        )
        assert row["camera_id"] == SLUG and row["site_id"] == SITE
    source = load_gauge_source(seq_dir(site, result.sequence_id))
    assert source is not None and source["association"]["nwis_site_id"] == STATION
    assert source["parameter"]["code"] == "00065" and len(source["readings"]) == 28


# ---- append --------------------------------------------------------------------------------


def test_append_adds_only_new_images_to_the_same_sequence(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3, 6], display_name="Mine")
    directory = seq_dir(site, created.sequence_id)
    before_images = tree_bytes(directory / "images")
    before_rows = manifest(site, created.sequence_id)

    result = append(site, created.sequence_id, [candidate(moment(d)) for d in (12, 15)])

    assert result.added and len(result.added) == 2 and result.batch_number == 2 and not result.no_op
    assert result.sequence_id == created.sequence_id  # no separate destination was made
    assert visible(directory.parent) == [created.sequence_id]
    rows = manifest(site, created.sequence_id)
    assert rows[:2] == before_rows  # earlier records untouched and still first
    assert [r["captured_at_utc"] for r in rows] == sorted(r["captured_at_utc"] for r in rows)
    assert len(rows) == 4 and all((directory / "images" / r["filename"]).is_file() for r in rows)
    for name, data in before_images.items():
        assert (directory / "images" / name).read_bytes() == data
    summary = json.loads((directory / "download-summary.json").read_text())
    assert (
        summary["downloaded_count"] == 4
        and summary["display_name"] == "Mine"
        and summary["batch_count"] == 2
    )
    assert store.read_display_name(directory) == "Mine"


def test_batches_keep_their_own_provenance_and_never_recategorize_earlier_images(
    tmp_path: Path,
) -> None:
    site, created = make(tmp_path, [3, 6])
    first = json.loads(
        (seq_dir(site, created.sequence_id) / "sampling-batches" / "batch-0001.json").read_bytes()
    )

    append(
        site,
        created.sequence_id,
        [candidate(moment(12))],
        prov=provenance([candidate(moment(12))], "low"),
    )

    directory = seq_dir(site, created.sequence_id)
    batches = store.read_batches(directory)
    assert [b["batch_number"] for b in batches] == [1, 2]
    assert (
        json.loads((directory / "sampling-batches" / "batch-0001.json").read_bytes()) == first
    )  # untouched
    second = batches[1]
    assert second["destination"]["mode"] == "append" and second["request"]["groups"] == ["low"]
    assert [s["group"] for s in second["samples"]] == [
        "low"
    ] and "THIS batch's date range" in second["relative_note"]
    groups = {n: s["group"] for n, s in store.samples_by_filename(batches).items()}
    assert sorted(groups.values()) == ["high", "high", "low"]


def test_existing_gauge_readings_are_never_replaced_but_new_ones_are_added(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])
    directory = seq_dir(site, created.sequence_id)
    original = load_gauge_source(directory)
    assert original is not None
    revised = {d: float(d) + 100 for d in range(1, 29)}  # USGS "revised" every old value
    extra = series(revised)
    extra.readings.append(GageReading(moment(1, month=4).isoformat(), 55.0, ("P",), "provisional"))

    append(
        site,
        created.sequence_id,
        [candidate(moment(8))],
        series=extra,
        start="2026-03-01",
        end="2026-04-02",
    )

    merged = load_gauge_source(directory)
    assert merged is not None
    old = {r["datetime_utc"]: r for r in original["readings"]}
    now = {r["datetime_utc"]: r for r in merged["readings"]}
    assert all(now[k] == v for k, v in old.items())  # earlier evidence unchanged
    assert moment(1, month=4).isoformat() in now and len(now) == len(old) + 1
    assert (
        merged["end_date"] == "2026-04-02"
        and merged["appended_batches"][-1]["batch_id"] == "batch-0002"
    )
    assert merged["retrieved_at_utc"] == original["retrieved_at_utc"]


def test_an_all_duplicate_request_is_a_clear_no_op(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3, 6])
    directory = seq_dir(site, created.sequence_id)
    snapshot = tree_bytes(directory)
    fetch = fetcher()

    result = append(
        site, created.sequence_id, [candidate(moment(3)), candidate(moment(6))], fetch=fetch
    )

    assert (
        result.no_op
        and result.added == []
        and len(result.duplicates) == 2
        and result.batch_number is None
    )
    assert fetch.calls == []  # nothing was downloaded
    assert (
        tree_bytes(directory) == snapshot
    )  # not a byte changed: no batch, no manifest entry, no summary
    assert visible(directory.parent) == [created.sequence_id]


def test_overlapping_requests_skip_duplicates_and_add_the_rest(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3, 6])

    result = append(site, created.sequence_id, [candidate(moment(d)) for d in (6, 9, 12)])

    assert len(result.duplicates) == 1 and len(result.added) == 2
    rows = manifest(site, created.sequence_id)
    assert len(rows) == 4 and len({r["source_url"] for r in rows}) == 4  # no duplicate entries


def test_same_day_images_at_different_times_remain_separate(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])

    result = append(site, created.sequence_id, [candidate(moment(3, 17)), candidate(moment(3, 20))])

    assert len(result.added) == 2
    local_dates = {r["local_time"][:10] for r in manifest(site, created.sequence_id)}
    assert local_dates == {"2026-03-03"} and len(manifest(site, created.sequence_id)) == 3


def test_a_same_capture_time_from_another_source_is_a_conflict_not_an_overwrite(
    tmp_path: Path,
) -> None:
    site, created = make(tmp_path, [3])
    twin = ImageSequenceCandidate(
        f"https://other.test/{SLUG}/other___2026-03-03T18-00-00Z.jpg", moment(3), 30
    )
    snapshot = tree_bytes(seq_dir(site, created.sequence_id))

    result = append(site, created.sequence_id, [twin])

    assert result.no_op and result.conflicts[0]["reason"].startswith(
        "Another image already has this capture time"
    )
    assert tree_bytes(seq_dir(site, created.sequence_id)) == snapshot


def test_a_same_name_with_different_content_is_a_conflict_and_the_file_is_kept(
    tmp_path: Path,
) -> None:
    site, created = make(tmp_path, [3])
    directory = seq_dir(site, created.sequence_id)
    existing = manifest(site, created.sequence_id)[0]
    original = (directory / "images" / existing["filename"]).read_bytes()
    bigger = ImageSequenceCandidate(
        existing["source_url"], moment(3), 999
    )  # archive says different size

    result = append(site, created.sequence_id, [bigger])

    assert result.conflicts and "different size" in result.conflicts[0]["reason"] and result.no_op
    assert (directory / "images" / existing["filename"]).read_bytes() == original

    # a stray file with a new image's name but other content is also reported, not overwritten
    stray = candidate(moment(9))
    (directory / "images" / stray.source_url.rsplit("/", 1)[-1]).write_bytes(b"different")
    again = append(site, created.sequence_id, [stray])
    assert again.conflicts and "different file" in again.conflicts[0]["reason"]
    assert (directory / "images" / stray.source_url.rsplit("/", 1)[-1]).read_bytes() == b"different"


def test_conflicts_are_skipped_while_the_rest_of_the_batch_is_added(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])
    twin = ImageSequenceCandidate("https://other.test/o___2026-03-03T18-00-00Z.jpg", moment(3), 30)

    result = append(site, created.sequence_id, [twin, candidate(moment(9))])

    assert len(result.added) == 1 and len(result.conflicts) == 1
    assert len(manifest(site, created.sequence_id)) == 2


def test_new_images_start_unreviewed_and_labels_stay_with_original_identities(
    tmp_path: Path,
) -> None:
    site, created = make(tmp_path, [3])
    labels = site / "labels" / "labels.jsonl"
    labels.parent.mkdir(parents=True)
    labels.write_text(
        json.dumps({"image": manifest(site, created.sequence_id)[0]["filename"], "label": "x"})
        + "\n"
    )
    before = labels.read_bytes()

    append(site, created.sequence_id, [candidate(moment(9))])

    assert labels.read_bytes() == before  # appending never touches labels
    assert not (site / "outputs").exists()  # and starts no run or review


def test_a_failed_download_is_reported_and_never_listed_in_the_manifest(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])

    result = append(
        site,
        created.sequence_id,
        [candidate(moment(9)), candidate(moment(12))],
        fetch=fetcher(fail={"2026-03-09"}),
    )

    assert len(result.added) == 1 and len(result.failed) == 1
    rows = manifest(site, created.sequence_id)
    assert len(rows) == 2 and "2026-03-09" not in json.dumps(rows)
    directory = seq_dir(site, created.sequence_id)
    assert all((directory / "images" / r["filename"]).is_file() for r in rows)


def test_a_failed_download_of_everything_changes_nothing(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])
    directory = seq_dir(site, created.sequence_id)
    snapshot = tree_bytes(directory)

    result = append(
        site, created.sequence_id, [candidate(moment(9))], fetch=fetcher(fail={"2026-03-09"})
    )

    assert result.no_op and len(result.failed) == 1
    assert tree_bytes(directory) == snapshot


def test_an_interrupted_append_leaves_the_manifest_valid_and_a_retry_adds_no_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site, created = make(tmp_path, [3])
    directory = seq_dir(site, created.sequence_id)
    snapshot_manifest = (directory / "sequence-manifest.jsonl").read_bytes()
    new = [candidate(moment(9)), candidate(moment(12))]
    real_write = store.atomic_write_text

    def crash_on_manifest(path: Path, text: str) -> None:
        if path.name == "sequence-manifest.jsonl":
            raise OSError("power loss")
        real_write(path, text)

    monkeypatch.setattr(
        "openfloodai.ingestion.water_level_intake.atomic_write_text", crash_on_manifest
    )
    with pytest.raises(OSError):
        append(site, created.sequence_id, new)
    monkeypatch.setattr(WRITE_TEXT, real_write)

    # The manifest (the commit point) is exactly as before: it lists no missing file.
    assert (directory / "sequence-manifest.jsonl").read_bytes() == snapshot_manifest
    assert not [p for p in directory.iterdir() if p.name.startswith(".staging")]
    # The files were already moved into place; the retry adopts them without downloading again.
    fetch = fetcher()
    result = append(site, created.sequence_id, new, fetch=fetch)

    assert fetch.calls == []  # reused, not fetched again
    assert len(result.added) == 2
    rows = manifest(site, created.sequence_id)
    assert len(rows) == 3 and len({r["source_url"] for r in rows}) == 3
    batches = store.read_batches(directory)
    assert [b["batch_number"] for b in batches] == [
        1,
        2,
    ]  # the orphan pending batch was discarded/recovered
    assert not list((directory / "sampling-batches").glob(".batch-*"))


def test_a_pending_batch_is_finalised_only_if_its_images_were_committed(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])
    directory = seq_dir(site, created.sequence_id)
    name = manifest(site, created.sequence_id)[0]["filename"]
    pending = directory / "sampling-batches" / ".batch-0002.pending"
    pending.write_text(json.dumps({"samples": [{"filename": name}]}))
    orphan = directory / "sampling-batches" / ".batch-0003.pending"
    orphan.write_text(json.dumps({"samples": [{"filename": "never-committed.jpg"}]}))

    intake.recover_pending_batches(directory)

    assert (directory / "sampling-batches" / "batch-0002.json").is_file() and not pending.exists()
    assert not orphan.exists() and not (directory / "sampling-batches" / "batch-0003.json").exists()


# ---- compatibility -------------------------------------------------------------------------


def edit_manifest(site: Path, sequence_id: str, **changes: Any) -> None:
    path = seq_dir(site, sequence_id) / "sequence-manifest.jsonl"
    rows = [{**json.loads(line), **changes} for line in path.read_text().splitlines()]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_a_different_camera_is_rejected_on_the_server_with_a_reason(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])
    edit_manifest(site, created.sequence_id, camera_id="CO_Other_Camera")

    with pytest.raises(intake.IntakeError, match="different camera"):
        append(site, created.sequence_id, [candidate(moment(9))])
    rows = intake.list_destinations(
        site, camera_slug=SLUG, timezone_name=TZ, site_id=SITE, nwis_site_id=STATION
    )
    assert rows[0]["compatible"] is False and "CO_Other_Camera" in rows[0]["reasons"][0]


def test_a_different_timezone_site_or_inconsistent_timestamps_are_rejected(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])
    directory = seq_dir(site, created.sequence_id)

    wrong_zone = intake.compatibility_problems(
        directory,
        camera_slug=SLUG,
        timezone_name="America/New_York",
        site_id=SITE,
        nwis_site_id=STATION,
    )
    assert any("time zone" in p for p in wrong_zone)
    wrong_site = intake.compatibility_problems(
        directory, camera_slug=SLUG, timezone_name=TZ, site_id="other-site", nwis_site_id=STATION
    )
    assert any("different site" in p for p in wrong_site)
    edit_manifest(site, created.sequence_id, local_time="2026-03-03T12:00:00+00:00")
    skewed = intake.compatibility_problems(
        directory, camera_slug=SLUG, timezone_name=TZ, site_id=SITE, nwis_site_id=STATION
    )
    assert any("local times do not match" in p for p in skewed)


def test_a_sequence_with_discharge_or_another_station_is_not_compatible(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])
    directory = seq_dir(site, created.sequence_id)
    source = json.loads((directory / "gauge-readings.json").read_text())

    source["parameter"]["code"] = "00060"
    (directory / "gauge-readings.json").write_text(json.dumps(source))
    assert any(
        "not gauge height" in p
        for p in intake.compatibility_problems(
            directory, camera_slug=SLUG, timezone_name=TZ, site_id=SITE, nwis_site_id=STATION
        )
    )
    source["parameter"]["code"] = "00065"
    source["association"]["nwis_site_id"] = "01234567"
    (directory / "gauge-readings.json").write_text(json.dumps(source))
    assert any(
        "different USGS station" in p
        for p in intake.compatibility_problems(
            directory, camera_slug=SLUG, timezone_name=TZ, site_id=SITE, nwis_site_id=STATION
        )
    )


def test_an_unknown_or_unsafe_destination_is_not_found(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])
    for bad in ("../../etc", "usgs-nope-2026-03-01-2026-03-28-all", "", created.sequence_id + "x"):
        with pytest.raises(intake.IntakeError):
            append(site, bad, [candidate(moment(9))])


def test_list_destinations_marks_each_sequence_and_shows_names_or_ids(tmp_path: Path) -> None:
    site, named = make(tmp_path, [3], display_name="Named")
    cands = [candidate(moment(6))]
    plain = intake.create_sequence(
        site_dir=site,
        site_id=SITE,
        camera_slug=SLUG,
        timezone_name=TZ,
        start_date="2026-03-01",
        end_date="2026-03-28",
        candidates=cands,
        provenance=provenance(cands),
        series=series(),
        gage_relationship="same_site",
        gage_relationship_note=None,
        fetch=fetcher(),
    )

    rows = {
        r["sequence_id"]: r
        for r in intake.list_destinations(
            site, camera_slug=SLUG, timezone_name=TZ, site_id=SITE, nwis_site_id=STATION
        )
    }

    assert rows[named.sequence_id]["label"] == "Named" and rows[named.sequence_id]["compatible"]
    assert (
        rows[plain.sequence_id]["label"] == plain.sequence_id
        and rows[plain.sequence_id]["display_name"] is None
    )


# ---- concurrency ---------------------------------------------------------------------------


def test_two_simultaneous_appends_of_the_same_images_add_each_image_once(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])
    cands = [candidate(moment(d)) for d in (9, 12, 15)]
    results: list[intake.IntakeResult] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        try:
            barrier.wait(5)
            results.append(append(site, created.sequence_id, list(cands)))
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert not errors
    assert sum(len(r.added) for r in results) == 3  # each image added by exactly one of them
    rows = manifest(site, created.sequence_id)
    assert len(rows) == 4 and len({r["source_url"] for r in rows}) == 4
    numbers = [b["batch_number"] for b in store.read_batches(seq_dir(site, created.sequence_id))]
    assert numbers == sorted(set(numbers))  # unique, ordered batch numbers


def test_an_append_waits_for_a_held_sequence_instead_of_interleaving(tmp_path: Path) -> None:
    site, created = make(tmp_path, [3])
    directory = seq_dir(site, created.sequence_id)
    inside = threading.Event()
    finished = threading.Event()

    def appender() -> None:
        append(site, created.sequence_id, [candidate(moment(9))])
        finished.set()

    with store.sequence_lock(directory):  # e.g. a validation run is starting
        thread = threading.Thread(target=appender)
        thread.start()
        inside.set()
        assert not finished.wait(0.5)  # the append cannot commit while the run holds the sequence
        assert len(manifest(site, created.sequence_id)) == 1
    assert finished.wait(10)
    thread.join(5)
    assert len(manifest(site, created.sequence_id)) == 2
    assert inside.is_set()

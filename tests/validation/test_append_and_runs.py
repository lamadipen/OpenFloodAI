"""Appending water-level samples never rewrites a finished run (Issue #214).

Real (tiny) JPEGs, real validation runs, real intake. Only the archive download is
replaced by a dictionary.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from openfloodai.ingestion import sequence_store as store
from openfloodai.ingestion import water_level_intake as intake
from openfloodai.ingestion.river_images import ImageSequenceCandidate, list_site_image_sequences
from openfloodai.ingestion.usgs_gage_data import GageReading, GageSeries
from openfloodai.validation.image_sequence_runner import (
    ImageSequenceValidationError,
    list_image_sequence_runs,
    read_image_sequence_run_detail,
    run_image_sequence_validation,
)

WRITE_JSON = "openfloodai.ingestion.water_level_intake.atomic_write_json"
WRITE_TEXT = "openfloodai.ingestion.water_level_intake.atomic_write_text"
SLUG = "CO_Test_Camera"
TZ = "America/Denver"
SITE = "site-demo-01"
STATION = "09999999"
ASSOCIATION = {
    "camera_id": SLUG,
    "nwis_site_id": STATION,
    "relationship": "same_site",
    "relationship_note": None,
    "source": "https://example.test/registry",
}


class Archive:
    """A fake camera archive: URL -> JPEG bytes, with matching listed sizes."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def candidate(
        self, day: int, value: int, hour: int = 18, minute: int = 0
    ) -> ImageSequenceCandidate:
        when = datetime(2026, 3, day, hour, minute, tzinfo=UTC)
        url = f"https://x.test/720/{SLUG}/{SLUG}___{when:%Y-%m-%dT%H-%M-%SZ}.jpg"
        ok, encoded = cv2.imencode(".jpg", np.full((30, 18, 3), value, dtype=np.uint8))
        assert ok
        self.files[url] = encoded.tobytes()
        return ImageSequenceCandidate(url, when, len(self.files[url]))

    def fetch(self, url: str) -> bytes:
        return self.files[url]


def series(days: int = 28) -> GageSeries:
    readings = [
        GageReading(
            datetime(2026, 3, d, 18, 0, tzinfo=UTC).isoformat(), float(d), ("A",), "approved"
        )
        for d in range(1, days + 1)
    ]
    return GageSeries(
        STATION, "00065", "gage height", "ft", False, readings, "https://usgs.example", 0
    )


def provenance(
    cands: list[ImageSequenceCandidate], group: str, preview: dict[int, float] | None = None
) -> dict[str, Any]:
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
        "gauge": {"parameter_code": "00065", "parameter_label": "gage height", "unit": "ft"},
        "thresholds": {"median": 14.0},
        "note": "relative",
        "samples": [
            {
                "filename": c.source_url.rsplit("/", 1)[-1],
                "group": group,
                "motivating_reading": {"value": float(c.captured_utc.day), "unit": "ft"},
                # The reading nearest the image, as the sampling preview found it at download time.
                "image_reading": {
                    "datetime_utc": datetime(
                        2026, 3, c.captured_utc.day, 18, 0, tzinfo=UTC
                    ).isoformat(),
                    "value": (preview or {}).get(c.captured_utc.day, float(c.captured_utc.day)),
                    "unit": "ft",
                    "qualifiers": ["A"],
                    "quality_status": "approved",
                },
                "gap_seconds": 0,
                "image_reading_gap_seconds": -(c.captured_utc.minute * 60),
            }
            for c in cands
        ],
        "groups": [{"group": group, "requested": 3, "approved": len(cands)}],
    }


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    site = tmp_path / "site"
    (site / "configs").mkdir(parents=True)
    (site / "configs" / "site.json").write_text(
        json.dumps(
            {
                "site_id": SITE,
                "camera_id": SLUG,
                "site_name": "Demo",
                "input_type": "local_video",
                "reference_region": {"x": 0, "y": 0, "width": 100, "height": 100},
            }
        ),
        encoding="utf-8",
    )
    archive = Archive()
    first = [archive.candidate(3, 70), archive.candidate(6, 90), archive.candidate(9, 110)]
    created = intake.create_sequence(
        site_dir=site,
        site_id=SITE,
        camera_slug=SLUG,
        timezone_name=TZ,
        start_date="2026-03-01",
        end_date="2026-03-28",
        candidates=first,
        provenance=provenance(first, "low"),
        series=series(),
        gage_relationship="same_site",
        gage_relationship_note=None,
        display_name="Windy Gap",
        fetch=archive.fetch,
    )
    return {"site": site, "archive": archive, "sequence_id": created.sequence_id, "first": first}


def append(
    world: dict[str, Any], cands: list[ImageSequenceCandidate], group: str = "high", **kwargs: Any
) -> intake.IntakeResult:
    return intake.append_to_sequence(
        site_dir=world["site"],
        sequence_id=world["sequence_id"],
        site_id=SITE,
        camera_slug=SLUG,
        timezone_name=TZ,
        nwis_site_id=STATION,
        start_date="2026-03-01",
        end_date="2026-03-28",
        candidates=cands,
        provenance=provenance(cands, group, kwargs.pop("preview", None)),
        series=kwargs.pop("series", series()),
        gage_relationship="same_site",
        gage_relationship_note=None,
        fetch=world["archive"].fetch,
    )


def baseline_name(world: dict[str, Any]) -> str:
    return str(world["first"][0].source_url.rsplit("/", 1)[-1])


def run(world: dict[str, Any]) -> Any:
    return run_image_sequence_validation(
        world["site"], world["sequence_id"], baseline_filename=baseline_name(world)
    )


def folder_hashes(path: Path) -> dict[str, str]:
    return {
        str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def filenames(detail: dict[str, Any]) -> list[str]:
    return [r["filename"] for r in detail["records"]]


def test_an_older_run_keeps_its_original_snapshot_after_an_append(world: dict[str, Any]) -> None:
    before_report = run(world)
    before = read_image_sequence_run_detail(world["site"], before_report.run_id)
    run_folder = world["site"] / "outputs" / "image-sequence-runs" / before_report.run_id
    files_before = folder_hashes(run_folder)
    assert len(filenames(before)) == 2 and before["summary"]["sequence_display_name"] == "Windy Gap"

    append(world, [world["archive"].candidate(12, 130), world["archive"].candidate(15, 150)])

    after = read_image_sequence_run_detail(world["site"], before_report.run_id)
    assert (
        after == before
    )  # records, gauge evidence, sampling record, setup: all exactly as they were
    assert filenames(after) == filenames(before)  # the new images are not silently included
    assert folder_hashes(run_folder) == files_before  # not a byte of the finished run changed
    assert after["water_level_selection"]["batch_count"] == 1
    assert (
        len(after["gauge_evidence"]["images"]) == 3
    )  # baseline + 2, not the 5 now in the sequence


def test_a_new_run_includes_the_appended_images_and_keeps_earlier_matches(
    world: dict[str, Any],
) -> None:
    first_report = run(world)
    first = read_image_sequence_run_detail(world["site"], first_report.run_id)
    append(world, [world["archive"].candidate(12, 130), world["archive"].candidate(15, 150)])

    second_report = run(world)
    second = read_image_sequence_run_detail(world["site"], second_report.run_id)

    assert second_report.run_id != first_report.run_id
    assert len(filenames(second)) == 4 and set(filenames(first)) < set(filenames(second))
    # earlier images keep exactly the gauge matches they had; new images have their own
    old = {i["filename"]: i for i in first["gauge_evidence"]["images"]}
    new = {i["filename"]: i for i in second["gauge_evidence"]["images"]}
    for name, evidence in old.items():
        assert new[name]["reading"] == evidence["reading"]
        assert new[name]["time_difference_seconds"] == evidence["time_difference_seconds"]
    added = set(new) - set(old)
    assert len(added) == 2 and all(new[n]["match_status"] == "matched" for n in added)
    assert sorted(new[n]["reading"]["value"] for n in added) == [12.0, 15.0]
    # sampling record: two batches, each image attributed to the batch that added it
    selection = second["water_level_selection"]
    assert selection["batch_count"] == 2
    groups = {n: s["group"] for n, s in selection["samples"].items()}
    assert sorted(groups.values()) == ["high", "high", "low", "low", "low"]
    assert {s["batch_number"] for s in selection["samples"].values()} == {1, 2}
    assert [r["run_id"] for r in list_image_sequence_runs(world["site"], world["sequence_id"])] == [
        second_report.run_id,
        first_report.run_id,
    ]


def test_batch_thresholds_stay_with_their_own_batch(world: dict[str, Any]) -> None:
    append(world, [world["archive"].candidate(12, 130)], "high")
    report = run(world)

    batches = read_image_sequence_run_detail(world["site"], report.run_id)["water_level_selection"][
        "batches"
    ]

    assert [b["batch_number"] for b in batches] == [1, 2]
    assert batches[0]["request"]["groups"] == ["low"] and batches[1]["request"]["groups"] == [
        "high"
    ]


def test_baseline_guides_and_labels_are_untouched_by_an_append(world: dict[str, Any]) -> None:
    config_path = world["site"] / "configs" / "site.json"
    labels = world["site"] / "labels" / "labels.jsonl"
    labels.parent.mkdir(parents=True)
    labels.write_text(
        '{"image": "' + baseline_name(world) + '", "label": "no_water_level_change"}\n'
    )
    config_before, labels_before = config_path.read_bytes(), labels.read_bytes()
    images_dir = world["site"] / "inputs" / "image-sequences" / world["sequence_id"] / "images"
    old_images = {p.name: p.read_bytes() for p in images_dir.iterdir()}

    append(world, [world["archive"].candidate(12, 130)])

    assert config_path.read_bytes() == config_before and labels.read_bytes() == labels_before
    assert {n: (images_dir / n).read_bytes() for n in old_images} == old_images
    assert not (world["site"] / "outputs").exists()  # appending starts no run and no review


def test_a_run_after_an_append_still_needs_an_explicit_baseline(world: dict[str, Any]) -> None:
    append(world, [world["archive"].candidate(12, 130)])
    with pytest.raises(ImageSequenceValidationError, match="Choose a baseline"):
        run_image_sequence_validation(world["site"], world["sequence_id"])


def test_runs_record_the_sequence_name_and_fall_back_to_the_id(
    world: dict[str, Any], tmp_path: Path
) -> None:
    named = read_image_sequence_run_detail(world["site"], run(world).run_id)["summary"]
    assert named["sequence_label"] == "Windy Gap" and named["sequence_display_name"] == "Windy Gap"

    cands = [world["archive"].candidate(20, 100), world["archive"].candidate(22, 120)]
    plain = intake.create_sequence(
        site_dir=world["site"],
        site_id=SITE,
        camera_slug=SLUG,
        timezone_name=TZ,
        start_date="2026-03-01",
        end_date="2026-03-28",
        candidates=cands,
        provenance=provenance(cands, "high"),
        series=series(),
        gage_relationship="same_site",
        gage_relationship_note=None,
        fetch=world["archive"].fetch,
    )
    report = run_image_sequence_validation(
        world["site"], plain.sequence_id, baseline_filename=cands[0].source_url.rsplit("/", 1)[-1]
    )
    summary = read_image_sequence_run_detail(world["site"], report.run_id)["summary"]
    assert (
        summary["sequence_display_name"] is None and summary["sequence_label"] == plain.sequence_id
    )
    rows = {r["sequence_id"]: r["label"] for r in list_site_image_sequences(world["site"])}
    assert (
        rows[world["sequence_id"]] == "Windy Gap" and rows[plain.sequence_id] == plain.sequence_id
    )


def test_a_run_waits_for_a_held_sequence_and_then_sees_a_consistent_snapshot(
    world: dict[str, Any],
) -> None:
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    done = threading.Event()
    box: dict[str, Any] = {}

    def runner() -> None:
        box["report"] = run(world)
        done.set()

    with store.sequence_lock(directory):  # e.g. an append is committing
        thread = threading.Thread(target=runner)
        thread.start()
        assert not done.wait(0.5)  # the run cannot start reading while the sequence is held
    assert done.wait(30)
    thread.join(5)
    assert len(box["report"].records) == 2


def test_concurrent_appends_and_runs_always_give_each_run_one_consistent_snapshot(
    world: dict[str, Any],
) -> None:
    errors: list[BaseException] = []
    stop = threading.Event()
    extra = [world["archive"].candidate(d, 80 + d) for d in (12, 15, 18, 21)]

    def appender() -> None:
        try:
            for item in extra:
                append(world, [item])
        except BaseException as error:  # noqa: BLE001
            errors.append(error)
        finally:
            stop.set()

    thread = threading.Thread(target=appender)
    thread.start()
    run_ids: list[str] = []
    while not stop.is_set() or len(run_ids) < 2:
        run_ids.append(run(world).run_id)
        if len(run_ids) > 40:
            break
    thread.join(60)

    assert not errors
    for run_id in run_ids:
        run_folder = world["site"] / "outputs" / "image-sequence-runs" / run_id
        manifest = [
            json.loads(line)
            for line in (run_folder / "inputs-used" / "sequence-manifest.snapshot.jsonl")
            .read_text()
            .splitlines()
        ]
        detail = read_image_sequence_run_detail(world["site"], run_id)
        downloaded = {r["filename"] for r in manifest if r["download_status"] == "downloaded"}
        compared = set(filenames(detail)) | {detail["summary"]["baseline_filename"]}
        assert (
            compared == downloaded
        )  # the run used exactly the manifest it froze, no more, no less
        batches = detail["water_level_selection"]["batches"]
        assert {s["batch_number"] for s in detail["water_level_selection"]["samples"].values()} <= {
            b["batch_number"] for b in batches
        }
        names = set(detail["water_level_selection"]["samples"])
        assert downloaded <= names  # every frozen image has its sampling provenance
    final = read_image_sequence_run_detail(world["site"], run(world).run_id)
    assert len(filenames(final)) == 3 + len(extra) - 1


# ---- gauge matches are saved once per image (review: appending must not change a match) ----


def match_of(detail: dict[str, Any], name: str) -> tuple[float | None, int | None]:
    row = next(i for i in detail["gauge_evidence"]["images"] if i["filename"] == name)
    reading = row["reading"]
    return (reading["value"] if reading else None, row["time_difference_seconds"])


def closer_series(day: int, value: float) -> GageSeries:
    """The usual series plus a NEW reading at 18:09 on `day`, nearer to an 18:10 image."""

    base = series()
    base.readings.append(
        GageReading(
            datetime(2026, 3, day, 18, 9, tzinfo=UTC).isoformat(), value, ("A",), "approved"
        )
    )
    return base


def world_with_offset_image(tmp_path: Path) -> dict[str, Any]:
    """A sequence whose day-3 image is at 18:10, so its nearest reading is 18:00 (3 ft, 10 min)."""

    site = tmp_path / "site"
    (site / "configs").mkdir(parents=True)
    (site / "configs" / "site.json").write_text(
        json.dumps(
            {
                "site_id": SITE,
                "camera_id": SLUG,
                "site_name": "Demo",
                "input_type": "local_video",
                "reference_region": {"x": 0, "y": 0, "width": 100, "height": 100},
            }
        ),
        encoding="utf-8",
    )
    archive = Archive()
    first = [
        archive.candidate(3, 70, minute=10),
        archive.candidate(6, 90),
        archive.candidate(9, 110),
    ]
    created = intake.create_sequence(
        site_dir=site,
        site_id=SITE,
        camera_slug=SLUG,
        timezone_name=TZ,
        start_date="2026-03-01",
        end_date="2026-03-28",
        candidates=first,
        provenance=provenance(first, "low"),
        series=series(),
        gage_relationship="same_site",
        gage_relationship_note=None,
        fetch=archive.fetch,
    )
    return {"site": site, "archive": archive, "sequence_id": created.sequence_id, "first": first}


def test_an_older_images_match_does_not_change_when_a_closer_reading_is_appended(
    tmp_path: Path,
) -> None:
    world = world_with_offset_image(tmp_path)
    old_name = baseline_name(world)  # the day-3 image at 18:10 is the first (and the baseline)
    other = world["first"][1].source_url.rsplit("/", 1)[-1]
    before = read_image_sequence_run_detail(world["site"], run(world).run_id)
    assert match_of(before, other) == (6.0, 0)

    # A later batch's fresh readings include one at 18:09 on day 3 (9 ft): closer to the old image.
    append(world, [world["archive"].candidate(12, 130)], series=closer_series(3, 9.0))
    readings = {
        r["datetime_utc"]: r["value"]
        for r in json.loads(
            (
                world["site"]
                / "inputs"
                / "image-sequences"
                / world["sequence_id"]
                / "gauge-readings.json"
            ).read_text()
        )["readings"]
    }
    assert (
        readings[datetime(2026, 3, 3, 18, 9, tzinfo=UTC).isoformat()] == 9.0
    )  # it is in the source

    after = read_image_sequence_run_detail(world["site"], run(world).run_id)
    # the baseline image (day 3, 18:10) is not compared, but its evidence is in the run
    base_row = next(i for i in after["gauge_evidence"]["images"] if i["filename"] == old_name)
    assert base_row["reading"]["value"] == 3.0 and base_row["time_difference_seconds"] == -600
    assert match_of(after, other) == match_of(before, other)  # untouched images keep their match


def test_a_new_image_keeps_the_reading_its_preview_showed_not_an_older_saved_value(
    tmp_path: Path,
) -> None:
    world = world_with_offset_image(tmp_path)
    new = world["archive"].candidate(12, 130)
    new_name = new.source_url.rsplit("/", 1)[-1]
    # Fresh preview data says the day-12 reading is now 99 ft; the saved source still holds 12 ft.
    append(world, [new], preview={12: 99.0})

    detail = read_image_sequence_run_detail(world["site"], run(world).run_id)

    assert match_of(detail, new_name) == (99.0, 0)  # what the sampling preview showed
    row = next(i for i in detail["gauge_evidence"]["images"] if i["filename"] == new_name)
    assert row["match_status"] == "matched" and row["reading"]["parameter_label"] == "gage height"
    assert row["reading"]["quality_status"] == "approved" and row["reading"]["unit"] == "ft"


def test_images_added_before_matches_were_saved_are_frozen_at_the_first_append(
    tmp_path: Path,
) -> None:
    world = world_with_offset_image(tmp_path)
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    (directory / "gauge-matches.json").unlink()  # a sequence made before matches were saved
    old_name = baseline_name(world)
    before = read_image_sequence_run_detail(world["site"], run(world).run_id)
    other = world["first"][1].source_url.rsplit("/", 1)[-1]

    append(world, [world["archive"].candidate(12, 130)], series=closer_series(6, 77.0))

    matches = json.loads((directory / "gauge-matches.json").read_text())["matches"]
    assert matches[old_name]["origin"] == "existing_before_append"
    assert matches[old_name]["reading"]["value"] == 3.0
    after = read_image_sequence_run_detail(world["site"], run(world).run_id)
    assert match_of(after, other) == match_of(before, other)


def test_saved_matches_are_append_only_for_existing_images(tmp_path: Path) -> None:
    world = world_with_offset_image(tmp_path)
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    first = json.loads((directory / "gauge-matches.json").read_text())["matches"]

    append(world, [world["archive"].candidate(12, 130)], preview={12: 5.0})
    append(
        world,
        [world["archive"].candidate(15, 150)],
        preview={15: 6.0},
        series=closer_series(3, 9.0),
    )

    later = json.loads((directory / "gauge-matches.json").read_text())["matches"]
    assert all(later[name] == entry for name, entry in first.items())  # never rewritten
    assert len(later) == len(first) + 2
    assert {
        later[n]["batch_number"] for n in later if later[n]["origin"] == "sampling_preview"
    } == {1, 2, 3}


def test_a_completed_run_is_unchanged_by_the_new_matches(tmp_path: Path) -> None:
    world = world_with_offset_image(tmp_path)
    report = run(world)
    folder = world["site"] / "outputs" / "image-sequence-runs" / report.run_id
    before = folder_hashes(folder)

    append(world, [world["archive"].candidate(12, 130)], series=closer_series(3, 9.0))
    run(world)

    assert folder_hashes(folder) == before


# ---- an interrupted append is repaired before the next run reads the sequence ----------------


def crash_at(
    monkeypatch: pytest.MonkeyPatch, *, final_batch: bool = False, summary: bool = False
) -> None:
    import os

    real_replace = os.replace
    real_json = store.atomic_write_json

    def replace(src: Any, dst: Any) -> None:
        if final_batch and "sampling-batches" in str(dst) and Path(dst).name.startswith("batch-"):
            raise OSError("power loss before the batch was finalized")
        real_replace(src, dst)

    def write_json(path: Path, payload: Any) -> None:
        if summary and path.name == "download-summary.json":
            raise OSError("power loss before the summary was refreshed")
        real_json(path, payload)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(WRITE_JSON, write_json)


def test_a_run_recovers_a_batch_left_pending_by_an_interrupted_append(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    new = world["archive"].candidate(12, 130)
    new_name = new.source_url.rsplit("/", 1)[-1]
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    with monkeypatch.context() as patch:
        crash_at(patch, final_batch=True)
        with pytest.raises(OSError):
            append(world, [new])
    # The manifest already lists the image, but its batch is still a pending file.
    assert new_name in (directory / "sequence-manifest.jsonl").read_text()
    assert list((directory / "sampling-batches").glob(".batch-*.pending"))
    assert not (directory / "sampling-batches" / "batch-0002.json").exists()

    report = run(world)

    detail = read_image_sequence_run_detail(world["site"], report.run_id)
    assert new_name in filenames(detail)  # the run includes the new image...
    assert (
        detail["water_level_selection"]["samples"][new_name]["batch_number"] == 2
    )  # ...and its history
    assert detail["water_level_selection"]["batch_count"] == 2
    assert (directory / "sampling-batches" / "batch-0002.json").is_file()
    assert not list((directory / "sampling-batches").glob(".batch-*.pending"))
    summary = json.loads((directory / "download-summary.json").read_text())
    assert summary["downloaded_count"] == 4 and summary["batch_count"] == 2
    assert len(summary["records"]) == 4


def test_a_run_discards_a_pending_batch_whose_append_never_committed(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    new = world["archive"].candidate(12, 130)
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    manifest_before = (directory / "sequence-manifest.jsonl").read_bytes()
    real_write = store.atomic_write_text

    def crash_on_manifest(path: Path, text: str) -> None:
        if path.name == "sequence-manifest.jsonl":
            raise OSError("power loss")
        real_write(path, text)

    monkeypatch.setattr(
        "openfloodai.ingestion.water_level_intake.atomic_write_text", crash_on_manifest
    )
    with pytest.raises(OSError):
        append(world, [new])
    monkeypatch.undo()
    assert list((directory / "sampling-batches").glob(".batch-*.pending"))

    report = run(world)

    detail = read_image_sequence_run_detail(world["site"], report.run_id)
    assert (directory / "sequence-manifest.jsonl").read_bytes() == manifest_before
    assert detail["water_level_selection"]["batch_count"] == 1 and len(filenames(detail)) == 2
    assert not list((directory / "sampling-batches").glob(".batch-*.pending"))


def test_a_run_refreshes_a_summary_left_stale_by_an_interrupted_append(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    new = world["archive"].candidate(12, 130)
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    with monkeypatch.context() as patch:
        crash_at(patch, summary=True)
        with pytest.raises(OSError):
            append(world, [new])
    stale = json.loads((directory / "download-summary.json").read_text())
    assert stale["downloaded_count"] == 3  # the manifest was committed but the summary was not

    run(world)

    fresh = json.loads((directory / "download-summary.json").read_text())
    assert (
        fresh["downloaded_count"] == 4 and fresh["batch_count"] == 2 and len(fresh["records"]) == 4
    )
    rows = list_site_image_sequences(world["site"])
    assert rows[0]["downloaded_count"] == 4 and rows[0]["label"] == "Windy Gap"


def test_recovery_leaves_a_healthy_sequence_untouched(world: dict[str, Any]) -> None:
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    before = folder_hashes(directory)

    intake.recover_interrupted_append(directory)

    assert folder_hashes(directory) == before


# ---- a failed append must not change gauge results (review on d6fe7a7) ----------------------


GAUGE_FILES = ("gauge-readings.json", "gauge-readings-summary.json", "gauge-matches.json")


def flood_series() -> GageSeries:
    """The usual series plus one huge reading at a NEW timestamp (the review's 999 ft)."""

    base = series()
    base.readings.append(
        GageReading(
            datetime(2026, 3, 20, 6, 0, tzinfo=UTC).isoformat(), 999.0, ("P",), "provisional"
        )
    )
    return base


def gauge_bytes(world: dict[str, Any]) -> dict[str, bytes]:
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    return {name: (directory / name).read_bytes() for name in GAUGE_FILES}


def highest(detail: dict[str, Any]) -> float:
    return float(detail["gauge_evidence"]["peak_events"]["highest"]["event_reading"]["value"])


def fail_manifest_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    real_write = store.atomic_write_text

    def crash(path: Path, text: str) -> None:
        if path.name == "sequence-manifest.jsonl":
            raise OSError("power loss at the manifest commit")
        real_write(path, text)

    monkeypatch.setattr(WRITE_TEXT, crash)


def test_a_failed_append_leaves_the_gauge_results_exactly_as_they_were(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    before_run = read_image_sequence_run_detail(world["site"], run(world).run_id)
    assert (
        highest(before_run) == 3.0 + 0 or highest(before_run) == 28.0
    )  # the usual series peaks at 28
    gauge_before = gauge_bytes(world)
    manifest_before = (directory / "sequence-manifest.jsonl").read_bytes()
    summary_before = (directory / "download-summary.json").read_bytes()

    with monkeypatch.context() as patch:
        fail_manifest_commit(patch)
        with pytest.raises(OSError):
            append(world, [world["archive"].candidate(12, 130)], series=flood_series())

    # nothing about the sequence changed, including the gauge files (the 999 was only staged)
    assert gauge_bytes(world) == gauge_before
    assert (directory / "sequence-manifest.jsonl").read_bytes() == manifest_before
    assert (directory / "download-summary.json").read_bytes() == summary_before

    # a validation run WITHOUT retrying the append: recovery discards the staged gauge data
    after = read_image_sequence_run_detail(world["site"], run(world).run_id)
    assert highest(after) == highest(before_run) == 28.0
    assert len(filenames(after)) == 2 and after["water_level_selection"]["batch_count"] == 1
    assert gauge_bytes(world) == gauge_before
    batches = directory / "sampling-batches"
    assert not list(batches.glob(".batch-*")) and not list(batches.glob(".gauge-*"))
    assert json.loads((directory / "download-summary.json").read_text())["downloaded_count"] == 3
    assert json.loads((directory / "download-summary.json").read_text())["batch_count"] == 1


def test_a_failed_append_then_a_successful_retry_still_applies_its_gauge_data_once(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    new = world["archive"].candidate(12, 130)
    with monkeypatch.context() as patch:
        fail_manifest_commit(patch)
        with pytest.raises(OSError):
            append(world, [new], series=flood_series())

    result = append(world, [new], series=flood_series())

    detail = read_image_sequence_run_detail(world["site"], run(world).run_id)
    assert len(result.added) == 1 and highest(detail) == 999.0  # applied now, once, with the image
    source = json.loads(
        (
            world["site"]
            / "inputs"
            / "image-sequences"
            / world["sequence_id"]
            / "gauge-readings.json"
        ).read_text()
    )
    assert [b["batch_id"] for b in source["appended_batches"]] == ["batch-0001", "batch-0002"]
    stamps = [r["datetime_utc"] for r in source["readings"]]
    assert len(stamps) == len(set(stamps))


def test_a_committed_append_whose_gauge_move_was_interrupted_is_finished_by_the_next_run(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    new = world["archive"].candidate(12, 130)
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    gauge_before = gauge_bytes(world)
    with monkeypatch.context() as patch:
        patch.setattr(
            intake,
            "_finalize_pending_gauge",
            lambda *_: (_ for _ in ()).throw(OSError("power loss")),
        )
        with pytest.raises(OSError):
            append(world, [new], series=flood_series())
    # the manifest committed (the image is in it) but the gauge files were not moved yet
    assert new.source_url.rsplit("/", 1)[-1] in (directory / "sequence-manifest.jsonl").read_text()
    assert gauge_bytes(world) == gauge_before
    assert list((directory / "sampling-batches").glob(".gauge-*"))

    detail = read_image_sequence_run_detail(world["site"], run(world).run_id)

    assert highest(detail) == 999.0  # the committed append's gauge data is now in place
    assert gauge_bytes(world) != gauge_before
    assert len(filenames(detail)) == 3 and detail["water_level_selection"]["batch_count"] == 2
    assert not list((directory / "sampling-batches").glob(".gauge-*"))
    assert not list((directory / "sampling-batches").glob(".batch-*"))


def test_a_gauge_move_interrupted_half_way_is_completed_without_losing_or_repeating_anything(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    new = world["archive"].candidate(12, 130)
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    real_replace = os.replace
    calls = {"gauge": 0}

    def replace(src: Any, dst: Any) -> None:
        if Path(dst).parent == directory and Path(dst).name in GAUGE_FILES:
            calls["gauge"] += 1
            if calls["gauge"] == 2:
                raise OSError("power loss in the middle of moving the gauge files")
        real_replace(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", replace)
        with pytest.raises(OSError):
            append(world, [new], series=flood_series())
    staged = list((directory / "sampling-batches").glob(".gauge-*/*.json"))
    assert staged  # some files are still waiting

    detail = read_image_sequence_run_detail(world["site"], run(world).run_id)

    assert highest(detail) == 999.0 and len(filenames(detail)) == 3
    assert not list((directory / "sampling-batches").glob(".gauge-*"))
    source = json.loads((directory / "gauge-readings.json").read_text())
    stamps = [r["datetime_utc"] for r in source["readings"]]
    batch_ids = [b["batch_id"] for b in source["appended_batches"]]
    assert len(stamps) == len(set(stamps)) and batch_ids == ["batch-0001", "batch-0002"]


def test_a_staged_gauge_folder_with_no_pending_batch_is_never_applied(
    world: dict[str, Any],
) -> None:
    directory = world["site"] / "inputs" / "image-sequences" / world["sequence_id"]
    gauge_before = gauge_bytes(world)
    stray = directory / "sampling-batches" / ".gauge-0009.pending"
    stray.mkdir(parents=True)
    (stray / "gauge-readings.json").write_text('{"readings": [], "poison": true}')

    run(world)

    assert not stray.exists() and gauge_bytes(world) == gauge_before

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

    def candidate(self, day: int, value: int, hour: int = 18) -> ImageSequenceCandidate:
        when = datetime(2026, 3, day, hour, 0, tzinfo=UTC)
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


def provenance(cands: list[ImageSequenceCandidate], group: str) -> dict[str, Any]:
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
        "note": "relative",
        "samples": [
            {
                "filename": c.source_url.rsplit("/", 1)[-1],
                "group": group,
                "motivating_reading": {"value": float(c.captured_utc.day), "unit": "ft"},
                "image_reading": {"value": float(c.captured_utc.day), "unit": "ft"},
                "gap_seconds": 0,
                "image_reading_gap_seconds": 0,
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
        provenance=provenance(cands, group),
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

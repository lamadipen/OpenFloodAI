"""Tests for running local validation against a saved USGS image sequence (issue #182)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from openfloodai.config import write_evidence_adapter_override
from openfloodai.evidence.settings import write_global_adapter_setting
from openfloodai.review.event_reviews import compute_evidence_key, set_event_review
from openfloodai.validation.image_sequence_runner import (
    RESULT_CAMERA_OR_IMAGE_PROBLEM,
    RESULT_CANNOT_JUDGE_WATER_LEVEL,
    RESULT_NO_WATER_LEVEL_CHANGE,
    RESULT_POSSIBLE_WATER_LEVEL_CHANGE,
    ImageSequenceValidationError,
    _classify_comparison,
    list_image_sequence_runs,
    read_image_sequence_run_detail,
    resolve_image_sequence_run_image,
    run_image_sequence_validation,
)

SEQUENCE_ID = "usgs-camera-demo-2026-09-01-2026-09-01-all"
FULL_REGION: dict[str, object] = {"x": 0, "y": 0, "width": 100, "height": 100}


def make_site(
    site_dir: Path,
    *,
    reference_region: dict[str, object] | None = FULL_REGION,
    normal_waterline_guides: list[dict[str, object]] | None = None,
) -> None:
    (site_dir / "configs").mkdir(parents=True)
    config: dict[str, object] = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo Site",
        "input_type": "local_video",
    }
    if reference_region is not None:
        config["reference_region"] = reference_region
    if normal_waterline_guides is not None:
        config["normal_waterline_guides"] = normal_waterline_guides
    (site_dir / "configs" / "site.json").write_text(json.dumps(config), encoding="utf-8")


def confirmed_guide_record(guide_id: str = "left-bank") -> dict[str, object]:
    return {
        "id": guide_id,
        "label": "Left bank",
        "points": [{"x": 10, "y": 10}, {"x": 20, "y": 20}],
        "video_id": "video-001",
        "video_time_seconds": 4.5,
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "status": "confirmed",
        "normal_condition": True,
        "notes": "Clear view of the bank.",
        "confirmed_at": "2026-08-01T00:00:00+00:00",
        "invalidated_at": None,
        "invalidation_reason": None,
    }


def write_frame(path: Path, value: int, *, bottom_third_value: int | None = None) -> None:
    frame = np.full((30, 18, 3), value, dtype=np.uint8)
    if bottom_third_value is not None:
        frame[20:, :, :] = bottom_third_value
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), frame)


def write_manifest(sequence_dir: Path, records: list[dict[str, object]]) -> None:
    sequence_dir.mkdir(parents=True, exist_ok=True)
    with (sequence_dir / "sequence-manifest.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def manifest_record(filename: str, captured_at: str, status: str) -> dict[str, object]:
    return {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "source_url": f"https://example.test/{filename}",
        "captured_at_utc": captured_at,
        "local_time": captured_at,
        "filename": filename,
        "file_size_bytes": 100,
        "download_status": status,
        "source_system": "usgs_nims",
    }


def test_run_classifies_all_four_result_states_and_writes_outputs(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"

    write_frame(images_dir / "baseline.jpg", 30)
    write_frame(images_dir / "no-change.jpg", 30)
    write_frame(images_dir / "possible-change.jpg", 30, bottom_third_value=220)
    write_frame(images_dir / "camera-problem.jpg", 220)
    write_frame(images_dir / "dark.jpg", 3)

    write_manifest(
        sequence_dir,
        [
            manifest_record("baseline.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("no-change.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
            manifest_record("possible-change.jpg", "2026-09-01T02:00:00+00:00", "downloaded"),
            manifest_record("camera-problem.jpg", "2026-09-01T03:00:00+00:00", "downloaded"),
            manifest_record("dark.jpg", "2026-09-01T04:00:00+00:00", "downloaded"),
            manifest_record("missing.jpg", "2026-09-01T05:00:00+00:00", "missing"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    assert report.baseline_filename == "baseline.jpg"
    results_by_filename = {record.filename: record.result for record in report.records}
    assert results_by_filename["no-change.jpg"] == RESULT_NO_WATER_LEVEL_CHANGE
    assert results_by_filename["possible-change.jpg"] == RESULT_POSSIBLE_WATER_LEVEL_CHANGE
    assert results_by_filename["camera-problem.jpg"] == RESULT_CAMERA_OR_IMAGE_PROBLEM
    assert results_by_filename["dark.jpg"] == RESULT_CAMERA_OR_IMAGE_PROBLEM
    assert results_by_filename["missing.jpg"] == RESULT_CAMERA_OR_IMAGE_PROBLEM

    assert report.possible_change_count == 1
    assert report.no_change_count == 1
    assert report.camera_or_image_problem_count == 3
    assert report.cannot_judge_count == 0

    run_dir = report.run_dir
    assert run_dir.parent == site_dir / "outputs" / "image-sequence-runs"
    assert (run_dir / "run-summary.json").is_file()
    assert (run_dir / "image-sequence-records.jsonl").is_file()
    assert (run_dir / "image-sequence-report.md").is_file()
    assert (run_dir / "inputs-used" / "sequence-manifest.snapshot.jsonl").is_file()
    assert (run_dir / "inputs-used" / "site-config.snapshot.json").is_file()
    assert (run_dir / "inputs-used" / "receipt.json").is_file()

    review_images = sorted((run_dir / "review-images").glob("*.png"))
    assert review_images, "the biggest-change comparison should produce review images"

    summary = json.loads((run_dir / "run-summary.json").read_text())
    assert summary["sequence_id"] == SEQUENCE_ID
    assert summary["biggest_change_filename"] == "possible-change.jpg"
    assert summary["review_images_generated"] is True
    assert summary["effective_evidence_adapters"] == [
        {
            "plugin_id": "pixel_change_region_v1",
            "plugin_version": "1.0.0",
            "enabled": True,
            "source": "catalog_default",
        },
        {
            "plugin_id": "riverbank_crossing_v1",
            "plugin_version": "1.0.0",
            "enabled": False,
            "source": "catalog_default",
        },
    ]

    report_text = (run_dir / "image-sequence-report.md").read_text()
    assert "Safety Boundary" in report_text
    assert "possible-change.jpg" in report_text

    records_lines = (run_dir / "image-sequence-records.jsonl").read_text().splitlines()
    assert len(records_lines) == 5

    evidence_lines = (run_dir / "evidence-records.jsonl").read_text().splitlines()
    assert len(evidence_lines) == 10
    all_evidence_rows = [json.loads(line) for line in evidence_lines]
    evidence_rows = [
        row for row in all_evidence_rows if row["plugin_id"] == "pixel_change_region_v1"
    ]
    assert len(evidence_rows) == 5
    statuses = [row["status"] for row in evidence_rows]
    # no-change/possible-change/camera-problem/dark all reach a real
    # compare_region_signals() call (camera-problem and dark are still
    # readable images -- they're only judged a "camera or image problem"
    # by brightness, not by a failed comparison), so those 4 rows carry a
    # real measurement. Only "missing.jpg" never got downloaded, so it's
    # the one "unavailable" row -- no fabricated score for a missing image.
    assert statuses.count("available") == 4
    assert statuses.count("unavailable") == 1
    for row in evidence_rows:
        assert row["plugin_id"] == "pixel_change_region_v1"
        if row["status"] == "available":
            assert isinstance(row["value"], float)
        else:
            assert row["value"] is None

    # riverbank_crossing_v1 is disabled by default (unevaluated): every
    # readable image gets a "disabled" row (never a fabricated measurement),
    # and never affects pixel_change_region_v1's own rows above. The one
    # never-downloaded image still gets its own "unavailable" row, same as
    # pixel_change's -- a missing image is a fact about the image, not the
    # adapter's enabled state.
    riverbank_statuses = [
        row["status"] for row in all_evidence_rows if row["plugin_id"] == "riverbank_crossing_v1"
    ]
    assert riverbank_statuses.count("disabled") == 4
    assert riverbank_statuses.count("unavailable") == 1


def test_run_marks_the_row_cannot_judge_when_the_adapter_is_disabled_globally(
    tmp_path: Path,
) -> None:
    """Disabling the only signal source must show up in the real result too.

    Classification is now driven by the adapter's evidence, not a parallel
    read of the same raw dict -- so turning the adapter off has to mean
    something for the actual row, not just the evidence side channel. It
    must never silently keep reporting "no change" with no real signal
    behind it.
    """

    # site_dir must be nested as <sites_dir>/<folder_name>, matching real
    # production layout (home_server.py's _resolve_site_dir) -- the
    # reference directory is a sibling of sites_dir, not of the site itself.
    site_dir = tmp_path / "sites" / "site"
    make_site(site_dir)
    write_global_adapter_setting(tmp_path / "reference", "pixel_change_region_v1", False)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"

    write_frame(images_dir / "baseline.jpg", 30)
    write_frame(images_dir / "no-change.jpg", 30)

    write_manifest(
        sequence_dir,
        [
            manifest_record("baseline.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("no-change.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    assert report.records[0].result == RESULT_CANNOT_JUDGE_WATER_LEVEL
    assert report.records[0].region_change_score is None

    evidence_lines = (report.run_dir / "evidence-records.jsonl").read_text().splitlines()
    assert len(evidence_lines) == 2
    all_rows = [json.loads(line) for line in evidence_lines]
    row = next(r for r in all_rows if r["plugin_id"] == "pixel_change_region_v1")
    assert row["status"] == "disabled"
    assert row["value"] is None
    assert "ADAPTER_DISABLED" in row["reason_codes"]


def test_disabled_adapter_does_not_hide_a_missing_or_unreadable_image(tmp_path: Path) -> None:
    """A missing/unreadable image is a fact about the image, not the adapter.

    Dataset-quality counts (camera_or_image_problem) must stay accurate
    even when the adapter is off -- disabling a signal must never make a
    real data-quality problem disappear into "cannot judge".
    """

    site_dir = tmp_path / "sites" / "site"
    make_site(site_dir)
    write_global_adapter_setting(tmp_path / "reference", "pixel_change_region_v1", False)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"

    write_frame(images_dir / "baseline.jpg", 30)
    write_frame(images_dir / "no-change.jpg", 30)
    # "missing.jpg" is deliberately never written -- download_status says
    # downloaded, but the file isn't there, so this is an unreadable image.

    write_manifest(
        sequence_dir,
        [
            manifest_record("baseline.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("no-change.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
            manifest_record("missing.jpg", "2026-09-01T02:00:00+00:00", "missing"),
            manifest_record("unreadable.jpg", "2026-09-01T03:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    results_by_filename = {record.filename: record.result for record in report.records}
    assert results_by_filename["missing.jpg"] == RESULT_CAMERA_OR_IMAGE_PROBLEM
    assert results_by_filename["unreadable.jpg"] == RESULT_CAMERA_OR_IMAGE_PROBLEM
    # The only genuinely valid, readable image still gets the disabled treatment.
    assert results_by_filename["no-change.jpg"] == RESULT_CANNOT_JUDGE_WATER_LEVEL

    pixel_change_rows = [
        json.loads(line)
        for line in (report.run_dir / "evidence-records.jsonl").read_text().splitlines()
        if json.loads(line)["plugin_id"] == "pixel_change_region_v1"
    ]
    evidence_by_status: dict[str, list[list[str]]] = {}
    for row in pixel_change_rows:
        evidence_by_status.setdefault(row["status"], []).append(row["reason_codes"])
    assert evidence_by_status["unavailable"] == [
        ["IMAGE_NOT_DOWNLOADED"],
        ["IMAGE_FILE_UNREADABLE"],
    ]
    assert evidence_by_status["disabled"] == [["ADAPTER_DISABLED"]]


def test_run_site_override_re_enables_an_adapter_disabled_globally(tmp_path: Path) -> None:
    site_dir = tmp_path / "sites" / "site"
    make_site(site_dir)
    write_global_adapter_setting(tmp_path / "reference", "pixel_change_region_v1", False)
    write_evidence_adapter_override(
        site_dir / "configs" / "site.json", "pixel_change_region_v1", True
    )
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"

    write_frame(images_dir / "baseline.jpg", 30)
    write_frame(images_dir / "no-change.jpg", 30)

    write_manifest(
        sequence_dir,
        [
            manifest_record("baseline.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("no-change.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    evidence_lines = (report.run_dir / "evidence-records.jsonl").read_text().splitlines()
    all_rows = [json.loads(line) for line in evidence_lines]
    row = next(r for r in all_rows if r["plugin_id"] == "pixel_change_region_v1")
    assert row["status"] == "available"
    assert row["value"] == 0.0

    summary = json.loads((report.run_dir / "run-summary.json").read_text())
    assert summary["effective_evidence_adapters"] == [
        {
            "plugin_id": "pixel_change_region_v1",
            "plugin_version": "1.0.0",
            "enabled": True,
            "source": "site_override",
        },
        {
            "plugin_id": "riverbank_crossing_v1",
            "plugin_version": "1.0.0",
            "enabled": False,
            "source": "catalog_default",
        },
    ]


def test_run_records_global_override_as_the_adapter_source_when_no_site_override(
    tmp_path: Path,
) -> None:
    """catalog_default and global_override must be distinguished, not both called "global".

    Two runs can both resolve to enabled=True for different reasons: one
    because nobody ever touched the setting (catalog_default), another
    because someone explicitly turned the global default back on
    (global_override). Auditing a run needs to know which actually
    happened.
    """

    site_dir = tmp_path / "sites" / "site"
    make_site(site_dir)
    write_global_adapter_setting(tmp_path / "reference", "pixel_change_region_v1", True)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"

    write_frame(images_dir / "baseline.jpg", 30)
    write_frame(images_dir / "no-change.jpg", 30)

    write_manifest(
        sequence_dir,
        [
            manifest_record("baseline.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("no-change.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    summary = json.loads((report.run_dir / "run-summary.json").read_text())
    assert summary["effective_evidence_adapters"] == [
        {
            "plugin_id": "pixel_change_region_v1",
            "plugin_version": "1.0.0",
            "enabled": True,
            "source": "global_override",
        },
        {
            "plugin_id": "riverbank_crossing_v1",
            "plugin_version": "1.0.0",
            "enabled": False,
            "source": "catalog_default",
        },
    ]


def image_sequence_guide_record(
    guide_id: str = "left-bank",
    *,
    image_sequence_id: str,
    image_filename: str,
    points: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """A confirmed guide sourced from a saved image-sequence still, not a video.

    riverbank_crossing_v1 only treats a guide as usable when its saved
    source actually matches the run: for an image-sequence run, that means
    guide.image_sequence_id == the sequence_id being validated (see
    GUIDE_SOURCE_MISMATCH in image_sequence_runner.py).
    """

    return {
        "id": guide_id,
        "label": "Left bank",
        "points": points or [{"x": 10, "y": 10}, {"x": 20, "y": 20}],
        "video_id": "",
        "video_time_seconds": 0,
        "image_sequence_id": image_sequence_id,
        "image_filename": image_filename,
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "status": "confirmed",
        "normal_condition": True,
        "notes": "Clear view of the bank.",
        "confirmed_at": "2026-08-01T00:00:00+00:00",
        "invalidated_at": None,
        "invalidation_reason": None,
    }


def test_riverbank_crossing_enabled_with_a_confirmed_guide_produces_available_evidence(
    tmp_path: Path,
) -> None:
    """Proves the guide's OWN source image is used, not this run's baseline.jpg.

    baseline.jpg (the run's own chosen baseline, unrelated to the guide) is
    a uniform "already flooded" frame; the guide's real source
    (guide-source.jpg) and the compared image (no-change.jpg) both show the
    true normal condition (dry land above the line, water below). If the
    adapter used baseline.jpg instead of the guide's own source -- the
    exact bug this test guards against -- the land side would appear to
    change from "flooded" to "dry", registering a false crossing. Using
    the guide's real source correctly reports no change at all.
    """

    site_dir = tmp_path / "sites" / "site"
    guide_points: list[dict[str, object]] = [{"x": 0, "y": 70}, {"x": 100, "y": 70}]
    guide = {
        **image_sequence_guide_record(
            image_sequence_id=SEQUENCE_ID,
            image_filename="guide-source.jpg",
            points=guide_points,
        ),
        "water_side_point": {"x": 50, "y": 95},
    }
    make_site(site_dir, normal_waterline_guides=[guide])
    write_global_adapter_setting(tmp_path / "reference", "riverbank_crossing_v1", True)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"

    # The run's OWN baseline: a uniform, already-anomalous frame, deliberately
    # different from the guide's real source below.
    write_frame(images_dir / "baseline.jpg", 50, bottom_third_value=50)
    # The guide's real source and the compared image both show the true
    # normal condition: land (top) bright/dry, water (bottom) dark/wet.
    write_frame(images_dir / "guide-source.jpg", 200, bottom_third_value=50)
    write_frame(images_dir / "no-change.jpg", 200, bottom_third_value=50)
    write_manifest(
        sequence_dir,
        [
            manifest_record("baseline.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("no-change.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    all_rows = [
        json.loads(line)
        for line in (report.run_dir / "evidence-records.jsonl").read_text().splitlines()
    ]
    row = next(r for r in all_rows if r["plugin_id"] == "riverbank_crossing_v1")
    assert row["status"] == "available"
    assert row["provenance"]["guide_id"] == "left-bank"
    # Comparing against the guide's real source (identical to no-change.jpg)
    # correctly finds nothing. Comparing against the run's own baseline.jpg
    # (the bug this guards against) would instead show the land side
    # "changing" from flooded to dry and wrongly report a crossing.
    assert row["value"] == 0.0
    assert "NO_CLEAR_CROSSING" in row["reason_codes"]


def test_riverbank_crossing_reports_source_mismatch_for_a_guide_from_another_sequence(
    tmp_path: Path,
) -> None:
    """A guide traced on a DIFFERENT sequence's image must never supply a baseline here.

    Regression for the exact bug reported in review: without this check, the
    pipeline would silently compare against this run's own chosen baseline
    image instead of refusing -- convincing but wrong crossing evidence.
    """

    site_dir = tmp_path / "sites" / "site"
    guide = {
        **image_sequence_guide_record(
            image_sequence_id="a-completely-different-sequence",
            image_filename="baseline.jpg",
        ),
        "water_side_point": {"x": 50, "y": 50},
    }
    make_site(site_dir, normal_waterline_guides=[guide])
    write_global_adapter_setting(tmp_path / "reference", "riverbank_crossing_v1", True)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"

    write_frame(images_dir / "baseline.jpg", 30)
    write_frame(images_dir / "no-change.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("baseline.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("no-change.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    all_rows = [
        json.loads(line)
        for line in (report.run_dir / "evidence-records.jsonl").read_text().splitlines()
    ]
    row = next(r for r in all_rows if r["plugin_id"] == "riverbank_crossing_v1")
    assert row["status"] == "invalid"
    assert row["reason_codes"] == ["GUIDE_SOURCE_MISMATCH"]


def test_riverbank_crossing_reports_baseline_missing_when_the_guides_image_is_gone(
    tmp_path: Path,
) -> None:
    """The guide's source matches this sequence, but its exact image file is missing."""

    site_dir = tmp_path / "sites" / "site"
    guide = {
        **image_sequence_guide_record(
            image_sequence_id=SEQUENCE_ID, image_filename="deleted-guide-source.jpg"
        ),
        "water_side_point": {"x": 50, "y": 50},
    }
    make_site(site_dir, normal_waterline_guides=[guide])
    write_global_adapter_setting(tmp_path / "reference", "riverbank_crossing_v1", True)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"

    write_frame(images_dir / "baseline.jpg", 30)
    write_frame(images_dir / "no-change.jpg", 30)
    # "deleted-guide-source.jpg" is deliberately never written.
    write_manifest(
        sequence_dir,
        [
            manifest_record("baseline.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("no-change.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    all_rows = [
        json.loads(line)
        for line in (report.run_dir / "evidence-records.jsonl").read_text().splitlines()
    ]
    row = next(r for r in all_rows if r["plugin_id"] == "riverbank_crossing_v1")
    assert row["status"] == "unavailable"
    assert row["reason_codes"] == ["GUIDE_BASELINE_MISSING"]


def test_riverbank_crossing_enabled_without_an_eligible_guide_is_invalid(tmp_path: Path) -> None:
    site_dir = tmp_path / "sites" / "site"
    make_site(site_dir)
    write_global_adapter_setting(tmp_path / "reference", "riverbank_crossing_v1", True)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"

    write_frame(images_dir / "baseline.jpg", 30)
    write_frame(images_dir / "no-change.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("baseline.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("no-change.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    all_rows = [
        json.loads(line)
        for line in (report.run_dir / "evidence-records.jsonl").read_text().splitlines()
    ]
    row = next(r for r in all_rows if r["plugin_id"] == "riverbank_crossing_v1")
    assert row["status"] == "invalid"
    assert row["reason_codes"] == ["GUIDE_MISSING"]


def test_run_marks_a_too_small_watched_area_as_cannot_judge(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir, reference_region={"x": 0, "y": 0, "width": 100, "height": 5})
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30, bottom_third_value=220)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    assert report.records[0].result == RESULT_CANNOT_JUDGE_WATER_LEVEL
    assert report.cannot_judge_count == 1


def test_run_requires_a_watched_area(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir, reference_region=None)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    write_frame(sequence_dir / "images" / "a.jpg", 30)
    write_frame(sequence_dir / "images" / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    with pytest.raises(ImageSequenceValidationError, match="watched area"):
        run_image_sequence_validation(site_dir, SEQUENCE_ID)


def test_run_rejects_unknown_sequence_id(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)

    with pytest.raises(ImageSequenceValidationError, match="not found"):
        run_image_sequence_validation(site_dir, SEQUENCE_ID)


def test_run_requires_at_least_two_downloaded_images(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    write_frame(sequence_dir / "images" / "only.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("only.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("missing.jpg", "2026-09-01T01:00:00+00:00", "missing"),
        ],
    )

    with pytest.raises(ImageSequenceValidationError, match="At least two"):
        run_image_sequence_validation(site_dir, SEQUENCE_ID)


def test_run_accepts_an_explicit_baseline_override(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID, baseline_filename="b.jpg")

    assert report.baseline_filename == "b.jpg"
    assert [record.filename for record in report.records] == ["a.jpg"]


def test_run_rejects_an_unknown_baseline_override(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    with pytest.raises(ImageSequenceValidationError, match="baseline_filename"):
        run_image_sequence_validation(site_dir, SEQUENCE_ID, baseline_filename="nope.jpg")


def test_list_and_read_run_detail_round_trip(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    runs = list_image_sequence_runs(site_dir, SEQUENCE_ID)
    assert len(runs) == 1
    assert runs[0]["run_id"] == report.run_id

    detail = read_image_sequence_run_detail(site_dir, report.run_id)
    assert detail["summary"]["run_id"] == report.run_id
    assert len(detail["records"]) == 1
    assert "Image Sequence Validation Report" in detail["report"]
    # No gauge-daily-series.json or event-reviews.jsonl exist for this
    # sequence yet: both keys are present but empty, never missing.
    assert detail["gauge_series"] == []
    assert detail["event_reviews"] == {}
    assert len(detail["evidence_records"]) == 2
    evidence_row = next(
        r for r in detail["evidence_records"] if r["plugin_id"] == "pixel_change_region_v1"
    )
    assert evidence_row["timestamp"] == "2026-09-01T01:00:00+00:00"


def test_read_run_detail_includes_frozen_gauge_evidence_and_event_reviews(
    tmp_path: Path,
) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )
    write_gauge_source(sequence_dir, [("2026-09-01T01:07:00+00:00", 3.5, ["P"])])

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)
    detail = read_image_sequence_run_detail(site_dir, report.run_id)
    summary = detail["summary"]
    evidence_key = compute_evidence_key(summary["baseline_filename"], summary["watched_area_used"])
    set_event_review(
        sequence_dir,
        event_key="2026-09-01-2026-09-01-P",
        status="confirmed_real",
        evidence_key=evidence_key,
    )

    detail = read_image_sequence_run_detail(site_dir, report.run_id)

    gauge = detail["gauge_evidence"]
    assert gauge["captured"] is True
    by_name = {image["filename"]: image for image in gauge["images"]}
    assert by_name["a.jpg"]["match_status"] == "no_matching_reading"
    assert by_name["b.jpg"]["match_status"] == "matched"
    assert by_name["b.jpg"]["time_difference_seconds"] == 7 * 60
    assert by_name["b.jpg"]["reading"]["quality_status"] == "provisional"
    assert detail["event_reviews"] == {"2026-09-01-2026-09-01-P": "confirmed_real"}


def write_gauge_source(
    sequence_dir: Path, readings: list[tuple[str, float, list[str]]], status: str = "available"
) -> None:
    (sequence_dir / "gauge-readings.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": status,
                "reason": None,
                "retrieved_at_utc": "2026-09-02T00:00:00+00:00",
                "camera_id": "camera-demo-01",
                "association": {"nwis_site_id": "09095500", "relationship": "same_site"},
                "parameter": {
                    "code": "00065",
                    "label": "gage height",
                    "unit": "ft",
                    "used_fallback_discharge": False,
                },
                "source_url": "https://example.test/iv",
                "start_date": "2026-09-01",
                "end_date": "2026-09-01",
                "rejected_reading_count": 0,
                "readings": [
                    {
                        "datetime_utc": stamp,
                        "value": value,
                        "qualifiers": codes,
                        "quality_status": "provisional",
                    }
                    for stamp, value, codes in readings
                ],
            }
        ),
        encoding="utf-8",
    )


def test_finished_run_gauge_evidence_is_not_changed_by_later_gauge_data(
    tmp_path: Path,
) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )
    write_gauge_source(sequence_dir, [("2026-09-01T01:00:00+00:00", 3.5, ["A"])])
    first = run_image_sequence_validation(site_dir, SEQUENCE_ID)
    before = read_image_sequence_run_detail(site_dir, first.run_id)["gauge_evidence"]

    # A later download corrects the value and the sequence-level files change.
    write_gauge_source(sequence_dir, [("2026-09-01T01:00:00+00:00", 9.9, ["P"])])
    (sequence_dir / "gauge-readings-summary.json").write_text("{}", encoding="utf-8")

    after = read_image_sequence_run_detail(site_dir, first.run_id)["gauge_evidence"]
    second = run_image_sequence_validation(site_dir, SEQUENCE_ID)
    new_run = read_image_sequence_run_detail(site_dir, second.run_id)["gauge_evidence"]

    assert after == before
    first_b = next(i for i in before["images"] if i["filename"] == "b.jpg")
    new_b = next(i for i in new_run["images"] if i["filename"] == "b.jpg")
    assert first_b["reading"]["value"] == 3.5
    assert new_b["reading"]["value"] == 9.9
    assert (first.run_dir / "inputs-used" / "gauge-readings.snapshot.json").is_file()


def test_gauge_snapshot_hash_and_matches_come_from_the_same_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openfloodai.ingestion import usgs_gage_data
    from openfloodai.validation import image_sequence_runner as runner

    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )
    write_gauge_source(sequence_dir, [("2026-09-01T01:00:00+00:00", 4.0, ["A"])])
    real_parse = usgs_gage_data.parse_gauge_source

    def parse_then_download_changes_the_file(raw: bytes):  # type: ignore[no-untyped-def]
        parsed = real_parse(raw)
        # A concurrent download replaces the file right after it was read.
        write_gauge_source(sequence_dir, [("2026-09-01T01:00:00+00:00", 9.0, ["A"])])
        return parsed

    monkeypatch.setattr(runner, "parse_gauge_source", parse_then_download_changes_the_file)

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    evidence = read_image_sequence_run_detail(site_dir, report.run_id)["gauge_evidence"]
    snapshot_path = report.run_dir / "inputs-used" / "gauge-readings.snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    matched = next(i for i in evidence["images"] if i["filename"] == "b.jpg")
    assert matched["reading"]["value"] == 4.0
    assert snapshot["readings"][0]["value"] == 4.0
    assert evidence["source_file_sha256"] == hashlib.sha256(snapshot_path.read_bytes()).hexdigest()


def test_older_run_without_gauge_snapshot_reports_not_captured_and_never_refetches(
    tmp_path: Path,
) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )
    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)
    (report.run_dir / "gauge-evidence.json").unlink()
    # Gauge data that exists NOW must not be used to fill the old run's gap.
    write_gauge_source(sequence_dir, [("2026-09-01T01:00:00+00:00", 3.5, ["A"])])

    gauge = read_image_sequence_run_detail(site_dir, report.run_id)["gauge_evidence"]

    assert gauge["captured"] is False
    assert gauge["status"] == "not_captured"
    assert gauge["images"] == []
    assert "not captured" in gauge["reason"].lower()


def test_run_records_each_unmatched_state_distinctly(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
            manifest_record("c.jpg", "2026-09-01T02:00:00+00:00", "missing"),
        ],
    )

    statuses: dict[str, str] = {}
    for status in ("no_station_association", "service_unavailable", "no_readings_in_range"):
        write_gauge_source(sequence_dir, [], status=status)
        report = run_image_sequence_validation(site_dir, SEQUENCE_ID)
        gauge = read_image_sequence_run_detail(site_dir, report.run_id)["gauge_evidence"]
        statuses[status] = gauge["images"][1]["match_status"]
        assert gauge["images"][1]["reading"] is None
        assert gauge["images"][-1]["match_status"] == "image_not_downloaded"

    assert statuses == {
        "no_station_association": "no_station_association",
        "service_unavailable": "service_unavailable",
        "no_readings_in_range": "no_readings_in_range",
    }


def test_run_gauge_score_is_the_runs_own_score_for_that_exact_image(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "baseline.jpg", 30)
    write_frame(images_dir / "same.jpg", 30)
    write_frame(images_dir / "changed.jpg", 30, bottom_third_value=220)
    write_manifest(
        sequence_dir,
        [
            manifest_record("baseline.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("same.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
            manifest_record("changed.jpg", "2026-09-01T01:05:00+00:00", "downloaded"),
        ],
    )
    write_gauge_source(
        sequence_dir,
        [("2026-09-01T01:02:00+00:00", 3.0, ["A"]), ("2026-09-01T01:04:00+00:00", 9.0, ["P"])],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)
    gauge = read_image_sequence_run_detail(site_dir, report.run_id)["gauge_evidence"]
    by_name = {image["filename"]: image for image in gauge["images"]}
    scores = {record.filename: record.region_change_score for record in report.records}

    # Two images in the same hour keep their own readings and their own scores.
    assert by_name["same.jpg"]["reading"]["value"] == 3.0
    assert by_name["changed.jpg"]["reading"]["value"] == 9.0
    assert by_name["same.jpg"]["change_score"] == scores["same.jpg"]
    assert by_name["changed.jpg"]["change_score"] == scores["changed.jpg"]
    assert by_name["changed.jpg"]["change_score"] != by_name["same.jpg"]["change_score"]
    peak = gauge["peak_events"]["highest"]
    assert peak["event_reading"]["value"] == 9.0
    assert peak["image_filename"] == "changed.jpg"
    assert peak["image_change_score"] == scores["changed.jpg"]


def test_a_review_does_not_carry_over_when_the_watched_area_changes(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir, reference_region=FULL_REGION)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    first_report = run_image_sequence_validation(site_dir, SEQUENCE_ID)
    first_detail = read_image_sequence_run_detail(site_dir, first_report.run_id)
    first_evidence_key = compute_evidence_key(
        first_detail["summary"]["baseline_filename"],
        first_detail["summary"]["watched_area_used"],
    )
    set_event_review(
        sequence_dir,
        event_key="k1",
        status="confirmed_real",
        evidence_key=first_evidence_key,
    )
    assert read_image_sequence_run_detail(site_dir, first_report.run_id)["event_reviews"] == {
        "k1": "confirmed_real"
    }

    # Narrow the watched area and rerun on the same downloaded images. Even
    # though the event_key ("k1") is unchanged, the evidence behind it is
    # not the same comparison a human actually reviewed.
    config_path = site_dir / "configs" / "site.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["reference_region"] = {"x": 0, "y": 0, "width": 40, "height": 40}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    second_report = run_image_sequence_validation(site_dir, SEQUENCE_ID)
    second_detail = read_image_sequence_run_detail(site_dir, second_report.run_id)

    assert second_detail["event_reviews"] == {}


def test_list_image_sequence_runs_ignores_other_sequences(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    for sequence_id in (SEQUENCE_ID, "usgs-other-camera-2026-09-01-2026-09-01-all"):
        sequence_dir = site_dir / "inputs" / "image-sequences" / sequence_id
        images_dir = sequence_dir / "images"
        write_frame(images_dir / "a.jpg", 30)
        write_frame(images_dir / "b.jpg", 30)
        write_manifest(
            sequence_dir,
            [
                manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
                manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
            ],
        )
        run_image_sequence_validation(site_dir, sequence_id)

    runs = list_image_sequence_runs(site_dir, SEQUENCE_ID)
    assert len(runs) == 1
    assert runs[0]["sequence_id"] == SEQUENCE_ID


def test_resolve_image_sequence_run_image_rejects_traversal(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )
    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)
    filename = next((report.run_dir / "review-images").glob("*.png")).name

    resolved = resolve_image_sequence_run_image(site_dir, report.run_id, filename)
    assert resolved.is_file()

    with pytest.raises(ImageSequenceValidationError):
        resolve_image_sequence_run_image(site_dir, "../escape", filename)
    with pytest.raises(ImageSequenceValidationError):
        resolve_image_sequence_run_image(site_dir, report.run_id, "../../secret.png")


def test_run_rejects_a_dark_automatically_selected_baseline(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "dark-first.jpg", 3)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("dark-first.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    with pytest.raises(ImageSequenceValidationError, match="too dark"):
        run_image_sequence_validation(site_dir, SEQUENCE_ID)


def test_run_rejects_an_explicitly_chosen_dark_baseline(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "dark.jpg", 3)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("dark.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    with pytest.raises(ImageSequenceValidationError, match="too dark"):
        run_image_sequence_validation(site_dir, SEQUENCE_ID, baseline_filename="dark.jpg")


def test_inputs_used_preserves_the_complete_riverbank_guide(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir, normal_waterline_guides=[confirmed_guide_record()])
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    snapshot = json.loads(
        (report.run_dir / "inputs-used" / "site-config.snapshot.json").read_text()
    )
    saved_guides = snapshot["normal_waterline_guides"]
    assert len(saved_guides) == 1
    saved_guide = saved_guides[0]
    assert saved_guide["id"] == "left-bank"
    assert saved_guide["points"] == [{"x": 10, "y": 10}, {"x": 20, "y": 20}]
    assert saved_guide["video_id"] == "video-001"
    assert saved_guide["video_time_seconds"] == 4.5
    assert saved_guide["status"] == "confirmed"
    assert saved_guide["confirmed_at"] == "2026-08-01T00:00:00+00:00"
    assert saved_guide["notes"] == "Clear view of the bank."


def test_inputs_used_records_a_sha256_hash_per_processed_image(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    images_dir = sequence_dir / "images"
    write_frame(images_dir / "a.jpg", 30)
    write_frame(images_dir / "b.jpg", 30)
    write_manifest(
        sequence_dir,
        [
            manifest_record("a.jpg", "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record("b.jpg", "2026-09-01T01:00:00+00:00", "downloaded"),
            manifest_record("missing.jpg", "2026-09-01T02:00:00+00:00", "missing"),
        ],
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)

    images_used = json.loads((report.run_dir / "inputs-used" / "images.snapshot.json").read_text())
    hashes_by_filename = {entry["filename"]: entry["sha256"] for entry in images_used}
    assert set(hashes_by_filename) == {"a.jpg", "b.jpg"}

    expected_hash = hashlib.sha256((images_dir / "b.jpg").read_bytes()).hexdigest()
    assert hashes_by_filename["b.jpg"] == expected_hash


def test_classify_comparison_falls_back_to_cannot_judge_for_an_unknown_state() -> None:
    result, reason = _classify_comparison("some_future_state_not_yet_known", brightness_score=0.5)
    assert result == RESULT_CANNOT_JUDGE_WATER_LEVEL
    assert "some_future_state_not_yet_known" in reason


def test_classify_comparison_still_maps_useful_evidence_to_possible_change() -> None:
    result, _ = _classify_comparison("useful_water_level_evidence", brightness_score=0.5)
    assert result == RESULT_POSSIBLE_WATER_LEVEL_CHANGE


def test_workspace_image_review_preserves_pair_and_saved_machine_records(tmp_path: Path) -> None:
    from openfloodai.contracts import read_jsonl_records
    from openfloodai.review.workspace import evidence, media_path, save_group, save_observation

    site = tmp_path / "site"
    make_site(site)
    sequence = site / "inputs" / "image-sequences" / SEQUENCE_ID
    baseline = "camera___2026-09-01T00-00-00Z.jpg"
    selected = "camera___2026-09-01T01-00-00Z.jpg"
    for filename in (baseline, selected):
        write_frame(sequence / "images" / filename, 100)
    write_manifest(
        sequence,
        [
            manifest_record(baseline, "2026-09-01T00:00:00+00:00", "downloaded"),
            manifest_record(selected, "2026-09-01T01:00:00+00:00", "downloaded"),
        ],
    )
    report = run_image_sequence_validation(site, SEQUENCE_ID)
    records = report.run_dir / "image-sequence-records.jsonl"
    before = records.read_bytes()
    payload = evidence(site, "image", report.run_id, SEQUENCE_ID)
    point = payload["points"][0]
    assert point["comparison"]["result"] == "cannot_compare"
    request = {
        "kind": "image",
        "run_id": report.run_id,
        "media_id": SEQUENCE_ID,
        "sample_key": point["key"],
        "human_label": "no_water_level_change",
    }
    save_observation(site, request)
    updated = evidence(site, "image", report.run_id, SEQUENCE_ID)
    assert updated["points"][0]["comparison"]["result"] == "agree"
    saved = read_jsonl_records(report.run_dir / "human-review" / "observations.jsonl")[0]
    assert saved["filename"] == selected
    assert saved["baseline_filename"] == baseline
    assert isinstance(saved["label"], dict)
    assert "time_window_seconds" not in saved["label"]
    assert records.read_bytes() == before
    save_group(site, {**request, "group": "practice"})
    save_group(site, {**request, "group": "practice"})
    assert len(evidence(site, "image", report.run_id, SEQUENCE_ID)["groups"]) == 1
    with pytest.raises(ValueError):
        media_path(site, "image", "../escape", SEQUENCE_ID, selected)
    (sequence / "images" / selected).write_bytes(b"replacement")
    with pytest.raises(ValueError, match="changed since analysis"):
        save_observation(site, request)


def write_water_level_selection(sequence_dir: Path, group_by_file: dict[str, str]) -> None:
    payload = {
        "schema_version": 1,
        "policy_version": "water-level-sampling-v1",
        "selected_at_utc": "2026-10-01T00:00:00+00:00",
        "note": "Relative to this station and date range only.",
        "request": {"groups": ["high"], "images_per_group": 2},
        "association": {"nwis_site_id": "09999999", "source": "https://example.test/registry"},
        "gauge": {"parameter_code": "00065", "unit": "ft"},
        "samples": [
            {
                "filename": name,
                "group": group,
                "motivating_reading": {"value": 5.0, "unit": "ft", "quality_status": "provisional"},
                "image_reading": {"value": 4.9, "unit": "ft"},
                "gap_seconds": -300,
                "image_reading_gap_seconds": -120,
                "readings_differ": True,
            }
            for name, group in group_by_file.items()
        ],
    }
    (sequence_dir / "water-level-selection.json").write_text(json.dumps(payload), encoding="utf-8")


def make_water_level_sequence(tmp_path: Path) -> tuple[Path, Path]:
    site_dir = tmp_path / "site"
    make_site(site_dir)
    sequence_dir = site_dir / "inputs" / "image-sequences" / SEQUENCE_ID
    names = ["a.jpg", "b.jpg", "c.jpg"]
    for index, name in enumerate(names):
        write_frame(sequence_dir / "images" / name, 30 + index * 10)
    write_manifest(
        sequence_dir,
        [
            manifest_record(name, f"2026-09-01T0{index}:00:00+00:00", "downloaded")
            for index, name in enumerate(names)
        ],
    )
    write_water_level_selection(sequence_dir, {"a.jpg": "low", "b.jpg": "high", "c.jpg": "high"})
    return site_dir, sequence_dir


def test_a_water_level_sample_set_needs_an_explicit_baseline(tmp_path: Path) -> None:
    site_dir, _ = make_water_level_sequence(tmp_path)

    with pytest.raises(ImageSequenceValidationError, match="Choose a baseline"):
        run_image_sequence_validation(site_dir, SEQUENCE_ID)

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID, baseline_filename="a.jpg")
    assert report.baseline_filename == "a.jpg"


def test_a_run_freezes_the_water_level_selection_and_shows_groups_per_image(tmp_path: Path) -> None:
    site_dir, sequence_dir = make_water_level_sequence(tmp_path)
    report = run_image_sequence_validation(site_dir, SEQUENCE_ID, baseline_filename="a.jpg")

    detail = read_image_sequence_run_detail(site_dir, report.run_id)
    selection = detail["water_level_selection"]

    assert selection["policy_version"] == "water-level-sampling-v1"
    assert selection["samples"]["b.jpg"]["group"] == "high"
    assert selection["samples"]["b.jpg"]["readings_differ"] is True
    assert selection["samples"]["b.jpg"]["motivating_reading"]["quality_status"] == "provisional"
    assert (report.run_dir / "inputs-used" / "sampling" / "water-level-selection.json").is_file()

    # A later change to the sequence's own record never alters a finished run.
    write_water_level_selection(sequence_dir, {"a.jpg": "middle", "b.jpg": "low", "c.jpg": "low"})
    again = read_image_sequence_run_detail(site_dir, report.run_id)["water_level_selection"]
    assert again == selection


def test_regular_sequences_have_no_water_level_selection(tmp_path: Path) -> None:
    site_dir, sequence_dir = make_water_level_sequence(tmp_path)
    (sequence_dir / "water-level-selection.json").unlink()

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)  # default baseline, as before

    detail = read_image_sequence_run_detail(site_dir, report.run_id)
    assert detail["water_level_selection"] is None


def test_run_detail_returns_the_setup_the_run_used_for_overlays(tmp_path: Path) -> None:
    site_dir, sequence_dir = make_water_level_sequence(tmp_path)
    report = run_image_sequence_validation(site_dir, SEQUENCE_ID, baseline_filename="a.jpg")
    config_path = site_dir / "configs" / "site.json"
    config = json.loads(config_path.read_text())

    detail = read_image_sequence_run_detail(site_dir, report.run_id)
    used = detail["setup_used"]
    assert used["reference_region"] == config["reference_region"]

    # Editing the site's watched area afterward does not change the finished run's setup.
    config["reference_region"] = {"x": 0, "y": 0, "width": 10, "height": 10}
    config_path.write_text(json.dumps(config))
    assert read_image_sequence_run_detail(site_dir, report.run_id)["setup_used"] == used

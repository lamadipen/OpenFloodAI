"""Tests for running local validation against a saved USGS image sequence (issue #182)."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from openfloodai.validation.image_sequence_runner import (
    RESULT_CAMERA_OR_IMAGE_PROBLEM,
    RESULT_CANNOT_JUDGE_WATER_LEVEL,
    RESULT_NO_WATER_LEVEL_CHANGE,
    RESULT_POSSIBLE_WATER_LEVEL_CHANGE,
    ImageSequenceValidationError,
    list_image_sequence_runs,
    read_image_sequence_run_detail,
    resolve_image_sequence_run_image,
    run_image_sequence_validation,
)

SEQUENCE_ID = "usgs-camera-demo-2026-09-01-2026-09-01-all"
FULL_REGION: dict[str, object] = {"x": 0, "y": 0, "width": 100, "height": 100}


def make_site(site_dir: Path, *, reference_region: dict[str, object] | None = FULL_REGION) -> None:
    (site_dir / "configs").mkdir(parents=True)
    config: dict[str, object] = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo Site",
        "input_type": "local_video",
    }
    if reference_region is not None:
        config["reference_region"] = reference_region
    (site_dir / "configs" / "site.json").write_text(json.dumps(config), encoding="utf-8")


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

    report_text = (run_dir / "image-sequence-report.md").read_text()
    assert "Safety Boundary" in report_text
    assert "possible-change.jpg" in report_text

    records_lines = (run_dir / "image-sequence-records.jsonl").read_text().splitlines()
    assert len(records_lines) == 5


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

"""Tests for running local validation against a saved USGS image sequence (issue #182)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

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
    # No gauge-daily-series.json or event-reviews.jsonl exist for this
    # sequence yet: both keys are present but empty, never missing.
    assert detail["gauge_series"] == []
    assert detail["event_reviews"] == {}


def test_read_run_detail_includes_gauge_series_and_event_reviews_when_present(
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
    (sequence_dir / "gauge-daily-series.json").write_text(
        json.dumps([{"date": "2026-09-01", "gauge_value": 3.5}]), encoding="utf-8"
    )

    report = run_image_sequence_validation(site_dir, SEQUENCE_ID)
    detail = read_image_sequence_run_detail(site_dir, report.run_id)
    summary = detail["summary"]
    evidence_key = compute_evidence_key(
        summary["baseline_filename"], summary["watched_area_used"]
    )
    set_event_review(
        sequence_dir,
        event_key="2026-09-01-2026-09-01-P",
        status="confirmed_real",
        evidence_key=evidence_key,
    )

    detail = read_image_sequence_run_detail(site_dir, report.run_id)

    assert detail["gauge_series"] == [{"date": "2026-09-01", "gauge_value": 3.5}]
    assert detail["event_reviews"] == {"2026-09-01-2026-09-01-P": "confirmed_real"}


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

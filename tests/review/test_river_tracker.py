from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.review.dataset_groups import assign_dataset_group
from openfloodai.review.river_tracker import build_river_tracker
from openfloodai.validation.site_setup import setup_validation_site

CAMERA_A = "TEST_CAMERA_A"
CAMERA_B = "TEST_CAMERA_B"


@pytest.fixture
def reference_dir(tmp_path: Path) -> Path:
    reference_dir = tmp_path / "reference"
    rivers_dir = reference_dir / "rivers"
    rivers_dir.mkdir(parents=True)

    def camera(camera_id: str, folder_name: str) -> dict[str, object]:
        return {
            "river_id": "test-river",
            "camera_id": camera_id,
            "nwis_id": "09999999",
            "state": "CO",
            "latitude": 40.0,
            "longitude": -105.0,
            "display_name": camera_id,
            "folder_name": folder_name,
            "gage_relationship": "same_site",
            "timezone": "America/Denver",
        }

    payload = {
        "river_id": "test-river",
        "display_name": "Test River",
        "cameras": [camera(CAMERA_A, "test-river-a"), camera(CAMERA_B, "test-river-b")],
    }
    (rivers_dir / "test-river.json").write_text(json.dumps(payload), encoding="utf-8")
    return reference_dir


def test_camera_with_no_site_reports_not_created(reference_dir: Path, tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    registry, rows = build_river_tracker(
        "test-river", reference_dir=reference_dir, sites_base_dir=sites_dir
    )

    assert registry.river_id == "test-river"
    by_id = {row.camera_id: row for row in rows}
    assert by_id[CAMERA_A].camera_availability == "not_created"
    assert by_id[CAMERA_A].dataset_group == "development_candidate"
    assert by_id[CAMERA_A].known_problems == []


def test_site_with_sequence_and_gage_data_reports_progress(
    reference_dir: Path, tmp_path: Path
) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    setup_validation_site(
        sites_base_dir=sites_dir,
        folder_name="test-river-a",
        site_id="test-river-a_sid",
        camera_id=CAMERA_A,
        site_name="Test Camera A",
    )
    site_dir = sites_dir / "test-river-a"
    sequence_dir = (
        site_dir
        / "inputs"
        / "image-sequences"
        / f"usgs-{CAMERA_A}-2026-06-18-2026-09-16-one_daylight_image_per_day"
    )
    sequence_dir.mkdir(parents=True)
    (sequence_dir / "download-summary.json").write_text(
        json.dumps(
            {
                "sequence_id": sequence_dir.name,
                "camera_url": f"https://apps.usgs.gov/hivis/camera/{CAMERA_A}",
                "requested_start_date": "2026-06-18",
                "requested_end_date": "2026-09-16",
                "downloaded_count": 91,
                "missing_count": 0,
                "failed_count": 0,
            }
        ),
        encoding="utf-8",
    )
    (sequence_dir / "gauge-readings-summary.json").write_text(
        json.dumps({"available": True, "parameter_label": "gage height"}), encoding="utf-8"
    )

    registry, rows = build_river_tracker(
        "test-river", reference_dir=reference_dir, sites_base_dir=sites_dir
    )
    row = next(r for r in rows if r.camera_id == CAMERA_A)

    assert row.camera_availability == "downloaded"
    assert row.requested_date_range == "2026-06-18 to 2026-09-16"
    assert row.daylight_images_downloaded == 91
    assert row.missing_days == 0
    assert row.gage_data_status == "available (gage height)"
    assert row.watched_area_status == "not_drawn"
    assert row.human_review_progress == "images_downloaded"
    # An image-sequence-only site never has manifest.jsonl; that must not
    # be reported as a known problem.
    assert row.known_problems == []


def test_human_review_progress_counts_image_sequence_runs_not_video_reports(
    reference_dir: Path, tmp_path: Path
) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    setup_validation_site(
        sites_base_dir=sites_dir,
        folder_name="test-river-a",
        site_id="test-river-a_sid",
        camera_id=CAMERA_A,
        site_name="Test Camera A",
    )
    site_dir = sites_dir / "test-river-a"
    config_path = site_dir / "configs" / "test-river-a.json"
    config = json.loads(config_path.read_text())
    config["reference_region"] = {"x": 10, "y": 10, "width": 50, "height": 50}
    config["normal_waterline_guides"] = [
        {
            "id": "g1",
            "label": "left bank",
            "points": [{"x": 15.0, "y": 15.0}, {"x": 20.0, "y": 20.0}],
            "video_id": "",
            "video_time_seconds": 0.0,
            "site_id": "test-river-a_sid",
            "camera_id": CAMERA_A,
            "status": "confirmed",
            "normal_condition": True,
            "notes": "",
            "confirmed_at": "2026-09-17T00:00:00+00:00",
            "invalidated_at": None,
            "invalidation_reason": None,
            "image_sequence_id": "some-sequence",
            "image_filename": "some.jpg",
        }
    ]
    config_path.write_text(json.dumps(config), encoding="utf-8")

    sequence_id = f"usgs-{CAMERA_A}-2026-06-18-2026-09-16-one_daylight_image_per_day"
    sequence_dir = site_dir / "inputs" / "image-sequences" / sequence_id
    sequence_dir.mkdir(parents=True)
    (sequence_dir / "download-summary.json").write_text(
        json.dumps(
            {
                "sequence_id": sequence_id,
                "camera_url": f"https://apps.usgs.gov/hivis/camera/{CAMERA_A}",
                "requested_start_date": "2026-06-18",
                "requested_end_date": "2026-09-16",
                "downloaded_count": 91,
                "missing_count": 0,
                "failed_count": 0,
            }
        ),
        encoding="utf-8",
    )
    # A stray VIDEO validation report (a different flow entirely) must not
    # make an image-only site's progress read as "validated".
    video_outputs = site_dir / "outputs" / "runs" / "video-run-1"
    video_outputs.mkdir(parents=True)
    (video_outputs / "validation-report.md").write_text("# Video report\n", encoding="utf-8")

    _, rows = build_river_tracker(
        "test-river", reference_dir=reference_dir, sites_base_dir=sites_dir
    )
    row = next(r for r in rows if r.camera_id == CAMERA_A)
    assert row.baseline_selected is True
    assert row.validation_run_count == 0
    assert row.human_review_progress == "baseline_ready"

    # Now save a real IMAGE-sequence run for this sequence — only this
    # should flip progress to "validated".
    run_dir = site_dir / "outputs" / "image-sequence-runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "run-summary.json").write_text(
        json.dumps({"sequence_id": sequence_id, "run_id": "run-1", "created_at": "2026-09-17"}),
        encoding="utf-8",
    )

    _, rows = build_river_tracker(
        "test-river", reference_dir=reference_dir, sites_base_dir=sites_dir
    )
    row = next(r for r in rows if r.camera_id == CAMERA_A)
    assert row.validation_run_count == 1
    assert row.human_review_progress == "validated"


def test_gage_unavailable_status_reports_reason(reference_dir: Path, tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    setup_validation_site(
        sites_base_dir=sites_dir,
        folder_name="test-river-a",
        site_id="test-river-a_sid",
        camera_id=CAMERA_A,
        site_name="Test Camera A",
    )
    site_dir = sites_dir / "test-river-a"
    sequence_dir = (
        site_dir / "inputs" / "image-sequences" / f"usgs-{CAMERA_A}-2026-06-18-2026-09-16-all"
    )
    sequence_dir.mkdir(parents=True)
    (sequence_dir / "download-summary.json").write_text(
        json.dumps(
            {
                "sequence_id": sequence_dir.name,
                "camera_url": f"https://apps.usgs.gov/hivis/camera/{CAMERA_A}",
                "requested_start_date": "2026-06-18",
                "requested_end_date": "2026-09-16",
                "downloaded_count": 5,
                "missing_count": 0,
                "failed_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (sequence_dir / "gauge-readings-summary.json").write_text(
        json.dumps({"available": False, "unavailable_reason": "No data was available."}),
        encoding="utf-8",
    )

    _, rows = build_river_tracker(
        "test-river", reference_dir=reference_dir, sites_base_dir=sites_dir
    )
    row = next(r for r in rows if r.camera_id == CAMERA_A)

    assert row.gage_data_status == "unavailable: No data was available."
    assert row.known_problems == ["1 image(s) failed to download."]


def test_watched_area_drawn_and_riverbank_guide_and_baseline(
    reference_dir: Path, tmp_path: Path
) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    setup_validation_site(
        sites_base_dir=sites_dir,
        folder_name="test-river-a",
        site_id="test-river-a_sid",
        camera_id=CAMERA_A,
        site_name="Test Camera A",
    )
    config_path = sites_dir / "test-river-a" / "configs" / "test-river-a.json"
    config = json.loads(config_path.read_text())
    config["reference_region"] = {"x": 10, "y": 10, "width": 50, "height": 50}
    config["normal_waterline_guides"] = [
        {
            "id": "g1",
            "label": "left bank",
            "points": [{"x": 15.0, "y": 15.0}, {"x": 20.0, "y": 20.0}],
            "video_id": "",
            "video_time_seconds": 0.0,
            "site_id": "test-river-a_sid",
            "camera_id": CAMERA_A,
            "status": "confirmed",
            "normal_condition": True,
            "notes": "",
            "confirmed_at": "2026-09-17T00:00:00+00:00",
            "invalidated_at": None,
            "invalidation_reason": None,
            "image_sequence_id": "some-sequence",
            "image_filename": "some.jpg",
        }
    ]
    config_path.write_text(json.dumps(config), encoding="utf-8")

    _, rows = build_river_tracker(
        "test-river", reference_dir=reference_dir, sites_base_dir=sites_dir
    )
    row = next(r for r in rows if r.camera_id == CAMERA_A)

    assert row.watched_area_status == "drawn"
    assert row.riverbank_guide_status == "1 guide(s) drawn"
    assert row.baseline_selected is True


def test_dataset_group_assignments_are_summarized(reference_dir: Path, tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    setup_validation_site(
        sites_base_dir=sites_dir,
        folder_name="test-river-a",
        site_id="test-river-a_sid",
        camera_id=CAMERA_A,
        site_name="Test Camera A",
    )
    assign_dataset_group(
        sites_dir / "test-river-a",
        group="practice",
        start_date="2026-06-18",
        end_date="2026-07-31",
    )

    _, rows = build_river_tracker(
        "test-river", reference_dir=reference_dir, sites_base_dir=sites_dir
    )
    row = next(r for r in rows if r.camera_id == CAMERA_A)

    assert row.dataset_group == "practice (2026-06-18 to 2026-07-31)"

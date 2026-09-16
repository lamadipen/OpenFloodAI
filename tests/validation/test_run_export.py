from __future__ import annotations

import json
import shutil
from pathlib import Path

import cv2
import numpy as np

from openfloodai.validation import (
    build_export_all,
    build_run_export,
    discover_validation_site_statuses,
    run_site_validation,
)


def create_tiny_video(path: Path, *, frame_values: tuple[int, ...]) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 2.0, (8, 8))
    assert writer.isOpened(), "test video writer should open"

    try:
        for value in frame_values:
            frame = np.full((8, 8, 3), value, dtype=np.uint8)
            for _ in range(60 // len(frame_values)):
                writer.write(frame)
    finally:
        writer.release()


def write_site_config(path: Path, *, site_id: str = "site-demo-01") -> None:
    config = {
        "site_id": site_id,
        "camera_id": "camera-demo-01",
        "site_name": "Demo Site",
        "input_type": "local_video",
        "reference_region": {"x": 0, "y": 0, "width": 10, "height": 10},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))


def make_site_with_completed_run(
    sites_dir: Path, folder_name: str = "example-site"
) -> tuple[Path, str]:
    site_dir = sites_dir / folder_name
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    write_site_config(site_dir / "configs" / "site-config.json")
    (site_dir / "labels" / "labels.jsonl").write_text(
        json.dumps(
            {
                "video_id": "rising-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_level_rising",
            }
        )
        + "\n"
    )
    create_tiny_video(
        site_dir / "inputs" / "videos" / "rising-001.avi",
        frame_values=(80, 80),
    )
    report = run_site_validation(site_dir)
    return site_dir, report.run_id


def test_run_export_creates_portable_copy_of_the_run_folder(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir, run_id = make_site_with_completed_run(sites_dir)
    destination = tmp_path / "downloads"

    result = build_run_export(site_dir, run_id, destination)

    assert result.created, result.message
    assert result.export_dir == destination / run_id
    export_dir = result.export_dir
    assert (export_dir / "validation-report.md").is_file()
    assert (export_dir / "scorecard.json").is_file()
    assert (export_dir / "run-metadata.json").is_file()
    assert (export_dir / "records").is_dir()
    assert (export_dir / "review-images").is_dir()
    assert (export_dir / "inputs-used" / "receipt.json").is_file()
    assert (export_dir / "README.md").is_file()

    original_run_dir = site_dir / "outputs" / "runs" / run_id
    original_records = {p.name for p in (original_run_dir / "records").glob("*.jsonl")}
    exported_records = {p.name for p in (export_dir / "records").glob("*.jsonl")}
    assert original_records == exported_records


def test_run_export_metadata_paths_are_portable(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir, run_id = make_site_with_completed_run(sites_dir)
    destination = tmp_path / "downloads"

    result = build_run_export(site_dir, run_id, destination)

    metadata = json.loads((result.export_dir / "run-metadata.json").read_text(encoding="utf-8"))
    assert metadata["report_path"] == "validation-report.md"
    assert metadata["scorecard_path"] == "scorecard.json"
    assert metadata["records_path"] == "records"
    assert metadata["review_images_path"] == "review-images"
    assert metadata["inputs_used_path"] == "inputs-used"


def test_run_export_default_excludes_raw_video(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir, run_id = make_site_with_completed_run(sites_dir)

    result = build_run_export(site_dir, run_id, tmp_path / "downloads")

    assert result.included_raw_video is False
    assert not (result.export_dir / "videos").exists()


def test_run_export_raw_video_included_only_when_requested_and_unchanged(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir, run_id = make_site_with_completed_run(sites_dir)

    result = build_run_export(site_dir, run_id, tmp_path / "downloads", include_raw_video=True)

    assert result.included_raw_video is True
    exported_video = result.export_dir / "videos" / "rising-001.avi"
    assert exported_video.is_file()
    original = (site_dir / "inputs" / "videos" / "rising-001.avi").read_bytes()
    assert exported_video.read_bytes() == original


def test_run_export_excludes_and_notes_video_changed_since_run(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir, run_id = make_site_with_completed_run(sites_dir)

    create_tiny_video(site_dir / "inputs" / "videos" / "rising-001.avi", frame_values=(5, 5))

    result = build_run_export(site_dir, run_id, tmp_path / "downloads", include_raw_video=True)

    assert result.included_raw_video is False
    assert result.excluded_video_filenames == ["rising-001.avi"]
    readme = (result.export_dir / "README.md").read_text(encoding="utf-8")
    assert "rising-001.avi" in readme
    assert "no longer matches" in readme.lower()


def test_run_export_refuses_missing_run(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir, _run_id = make_site_with_completed_run(sites_dir)

    result = build_run_export(site_dir, "20200101T000000Z-deadbeef", tmp_path / "downloads")

    assert not result.created
    assert "does not exist" in result.message.lower()


def test_run_export_refuses_invalid_run_id_path_traversal(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir, _run_id = make_site_with_completed_run(sites_dir)

    result = build_run_export(site_dir, "../../etc", tmp_path / "downloads")

    assert not result.created
    assert "invalid run_id" in result.message.lower()


def test_exported_run_folder_is_picked_up_after_copy_into_another_site(tmp_path: Path) -> None:
    """The whole point of a portable export: drop it into another site and it just shows up."""

    source_sites_dir = tmp_path / "source-sites"
    site_dir, run_id = make_site_with_completed_run(source_sites_dir, folder_name="source-site")
    export_result = build_run_export(site_dir, run_id, tmp_path / "downloads")

    other_sites_dir = tmp_path / "other-sites"
    other_site_dir = other_sites_dir / "teammate-site"
    (other_site_dir / "outputs" / "runs").mkdir(parents=True)
    (other_site_dir / "configs").mkdir(parents=True)
    write_site_config(other_site_dir / "configs" / "site-config.json")

    shutil.copytree(export_result.export_dir, other_site_dir / "outputs" / "runs" / run_id)

    statuses = discover_validation_site_statuses(other_sites_dir)
    teammate_status = next(status for status in statuses if status.site_name == "teammate-site")
    assert teammate_status.report_history
    entry = teammate_status.report_history[0]
    assert entry["run_id"] == run_id
    assert entry["counts"] is not None
    assert str(other_site_dir) in entry["path"]
    assert str(other_site_dir) in (entry["inputs_used_path"] or "")


def test_export_all_bundles_every_site_with_config_labels_manifest_and_runs(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    make_site_with_completed_run(sites_dir, folder_name="site-a")
    make_site_with_completed_run(sites_dir, folder_name="site-b")
    destination = tmp_path / "bundle"

    result = build_export_all(sites_dir, destination)

    assert result.created, result.message
    assert sorted(result.exported_site_names) == ["site-a", "site-b"]
    for site_name in ("site-a", "site-b"):
        site_export = destination / site_name
        assert (site_export / "configs" / "site-config.json").is_file()
        assert (site_export / "labels" / "labels.jsonl").is_file()
        run_dirs = list((site_export / "outputs" / "runs").iterdir())
        assert len(run_dirs) == 1
        assert (run_dirs[0] / "validation-report.md").is_file()
        assert (run_dirs[0] / "run-metadata.json").is_file()
    assert (destination / "README.md").is_file()


def test_export_all_excludes_raw_video_by_default(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    make_site_with_completed_run(sites_dir, folder_name="site-a")

    result = build_export_all(sites_dir, tmp_path / "bundle")

    assert result.included_raw_video is False
    assert not (result.export_dir / "site-a" / "inputs" / "videos").exists()


def test_export_all_includes_raw_video_when_requested(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    make_site_with_completed_run(sites_dir, folder_name="site-a")

    result = build_export_all(sites_dir, tmp_path / "bundle", include_raw_video=True)

    assert result.included_raw_video is True
    videos = list((result.export_dir / "site-a" / "inputs" / "videos").glob("*.avi"))
    assert len(videos) == 1


def test_export_all_refuses_when_no_sites_exist(tmp_path: Path) -> None:
    sites_dir = tmp_path / "empty-sites"
    sites_dir.mkdir()

    result = build_export_all(sites_dir, tmp_path / "bundle")

    assert not result.created
    assert "no sites" in result.message.lower()

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from openfloodai.validation import export_run, run_site_validation


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


def write_site_config(path: Path) -> None:
    config = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo Site",
        "input_type": "local_video",
        "reference_region": {"x": 0, "y": 0, "width": 10, "height": 10},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))


def make_site_with_completed_run(tmp_path: Path) -> tuple[Path, str]:
    site_dir = tmp_path / "example-site"
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    write_site_config(site_dir / "configs" / "site-config.json")
    (site_dir / "labels" / "labels.jsonl").write_text(
        json.dumps(
            {
                "video_id": "rising-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_rising",
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


def test_export_creates_package_for_selected_run(tmp_path: Path) -> None:
    site_dir, run_id = make_site_with_completed_run(tmp_path)

    result = export_run(site_dir, run_id)

    assert result.created, result.message
    assert result.export_dir.is_dir()
    assert result.export_dir.parent == site_dir / "exports"


def test_default_export_includes_key_review_files(tmp_path: Path) -> None:
    site_dir, run_id = make_site_with_completed_run(tmp_path)

    result = export_run(site_dir, run_id)

    export_dir = result.export_dir
    assert (export_dir / "report.md").is_file()
    assert (export_dir / "scorecard.json").is_file()
    assert (export_dir / "records.jsonl").is_file()
    assert (export_dir / "run-metadata.json").is_file()
    assert (export_dir / "site-summary.json").is_file()
    assert (export_dir / "README.md").is_file()
    assert (export_dir / "review-images").is_dir()
    assert (export_dir / "inputs-used" / "receipt.json").is_file()
    assert (export_dir / "inputs-used" / "labels.snapshot.jsonl").is_file()

    records_text = (export_dir / "records.jsonl").read_text(encoding="utf-8")
    assert records_text.strip() != ""
    for line in records_text.splitlines():
        json.loads(line)

    summary = json.loads((export_dir / "site-summary.json").read_text(encoding="utf-8"))
    assert summary["site_id"] == "site-demo-01"
    assert summary["run_id"] == run_id


def test_default_export_excludes_raw_video(tmp_path: Path) -> None:
    site_dir, run_id = make_site_with_completed_run(tmp_path)

    result = export_run(site_dir, run_id)

    assert result.included_raw_video is False
    assert not (result.export_dir / "videos").exists()
    readme = (result.export_dir / "README.md").read_text(encoding="utf-8")
    assert "not requested" in readme.lower() or "not included" in readme.lower()


def test_raw_video_included_only_when_requested_and_unchanged(tmp_path: Path) -> None:
    site_dir, run_id = make_site_with_completed_run(tmp_path)

    result = export_run(site_dir, run_id, include_raw_video=True)

    assert result.included_raw_video is True
    exported_video = result.export_dir / "videos" / "rising-001.avi"
    assert exported_video.is_file()
    original = (site_dir / "inputs" / "videos" / "rising-001.avi").read_bytes()
    assert exported_video.read_bytes() == original


def test_raw_video_excluded_and_noted_when_changed_since_run(tmp_path: Path) -> None:
    site_dir, run_id = make_site_with_completed_run(tmp_path)

    create_tiny_video(
        site_dir / "inputs" / "videos" / "rising-001.avi",
        frame_values=(5, 5),
    )

    result = export_run(site_dir, run_id, include_raw_video=True)

    assert result.included_raw_video is False
    assert result.excluded_video_filenames == ["rising-001.avi"]
    assert not (result.export_dir / "videos").exists()
    readme = (result.export_dir / "README.md").read_text(encoding="utf-8")
    assert "rising-001.avi" in readme
    assert "no longer matches" in readme.lower()


def test_export_uses_saved_snapshot_not_live_site_files(tmp_path: Path) -> None:
    site_dir, run_id = make_site_with_completed_run(tmp_path)
    run_dir = site_dir / "outputs" / "runs" / run_id

    config_path = site_dir / "configs" / "site-config.json"
    config = json.loads(config_path.read_text())
    config["camera_id"] = "camera-changed-after-run"
    config_path.write_text(json.dumps(config))
    (site_dir / "labels" / "labels.jsonl").write_text(
        json.dumps(
            {
                "video_id": "rising-001",
                "time_window_seconds": [0, 30],
                "human_label": "water_falling",
            }
        )
        + "\n"
    )

    result = export_run(site_dir, run_id)

    summary = json.loads((result.export_dir / "site-summary.json").read_text(encoding="utf-8"))
    assert summary["camera_id"] == "camera-demo-01"
    labels_snapshot = (result.export_dir / "inputs-used" / "labels.snapshot.jsonl").read_text(
        encoding="utf-8"
    )
    assert "water_rising" in labels_snapshot
    assert "water_falling" not in labels_snapshot
    assert run_dir.exists()


def test_export_refuses_missing_run(tmp_path: Path) -> None:
    site_dir, _run_id = make_site_with_completed_run(tmp_path)

    result = export_run(site_dir, "20200101T000000Z-deadbeef")

    assert not result.created
    assert "does not exist" in result.message.lower()


def test_export_refuses_invalid_run_id_path_traversal(tmp_path: Path) -> None:
    site_dir, _run_id = make_site_with_completed_run(tmp_path)

    result = export_run(site_dir, "../../etc")

    assert not result.created
    assert "invalid run_id" in result.message.lower()


def test_export_path_cannot_escape_exports_directory(tmp_path: Path) -> None:
    site_dir, run_id = make_site_with_completed_run(tmp_path)

    result = export_run(site_dir, run_id)

    assert result.created
    assert result.export_dir.resolve().is_relative_to((site_dir / "exports").resolve())


def test_export_as_zip_produces_archive_without_loose_folder(tmp_path: Path) -> None:
    site_dir, run_id = make_site_with_completed_run(tmp_path)

    result = export_run(site_dir, run_id, as_zip=True)

    assert result.created
    assert result.zip_path is not None
    assert result.zip_path.is_file()
    assert result.zip_path.suffix == ".zip"

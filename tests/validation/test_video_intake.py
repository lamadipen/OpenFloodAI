"""Tests for local validation video intake."""

from __future__ import annotations

from pathlib import Path

import pytest

from openfloodai.review import load_manifest_records
from openfloodai.validation import intake_validation_video
from openfloodai.validation.site_setup import setup_validation_site


def _make_site(tmp_path: Path, folder_name: str = "test-site") -> Path:
    result = setup_validation_site(
        sites_base_dir=tmp_path,
        folder_name=folder_name,
        site_id="site-test",
        camera_id="camera-test",
        site_name="Test Site",
        public_location="Test Location",
    )
    assert result.created
    return result.site_dir


def _make_video(path: Path) -> Path:
    path.write_bytes(b"not-real-video")
    return path


def test_intake_validation_video_copies_file_and_creates_manifest(tmp_path: Path) -> None:
    site_dir = _make_site(tmp_path)
    source = _make_video(tmp_path / "rising-001.mp4")

    result = intake_validation_video(
        site_dir=site_dir,
        video_path=source,
        video_id="rising-001",
        purpose="possible_rising_water",
        split="practice",
        notes="Tiny safe test video. Not real footage.",
    )

    dest = site_dir / "inputs" / "videos" / "rising-001.mp4"
    assert result.created
    assert dest.exists()
    assert dest.read_bytes() == b"not-real-video"
    assert result.manifest_path == site_dir / "manifest.jsonl"

    records = load_manifest_records(result.manifest_path)
    assert len(records) == 1
    assert records[0]["video_id"] == "rising-001"
    assert records[0]["filename"] == "rising-001.mp4"
    assert records[0]["purpose"] == "possible_rising_water"
    assert records[0]["split"] == "practice"
    assert records[0]["approved_for_repo"] is False
    assert records[0]["has_human_label"] is False
    assert records[0]["notes"] == "Tiny safe test video. Not real footage."


def test_intake_validation_video_defaults_approved_for_repo_to_false(tmp_path: Path) -> None:
    site_dir = _make_site(tmp_path)
    source = _make_video(tmp_path / "demo-001.mp4")

    result = intake_validation_video(
        site_dir=site_dir,
        video_path=source,
        video_id="demo-001",
        purpose="practice_normal_water",
        split="practice",
        notes="Sharing stays off unless explicitly approved.",
    )

    assert result.created
    record = load_manifest_records(result.manifest_path)[0]
    assert record["approved_for_repo"] is False


def test_intake_validation_video_rejects_duplicate_video_id_by_default(tmp_path: Path) -> None:
    site_dir = _make_site(tmp_path)
    first = _make_video(tmp_path / "first.mp4")
    second = _make_video(tmp_path / "second.mp4")

    first_result = intake_validation_video(
        site_dir=site_dir,
        video_path=first,
        video_id="rising-001",
        purpose="possible_rising_water",
        split="practice",
        notes="First copy.",
    )
    assert first_result.created

    result = intake_validation_video(
        site_dir=site_dir,
        video_path=second,
        video_id="rising-001",
        purpose="other_purpose",
        split="practice",
        notes="Duplicate id should fail.",
    )

    assert not result.created
    assert "video_id already exists" in result.message
    dest = site_dir / "inputs" / "videos" / "rising-001.mp4"
    assert dest.read_bytes() == b"not-real-video"
    records = load_manifest_records(site_dir / "manifest.jsonl")
    assert len(records) == 1
    assert records[0]["purpose"] == "possible_rising_water"


def test_intake_validation_video_rejects_duplicate_filename_by_default(tmp_path: Path) -> None:
    site_dir = _make_site(tmp_path)
    videos_dir = site_dir / "inputs" / "videos"
    existing = _make_video(videos_dir / "rising-001.mp4")
    source = _make_video(tmp_path / "rising-001.mp4")
    existing.write_bytes(b"already-there")

    result = intake_validation_video(
        site_dir=site_dir,
        video_path=source,
        video_id="rising-001",
        purpose="possible_rising_water",
        split="practice",
        notes="Filename already present.",
    )

    assert not result.created
    assert "already exists" in result.message
    assert existing.read_bytes() == b"already-there"
    assert not (site_dir / "manifest.jsonl").exists()


def test_intake_validation_video_overwrites_when_requested(tmp_path: Path) -> None:
    site_dir = _make_site(tmp_path)
    first = _make_video(tmp_path / "first.mp4")
    first.write_bytes(b"first-bytes")
    second = _make_video(tmp_path / "second.mp4")
    second.write_bytes(b"second-bytes")

    intake_validation_video(
        site_dir=site_dir,
        video_path=first,
        video_id="rising-001",
        purpose="old_purpose",
        split="practice",
        notes="Original row.",
    )
    result = intake_validation_video(
        site_dir=site_dir,
        video_path=second,
        video_id="rising-001",
        purpose="new_purpose",
        split="locked_validation",
        notes="Replaced row.",
        hard_case_type="heavy_glare",
        overwrite=True,
    )

    dest = site_dir / "inputs" / "videos" / "rising-001.mp4"
    assert result.created
    assert dest.read_bytes() == b"second-bytes"
    records = load_manifest_records(result.manifest_path)
    assert len(records) == 1
    assert records[0]["purpose"] == "new_purpose"
    assert records[0]["split"] == "locked_validation"
    assert records[0]["hard_case_type"] == "heavy_glare"


@pytest.mark.parametrize(
    "video_id",
    ["../outside", "has space", "demo/site", ".", ".."],
)
def test_intake_validation_video_refuses_unsafe_video_ids(tmp_path: Path, video_id: str) -> None:
    site_dir = _make_site(tmp_path)
    source = _make_video(tmp_path / "clip.mp4")

    result = intake_validation_video(
        site_dir=site_dir,
        video_path=source,
        video_id=video_id,
        purpose="possible_rising_water",
        split="practice",
        notes="Unsafe id should fail.",
    )

    assert not result.created
    assert "Invalid video_id" in result.message
    video_files = [
        path
        for path in (site_dir / "inputs" / "videos").iterdir()
        if path.suffix.lower() in {".avi", ".mkv", ".mov", ".mp4"}
    ]
    assert video_files == []

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from openfloodai.ingestion import image_video
from openfloodai.ingestion.river_images import RiverImageError, resolve_downloaded_video


def image_batch(root: Path) -> Path:
    batch = root / ("c" * 32)
    batch.mkdir()
    images = []
    # Deliberately reversed: generation must use capture order, not manifest order.
    for minute, value in [(30, 180), (0, 60)]:
        filename = f"river___2026-09-06T09-{minute:02d}-00Z.jpg"
        assert cv2.imwrite(str(batch / filename), np.full((48, 64, 3), value, dtype=np.uint8))
        images.append(
            {
                "filename": filename,
                "status": "downloaded",
                "captured_utc": f"2026-09-06T09:{minute:02d}:00+00:00",
                "requested_utc": f"2026-09-06T09:{minute:02d}:00+00:00",
                "source_url": f"https://example.test/{filename}",
            }
        )
    images.append({"status": "missing", "requested_utc": "2026-09-06T09:15:00+00:00"})
    (batch / "download.json").write_text(json.dumps({"images": images}))
    return batch


def test_video_is_playable_sorted_and_keeps_real_time_mapping(tmp_path: Path) -> None:
    source = image_batch(tmp_path)
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    result = image_video.create_image_test_video(root=tmp_path, source_batch_id=source.name)
    target = resolve_downloaded_video(tmp_path, result["batch_id"], result["filename"])
    capture = cv2.VideoCapture(str(target))
    try:
        assert capture.isOpened()
        assert capture.get(cv2.CAP_PROP_FPS) == 10
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 100
        ok, first = capture.read()
        assert ok and float(first.mean()) < 100
        capture.set(cv2.CAP_PROP_POS_FRAMES, 50)
        ok, second = capture.read()
        assert ok and float(second.mean()) > 150
    finally:
        capture.release()
    assert result["duration_seconds"] == 10
    assert result["frames"][0]["captured_utc"] == "2026-09-06T09:00:00+00:00"
    assert result["frames"][1]["playback_time_window_seconds"] == [5, 10]
    assert len(result["skipped_slots"]) == 1
    metadata = json.loads((target.parent / "download.json").read_text())
    assert metadata["kind"] == "image_test_timelapse"
    assert metadata["source_batch_id"] == source.name
    assert len(metadata["frames"][0]["sha256"]) == 64
    assert before == {path.name: path.read_bytes() for path in source.iterdir()}
    other = image_video.create_image_test_video(root=tmp_path, source_batch_id=source.name)
    assert other["batch_id"] != result["batch_id"]


@pytest.mark.parametrize("problem", ["one_image", "unreadable", "moved", "dimensions", "time"])
def test_invalid_inputs_do_not_create_a_video_batch(tmp_path: Path, problem: str) -> None:
    source = image_batch(tmp_path)
    metadata_path = source / "download.json"
    metadata = json.loads(metadata_path.read_text())
    path = source / metadata["images"][0]["filename"]
    if problem == "one_image":
        metadata["images"][0]["status"] = "failed"
    elif problem == "unreadable":
        path.write_bytes(b"not a JPEG")
    elif problem == "moved":
        path.unlink()
    elif problem == "dimensions":
        assert cv2.imwrite(str(path), np.zeros((32, 32, 3), dtype=np.uint8))
    else:
        metadata["images"][0]["captured_utc"] = "unknown"
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises((RiverImageError, OSError)):
        image_video.create_image_test_video(root=tmp_path, source_batch_id=source.name)
    assert list(tmp_path.iterdir()) == [source]


def test_encoder_failure_cleans_output_not_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = image_batch(tmp_path)
    writer = MagicMock()
    writer.isOpened.return_value = False
    writer_type = MagicMock(return_value=writer)
    writer_type.fourcc.return_value = cv2.VideoWriter.fourcc(*"mp4v")
    monkeypatch.setattr(cv2, "VideoWriter", writer_type)
    with pytest.raises(RiverImageError, match="encoder"):
        image_video.create_image_test_video(root=tmp_path, source_batch_id=source.name)
    writer.release.assert_called_once()
    assert list(tmp_path.iterdir()) == [source]


def test_converter_rejects_paths_and_symlinked_batch(tmp_path: Path) -> None:
    with pytest.raises(RiverImageError):
        image_video.create_image_test_video(root=tmp_path, source_batch_id="../outside")
    source = image_batch(tmp_path)
    alias = tmp_path / ("d" * 32)
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(RiverImageError):
        image_video.create_image_test_video(root=tmp_path, source_batch_id=alias.name)

from __future__ import annotations

import io
import json
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pytest

from openfloodai.ingestion import river_images as river

MP4 = b"\x00\x00\x00\x18ftypisom" + b"test-movie-data"


def mock_video(
    monkeypatch: pytest.MonkeyPatch,
    *,
    body: bytes = MP4,
    content_type: str = "video/mp4",
    expected_size: int | None = None,
) -> MagicMock:
    response = MagicMock()
    response.headers = Message()
    response.headers["Content-Type"] = content_type
    response.headers["Content-Length"] = str(len(body) if expected_size is None else expected_size)
    response.headers["Last-Modified"] = "Tue, 15 Sep 2026 12:00:00 GMT"
    response.read.side_effect = io.BytesIO(body).read
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    monkeypatch.setattr(river, "build_opener", lambda *args: opener)
    return opener


def test_latest_video_uses_documented_url_and_preserves_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = mock_video(monkeypatch)
    result = river.download_latest_timelapse(
        camera_url=river.DEFAULT_CAMERA_URL, output_root=tmp_path
    )
    expected_url = (
        river.ARCHIVE_URL + "timelapse/CO_Colorado_River_near_Cameo/"
        "CO_Colorado_River_near_Cameo_720.mp4"
    )
    assert opener.open.call_args.args[0].full_url == expected_url
    folder = Path(result["output_directory"])
    assert (folder / result["filename"]).read_bytes() == MP4
    metadata = json.loads((folder / "download.json").read_text())
    assert metadata["kind"] == "latest_timelapse"
    assert metadata["source_url"] == expected_url
    assert metadata["capture_time_range"] is None
    assert metadata["downloaded_at_utc"]
    assert "requested_local_hour" not in metadata
    assert river.resolve_downloaded_video(
        tmp_path, result["batch_id"], result["filename"]
    ).is_file()
    mock_video(monkeypatch)
    newer = river.download_latest_timelapse(
        camera_url=river.DEFAULT_CAMERA_URL, output_root=tmp_path
    )
    assert newer["batch_id"] != result["batch_id"]
    assert (folder / result["filename"]).read_bytes() == MP4


@pytest.mark.parametrize(
    "body, content_type, expected_size, message",
    [
        (b"<html>Unavailable</html>", "text/html", None, "MP4"),
        (b"invalid MP4 data", "video/mp4", None, "recognisable"),
        (MP4, "video/mp4", len(MP4) + 10, "incomplete"),
        (b"", "video/mp4", None, "incomplete"),
    ],
)
def test_invalid_or_incomplete_video_leaves_no_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    content_type: str,
    expected_size: int | None,
    message: str,
) -> None:
    mock_video(monkeypatch, body=body, content_type=content_type, expected_size=expected_size)
    with pytest.raises(river.RiverImageError, match=message):
        river.download_latest_timelapse(camera_url=river.DEFAULT_CAMERA_URL, output_root=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "failure", ["missing", "timeout", "oversized", "oversized_without_length", "elapsed"]
)
def test_failed_transfer_is_cleaned_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    opener = mock_video(monkeypatch)
    if failure == "missing":
        opener.open.side_effect = HTTPError(river.ARCHIVE_URL, 404, "Not found", Message(), None)
    elif failure == "timeout":
        opener.open.return_value.__enter__.return_value.read.side_effect = TimeoutError()
    elif failure.startswith("oversized"):
        monkeypatch.setattr(river, "MAX_VIDEO_BYTES", 10)
        if failure == "oversized_without_length":
            del opener.open.return_value.__enter__.return_value.headers["Content-Length"]
    else:
        times = iter([0, 121])
        monkeypatch.setattr(river, "monotonic", lambda: next(times))
    with pytest.raises(river.RiverImageError):
        river.download_latest_timelapse(camera_url=river.DEFAULT_CAMERA_URL, output_root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_video_viewer_requires_batch_metadata_and_refuses_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_video(monkeypatch)
    result = river.download_latest_timelapse(
        camera_url=river.DEFAULT_CAMERA_URL, output_root=tmp_path
    )
    folder = Path(result["output_directory"])
    file = folder / result["filename"]
    file.unlink()
    target = tmp_path / "private.mp4"
    target.write_bytes(MP4)
    file.symlink_to(target)
    with pytest.raises(river.RiverImageError):
        river.resolve_downloaded_video(tmp_path, result["batch_id"], result["filename"])
    with pytest.raises(river.RiverImageError):
        river.resolve_downloaded_video(tmp_path, "../", "private.mp4")
    file.unlink()
    file.write_bytes(MP4)
    (folder / "download.json").write_text('{"kind": "images"}')
    with pytest.raises(river.RiverImageError):
        river.resolve_downloaded_video(tmp_path, result["batch_id"], result["filename"])

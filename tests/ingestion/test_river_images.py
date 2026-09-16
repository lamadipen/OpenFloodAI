from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

from openfloodai.ingestion import river_images as river

SLUG = "CO_Colorado_River_near_Cameo"
JPEG = b"\xff\xd8\xff\xe0test-image\xff\xd9"


def listing(timestamp: str) -> bytes:
    key = f"720/{SLUG}/{SLUG}___{timestamp}.jpg"
    return (
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<Contents><Key>{key}</Key></Contents></ListBucketResult>"
    ).encode()


@pytest.mark.parametrize(
    "url",
    [
        "http://apps.usgs.gov/hivis/camera/test",
        "https://example.com/hivis/camera/test",
        "https://apps.usgs.gov.evil.test/hivis/camera/test",
        "https://apps.usgs.gov/hivis/camera/../secret",
        "https://apps.usgs.gov/hivis/camera/test?url=http://localhost",
    ],
)
def test_camera_url_rejects_other_hosts_and_paths(url: str) -> None:
    with pytest.raises(river.RiverImageError):
        river.camera_slug(url)


def test_local_hour_uses_camera_zone_and_utc_date_rollover() -> None:
    times = river.parse_local_datetimes("2026-09-06 23:00", "America/Denver")
    assert times == [datetime(2026, 9, 7, 5, minute, tzinfo=UTC) for minute in (0, 15, 30, 45)]


@pytest.mark.parametrize(
    "hour, zone",
    [
        ("2026-09-06 09:15", "UTC"),
        ("2026-02-30 09", "UTC"),
        ("2026-09-06 09", "not/a/zone"),
        ("2026-03-08 02", "America/Denver"),
        ("2026-11-01 01", "America/Denver"),
    ],
)
def test_invalid_or_ambiguous_hours_are_rejected(hour: str, zone: str) -> None:
    with pytest.raises(river.RiverImageError):
        river.parse_local_datetimes(hour, zone)


def test_timezone_fallback_never_uses_computer_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USGS_NIMS_API_KEY", raising=False)
    assert river.camera_timezone(SLUG) == "America/Denver"
    with pytest.raises(river.RiverImageError, match="timezone"):
        river.camera_timezone("other_camera")


def test_exact_timestamp_is_included_and_late_image_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = listing("2026-09-06T15-00-00Z")

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        query = parse_qs(urlsplit(url).query)
        assert query["start-after"] == [f"720/{SLUG}/{SLUG}___2026-09-06T15-00-00Z"]
        assert query["max-keys"] == ["1"]
        return response, "application/xml"

    monkeypatch.setattr(river, "_fetch", fetch)
    requested = datetime(2026, 9, 6, 15, tzinfo=UTC)
    match = river.archive_image(SLUG, requested)
    assert match is not None and match[1] == requested
    response = listing("2026-09-06T15-15-00Z")
    assert river.archive_image(SLUG, requested) is None
    response = listing("2026-09-07T15-00-00Z")
    assert river.archive_image(SLUG, requested) is None


def test_partial_batch_preserves_actual_times_and_source_without_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        if "?" not in url:
            return JPEG, "image/jpeg"
        start = parse_qs(urlsplit(url).query)["start-after"][0]
        if "15-00-00" in start:
            return listing("2026-09-06T15-00-06Z"), "application/xml"
        if "15-15-00" in start:
            return listing("2026-09-06T15-30-00Z"), "application/xml"
        if "15-30-00" in start:
            raise river.RiverImageError("Archive timeout")
        return listing("2026-09-06T15-45-03Z"), "application/xml"

    monkeypatch.setattr(river, "_fetch", fetch)
    first = river.download_river_images(
        camera_url=river.DEFAULT_CAMERA_URL,
        local_hour="2026-09-06 09",
        timezone_name="America/Denver",
        output_root=tmp_path,
    )
    second = river.download_river_images(
        camera_url=river.DEFAULT_CAMERA_URL,
        local_hour="2026-09-06 09",
        timezone_name="America/Denver",
        output_root=tmp_path,
    )
    assert first.directory != second.directory
    assert [item.status for item in first.images] == [
        "downloaded",
        "missing",
        "failed",
        "downloaded",
    ]
    assert first.images[0].captured_utc == "2026-09-06T15:00:06+00:00"
    assert "15-00-06Z" in (first.images[0].filename or "")
    metadata = json.loads((first.directory / "download.json").read_text())
    assert metadata["success"] is False
    assert metadata["camera_url"] == river.DEFAULT_CAMERA_URL
    assert metadata["images"][0]["source_url"].startswith(river.ARCHIVE_URL)
    assert len(list(first.directory.glob("*.jpg"))) == 2


def test_non_jpeg_response_is_not_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        river, "archive_image", lambda slug, requested: (river.ARCHIVE_URL + "bad.jpg", requested)
    )
    monkeypatch.setattr(
        river, "_fetch", lambda *args, **kwargs: (b"<html>Error</html>", "text/html")
    )
    result = river.download_river_images(
        camera_url=river.DEFAULT_CAMERA_URL,
        local_hour="2026-09-06 09",
        timezone_name="UTC",
        output_root=tmp_path,
    )
    assert all(image.status == "failed" for image in result.images)
    assert not list(result.directory.glob("*.jpg"))


def test_response_size_and_redirects_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    response = MagicMock()
    response.read.return_value = b"too large"
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    monkeypatch.setattr(river, "build_opener", lambda *args: opener)
    with pytest.raises(river.RiverImageError, match="size limit"):
        river._fetch(river.ARCHIVE_URL, limit=4)
    response.read.assert_called_once_with(5)
    with pytest.raises(river.RiverImageError, match="redirected"):
        river._NoRedirects().redirect_request()


def test_viewer_rejects_traversal_and_symlinks(tmp_path: Path) -> None:
    filename = f"{SLUG}___2026-09-06T15-00-00Z.jpg"
    batch = tmp_path / ("a" * 32)
    batch.mkdir()
    outside = tmp_path / "private.jpg"
    outside.write_bytes(JPEG)
    (batch / filename).symlink_to(outside)
    requests = [("../", filename), (batch.name, "../../private.jpg"), (batch.name, filename)]
    for batch_id, name in requests:
        with pytest.raises(river.RiverImageError):
            river.resolve_downloaded_image(tmp_path, batch_id, name)

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from openfloodai.ingestion import river_images as river

SLUG = "CO_Colorado_River_near_Cameo"
JPEG = b"\xff\xd8\xff\xe0test-image\xff\xd9"


def _key(timestamp: str) -> str:
    return f"720/{SLUG}/{SLUG}___{timestamp}.jpg"


def listing(
    entries: list[tuple[str, int]], *, truncated: bool = False, next_token: str = ""
) -> bytes:
    contents = "".join(
        f"<Contents><Key>{_key(timestamp)}</Key><Size>{size}</Size></Contents>"
        for timestamp, size in entries
    )
    truncated_tag = f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>"
    token_tag = f"<NextContinuationToken>{next_token}</NextContinuationToken>" if next_token else ""
    return (
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"{contents}{truncated_tag}{token_tag}</ListBucketResult>"
    ).encode()


def test_parse_sequence_date_range_covers_whole_local_days() -> None:
    start_utc, end_utc = river.parse_sequence_date_range(
        "2026-09-01", "2026-09-02", "America/Denver"
    )
    assert start_utc == datetime(2026, 9, 1, 6, tzinfo=UTC)
    assert end_utc == datetime(2026, 9, 3, 6, tzinfo=UTC)


@pytest.mark.parametrize(
    "start, end, zone",
    [
        ("2026-09-02", "2026-09-01", "UTC"),
        ("not-a-date", "2026-09-01", "UTC"),
        ("2026-09-01", "2026-09-02", "not/a/zone"),
    ],
)
def test_parse_sequence_date_range_rejects_invalid_input(start: str, end: str, zone: str) -> None:
    with pytest.raises(river.RiverImageError):
        river.parse_sequence_date_range(start, end, zone)


def _candidate(hour: int, minute: int = 0, size: int = 100) -> river.ImageSequenceCandidate:
    captured = datetime(2026, 9, 1, hour, minute, tzinfo=UTC)
    return river.ImageSequenceCandidate(f"{river.ARCHIVE_URL}{hour}-{minute}.jpg", captured, size)


def test_sample_all_returns_every_candidate() -> None:
    candidates = [_candidate(0), _candidate(1), _candidate(2)]
    assert river.sample_image_sequence_candidates(candidates, "all") == candidates


def test_sample_one_per_hour_keeps_first_seen_per_hour() -> None:
    candidates = [_candidate(9, 0), _candidate(9, 30), _candidate(10, 0)]
    sampled = river.sample_image_sequence_candidates(candidates, "one_per_hour")
    assert [c.captured_utc.minute for c in sampled] == [0, 0]
    assert sampled[0] is candidates[0]
    assert sampled[1] is candidates[2]


def test_sample_one_per_day_keeps_first_seen_per_day() -> None:
    day_two = river.ImageSequenceCandidate(
        f"{river.ARCHIVE_URL}day2.jpg", datetime(2026, 9, 2, 5, tzinfo=UTC), 50
    )
    candidates = [_candidate(1), _candidate(23), day_two]
    sampled = river.sample_image_sequence_candidates(candidates, "one_per_day")
    assert len(sampled) == 2
    assert sampled[0] is candidates[0]
    assert sampled[1] is day_two


def test_sample_rejects_invalid_mode() -> None:
    with pytest.raises(river.RiverImageError):
        river.sample_image_sequence_candidates([], "nightly")


def test_sample_daylight_picks_image_nearest_local_noon() -> None:
    candidates = [_candidate(9, 45), _candidate(11, 45), _candidate(12, 15), _candidate(16, 0)]
    sampled = river.sample_image_sequence_candidates(candidates, "one_daylight_image_per_day")
    assert len(sampled) == 1
    assert sampled[0] is candidates[2]


def test_sample_daylight_skips_day_with_no_image_inside_window() -> None:
    candidates = [_candidate(6, 0), _candidate(20, 0)]
    sampled = river.sample_image_sequence_candidates(candidates, "one_daylight_image_per_day")
    assert sampled == []


def test_sample_daylight_respects_configurable_window() -> None:
    candidates = [_candidate(8, 0)]
    assert river.sample_image_sequence_candidates(candidates, "one_daylight_image_per_day") == []
    widened = river.sample_image_sequence_candidates(
        candidates,
        "one_daylight_image_per_day",
        daylight_window_start_hour=7,
        daylight_window_end_hour=9,
    )
    assert widened == candidates


def test_sample_daylight_rejects_invalid_window() -> None:
    with pytest.raises(river.RiverImageError):
        river.sample_image_sequence_candidates(
            [_candidate(9)],
            "one_daylight_image_per_day",
            daylight_window_start_hour=14,
            daylight_window_end_hour=10,
        )


def test_utc_calendar_year_windows_splits_and_clips() -> None:
    windows = river._utc_calendar_year_windows(
        datetime(2024, 6, 1, tzinfo=UTC), datetime(2026, 8, 30, tzinfo=UTC)
    )
    assert windows == [
        (datetime(2024, 6, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
        (datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
        (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 8, 30, tzinfo=UTC)),
    ]


def test_list_archive_images_between_windowed_issues_one_listing_per_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        calls.append(url)
        query = parse_qs(urlsplit(url).query)
        start_after = query.get("start-after", [""])[0]
        if start_after.endswith("2024-06-01T00-00-00Z"):
            return listing([("2024-12-31T00-00-00Z", 10)]), "application/xml"
        return listing([("2025-06-01T00-00-00Z", 20)]), "application/xml"

    monkeypatch.setattr(river, "_fetch", fetch)
    candidates = river.list_archive_images_between_windowed(
        SLUG, datetime(2024, 6, 1, tzinfo=UTC), datetime(2025, 12, 31, tzinfo=UTC)
    )
    assert [c.captured_utc.year for c in candidates] == [2024, 2025]
    assert len(calls) == 2


def test_list_archive_images_between_paginates_and_stops_at_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_one = listing(
        [("2026-09-01T00-00-00Z", 100), ("2026-09-01T01-00-00Z", 200)],
        truncated=True,
        next_token="page2",
    )
    page_two = listing(
        [("2026-09-01T02-00-00Z", 300), ("2026-09-02T00-00-00Z", 999)],
    )
    calls: list[str] = []

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        calls.append(url)
        query = parse_qs(urlsplit(url).query)
        if "continuation-token" in query:
            assert query["continuation-token"] == ["page2"]
            return page_two, "application/xml"
        assert query["start-after"] == [f"720/{SLUG}/{SLUG}___2026-09-01T00-00-00Z"]
        return page_one, "application/xml"

    monkeypatch.setattr(river, "_fetch", fetch)
    candidates = river.list_archive_images_between(
        SLUG,
        datetime(2026, 9, 1, tzinfo=UTC),
        datetime(2026, 9, 1, 12, tzinfo=UTC),
    )
    # The 2026-09-02 entry on page two is past end_utc and must be excluded.
    assert [c.captured_utc.hour for c in candidates] == [0, 1, 2]
    assert [c.size_bytes for c in candidates] == [100, 200, 300]
    assert len(calls) == 2


def test_list_archive_images_between_enforces_candidate_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = [(f"2026-09-01T{hour:02d}-00-00Z", 1) for hour in range(24)]
    page = listing(entries)
    monkeypatch.setattr(river, "_fetch", lambda *a, **k: (page, "application/xml"))
    monkeypatch.setattr(river, "MAX_SEQUENCE_CANDIDATES", 5)
    with pytest.raises(river.RiverImageError, match="too many images"):
        river.list_archive_images_between(
            SLUG, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC)
        )


def test_preview_reports_counts_and_size_without_downloading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = listing([("2026-09-01T09-00-00Z", 1000), ("2026-09-01T10-00-00Z", 2000)])
    monkeypatch.setattr(river, "_fetch", lambda *a, **k: (page, "application/xml"))
    preview = river.preview_river_image_sequence(
        camera_url=river.DEFAULT_CAMERA_URL,
        start_date="2026-09-01",
        end_date="2026-09-01",
        timezone_name="UTC",
        sampling_mode="all",
    )
    assert preview.candidate_count == 2
    assert preview.sampled_count == 2
    assert preview.estimated_bytes == 3000
    assert preview.camera_id == SLUG


def test_download_sequence_records_downloaded_missing_and_writes_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two candidates in hour 9, none in hour 10 (of a 0-11 UTC range) -> one_per_hour
    # samples hour 9 once and must record hour 10 as an explicit "missing" bucket.
    page = listing([("2026-09-01T09-00-00Z", 10), ("2026-09-01T09-30-00Z", 10)])

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        if "?" in url:
            return page, "application/xml"
        return JPEG, "image/jpeg"

    monkeypatch.setattr(river, "_fetch", fetch)
    site_dir = tmp_path / "site"
    site_dir.mkdir()

    result = river.download_river_image_sequence(
        camera_url=river.DEFAULT_CAMERA_URL,
        start_date="2026-09-01",
        end_date="2026-09-01",
        timezone_name="UTC",
        sampling_mode="one_per_hour",
        site_id="test-site",
        site_dir=site_dir,
    )

    statuses = sorted(record.download_status for record in result.records)
    assert statuses.count("downloaded") == 1
    assert statuses.count("missing") == 23  # 24 hourly buckets, only hour 9 has data

    sequence_dir = site_dir / "inputs" / "image-sequences" / result.sequence_id
    assert sequence_dir == result.directory
    images = list((sequence_dir / "images").glob("*.jpg"))
    assert len(images) == 1

    manifest_lines = (sequence_dir / "sequence-manifest.jsonl").read_text().splitlines()
    assert len(manifest_lines) == 24
    first_record = json.loads(manifest_lines[0])
    assert first_record["source_system"] == "usgs_nims"
    assert first_record["site_id"] == "test-site"

    summary = json.loads((sequence_dir / "download-summary.json").read_text())
    assert summary["downloaded_count"] == 1
    assert summary["missing_count"] == 23
    assert summary["failed_count"] == 0

    with pytest.raises(river.RiverImageError, match="already exists"):
        river.download_river_image_sequence(
            camera_url=river.DEFAULT_CAMERA_URL,
            start_date="2026-09-01",
            end_date="2026-09-01",
            timezone_name="UTC",
            sampling_mode="one_per_hour",
            site_id="test-site",
            site_dir=site_dir,
        )

    # A different sampling mode for the same camera/date range must not
    # collide with the sequence already saved above.
    other_mode_result = river.download_river_image_sequence(
        camera_url=river.DEFAULT_CAMERA_URL,
        start_date="2026-09-01",
        end_date="2026-09-01",
        timezone_name="UTC",
        sampling_mode="all",
        site_id="test-site",
        site_dir=site_dir,
    )
    assert other_mode_result.sequence_id != result.sequence_id
    assert other_mode_result.sequence_id.endswith("-all")
    assert result.sequence_id.endswith("-one_per_hour")


def test_download_sequence_with_overwrite_replaces_a_failed_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    attempt = {"n": 0}

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        if "?" in url:
            return listing([("2026-09-01T09-00-00Z", 10)]), "application/xml"
        attempt["n"] += 1
        if attempt["n"] == 1:
            return b"<html>error</html>", "text/html"
        return JPEG, "image/jpeg"

    monkeypatch.setattr(river, "_fetch", fetch)
    first = river.download_river_image_sequence(
        camera_url=river.DEFAULT_CAMERA_URL,
        start_date="2026-09-01",
        end_date="2026-09-01",
        timezone_name="UTC",
        sampling_mode="all",
        site_id="test-site",
        site_dir=site_dir,
    )
    assert [record.download_status for record in first.records] == ["failed"]

    retried = river.download_river_image_sequence(
        camera_url=river.DEFAULT_CAMERA_URL,
        start_date="2026-09-01",
        end_date="2026-09-01",
        timezone_name="UTC",
        sampling_mode="all",
        site_id="test-site",
        site_dir=site_dir,
        overwrite=True,
    )
    assert retried.sequence_id == first.sequence_id
    assert [record.download_status for record in retried.records] == ["downloaded"]


def test_download_sequence_with_resume_reuses_downloaded_images_and_retries_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    page = listing([("2026-09-01T09-00-00Z", 10), ("2026-09-01T10-00-00Z", 10)])
    fetch_calls: list[str] = []

    def fetch_first(url: str, **kwargs: object) -> tuple[bytes, str]:
        fetch_calls.append(url)
        if "?" in url:
            return page, "application/xml"
        if "09-00-00" in url:
            return JPEG, "image/jpeg"
        return b"<html>error</html>", "text/html"

    monkeypatch.setattr(river, "_fetch", fetch_first)
    first = river.download_river_image_sequence(
        camera_url=river.DEFAULT_CAMERA_URL,
        start_date="2026-09-01",
        end_date="2026-09-01",
        timezone_name="UTC",
        sampling_mode="all",
        site_id="test-site",
        site_dir=site_dir,
    )
    statuses = {record.filename: record.download_status for record in first.records}
    assert statuses[f"{SLUG}___2026-09-01T09-00-00Z.jpg"] == "downloaded"
    assert statuses[f"{SLUG}___2026-09-01T10-00-00Z.jpg"] == "failed"

    fetch_calls.clear()

    def fetch_retry(url: str, **kwargs: object) -> tuple[bytes, str]:
        fetch_calls.append(url)
        if "?" in url:
            return page, "application/xml"
        return JPEG, "image/jpeg"

    monkeypatch.setattr(river, "_fetch", fetch_retry)
    resumed = river.download_river_image_sequence(
        camera_url=river.DEFAULT_CAMERA_URL,
        start_date="2026-09-01",
        end_date="2026-09-01",
        timezone_name="UTC",
        sampling_mode="all",
        site_id="test-site",
        site_dir=site_dir,
        resume=True,
    )
    statuses = {record.filename: record.download_status for record in resumed.records}
    assert statuses[f"{SLUG}___2026-09-01T09-00-00Z.jpg"] == "downloaded"
    assert statuses[f"{SLUG}___2026-09-01T10-00-00Z.jpg"] == "downloaded"
    # Resume must not re-fetch the already-downloaded image, only the failed one.
    image_fetches = [url for url in fetch_calls if "?" not in url]
    assert len(image_fetches) == 1
    assert "10-00-00" in image_fetches[0]


def test_download_sequence_records_failed_image_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = listing([("2026-09-01T09-00-00Z", 10)])

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        if "?" in url:
            return page, "application/xml"
        return b"<html>error</html>", "text/html"

    monkeypatch.setattr(river, "_fetch", fetch)
    site_dir = tmp_path / "site"
    site_dir.mkdir()

    result = river.download_river_image_sequence(
        camera_url=river.DEFAULT_CAMERA_URL,
        start_date="2026-09-01",
        end_date="2026-09-01",
        timezone_name="UTC",
        sampling_mode="all",
        site_id="test-site",
        site_dir=site_dir,
    )
    assert [record.download_status for record in result.records] == ["failed"]
    assert result.to_dict()["success"] is False


def test_list_site_image_sequences_and_resolve_sequence_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = listing([("2026-09-01T09-00-00Z", 10)])

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        if "?" in url:
            return page, "application/xml"
        return JPEG, "image/jpeg"

    monkeypatch.setattr(river, "_fetch", fetch)
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    result = river.download_river_image_sequence(
        camera_url=river.DEFAULT_CAMERA_URL,
        start_date="2026-09-01",
        end_date="2026-09-01",
        timezone_name="UTC",
        sampling_mode="all",
        site_id="test-site",
        site_dir=site_dir,
    )

    summaries = river.list_site_image_sequences(site_dir)
    assert len(summaries) == 1
    assert summaries[0]["sequence_id"] == result.sequence_id

    filename = next(
        record.filename for record in result.records if record.download_status == "downloaded"
    )
    resolved = river.resolve_sequence_image(site_dir, result.sequence_id, filename)
    assert resolved.is_file()

    with pytest.raises(river.RiverImageError):
        river.resolve_sequence_image(site_dir, "../etc", filename)
    with pytest.raises(river.RiverImageError):
        river.resolve_sequence_image(site_dir, result.sequence_id, "../../secret.jpg")

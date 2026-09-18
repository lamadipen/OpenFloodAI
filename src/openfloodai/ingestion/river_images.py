"""Download public USGS HIVIS archive images and latest time-lapse MP4s for local review."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from http.client import HTTPException
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from openfloodai.contracts import read_jsonl_records, write_jsonl_records

DEFAULT_CAMERA_URL = "https://apps.usgs.gov/hivis/camera/CO_Colorado_River_near_Cameo"
ARCHIVE_URL = "https://usgs-nims-images.s3.amazonaws.com/"
CAMERA_API_URL = "https://api.waterdata.usgs.gov/nims/v0/cameras?enabled=true"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 128 * 1024 * 1024
MAX_VIDEO_SECONDS = 120
MAX_METADATA_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 15

ALLOWED_SEQUENCE_SAMPLING_MODES = {
    "one_per_day",
    "one_per_hour",
    "all",
    "one_daylight_image_per_day",
}
_DAY_BUCKET_SAMPLING_MODES = {"one_per_day", "one_daylight_image_per_day"}
MAX_SEQUENCE_CANDIDATES = 20_000
MAX_SEQUENCE_LISTING_PAGES = 50
_SEQUENCE_LISTING_PAGE_SIZE = 1000
DEFAULT_DAYLIGHT_WINDOW_START_HOUR = 10
DEFAULT_DAYLIGHT_WINDOW_END_HOUR = 14
_NOON_SECONDS = 12 * 3600
_SEQUENCE_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_SEQUENCE_ID_PATTERN = re.compile(
    r"usgs-[A-Za-z0-9_-]{1,160}-\d{4}-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}-"
    r"(?:" + "|".join(sorted(ALLOWED_SEQUENCE_SAMPLING_MODES)) + ")"
)


class RiverImageError(ValueError):
    """An invalid request or unavailable archive response."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> Request | None:
        raise RiverImageError("The archive redirected the request. No media was downloaded.")


def _fetch(url: str, *, limit: int, api_key: str = "") -> tuple[bytes, str]:
    headers = {"User-Agent": "OpenFloodAI-river-images/1.0"}
    if api_key:
        headers["X-Api-Key"] = api_key
    try:
        with build_opener(_NoRedirects()).open(
            Request(url, headers=headers), timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            data = response.read(limit + 1)
            content_type = response.headers.get_content_type()
    except HTTPError as error:
        raise RiverImageError(f"USGS archive request failed (HTTP {error.code}).") from error
    except (URLError, OSError, HTTPException) as error:
        raise RiverImageError("Could not reach the USGS archive. Try again later.") from error
    if len(data) > limit:
        raise RiverImageError("The archive response exceeded the download size limit.")
    return data, content_type


def camera_slug(camera_url: str) -> str:
    """Accept only an official HTTPS HIVIS camera page, never an arbitrary URL."""
    parsed = urlsplit(camera_url.strip())
    match = re.fullmatch(r"/hivis/camera/([A-Za-z0-9_-]{1,160})/?", parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "apps.usgs.gov"
        or parsed.query
        or parsed.fragment
        or not match
    ):
        raise RiverImageError(
            "Enter a camera URL like https://apps.usgs.gov/hivis/camera/CAMERA_ID."
        )
    return match.group(1)


def camera_timezone(slug: str) -> str:
    """Discover a camera's zone without embedding credentials in source or browser code."""
    api_key = os.environ.get("USGS_NIMS_API_KEY", "")
    if api_key:
        try:
            data, _ = _fetch(CAMERA_API_URL, limit=MAX_METADATA_BYTES, api_key=api_key)
            cameras = json.loads(data)
            if isinstance(cameras, list):
                for camera in cameras:
                    if isinstance(camera, dict) and camera.get("camId") == slug:
                        zone = camera.get("tz")
                        if isinstance(zone, str) and zone:
                            return zone
        except (RiverImageError, ValueError):
            pass
    if slug == "CO_Colorado_River_near_Cameo":
        return "America/Denver"
    raise RiverImageError(
        "Could not find this camera's timezone. Enter an IANA timezone, such as America/Denver."
    )


def parse_local_datetimes(value: str, timezone_name: str) -> list[datetime]:
    """Return four UTC times; reject nonexistent or ambiguous daylight-saving hours."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}(:00)?", value):
        raise RiverImageError("Enter a date and whole hour, such as 2026-09-06 09:00.")
    try:
        hour = datetime.strptime(value[:13], "%Y-%m-%d %H")
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise RiverImageError("Check the date, hour, and IANA timezone.") from error
    timestamps = []
    for minute in (0, 15, 30, 45):
        local = hour.replace(minute=minute)
        aware = local.replace(tzinfo=zone)
        utc = aware.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) != local:
            raise RiverImageError(
                "This hour does not exist due to daylight saving. Choose another."
            )
        if aware.utcoffset() != local.replace(tzinfo=zone, fold=1).utcoffset():
            raise RiverImageError(
                "This hour occurs twice due to daylight saving. "
                "Enter its UTC hour with timezone UTC."
            )
        timestamps.append(utc)
    return timestamps


def archive_image(slug: str, requested: datetime) -> tuple[str, datetime] | None:
    """Find the first image within this quarter-hour, including an exact timestamp."""
    prefix = f"720/{slug}/{slug}___"
    # S3 start-after is exclusive: omit .jpg so an exact timestamp is still included.
    query = urlencode(
        {
            "list-type": "2",
            "prefix": f"720/{slug}/",
            "start-after": prefix + requested.strftime("%Y-%m-%dT%H-%M-%SZ"),
            "max-keys": "1",
        }
    )
    data, _ = _fetch(f"{ARCHIVE_URL}?{query}", limit=MAX_METADATA_BYTES)
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise RiverImageError("The archive returned an unreadable image listing.") from error
    key = root.findtext("{*}Contents/{*}Key")
    if not key:
        return None
    match = re.fullmatch(re.escape(prefix) + r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)\.jpg", key)
    if not match:
        raise RiverImageError("The archive returned an unexpected image name.")
    try:
        captured = datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise RiverImageError("The archive returned an invalid capture time.") from error
    if not requested <= captured < requested + timedelta(minutes=15):
        return None
    return ARCHIVE_URL + key, captured


@dataclass(frozen=True)
class ImageResult:
    requested_utc: str
    status: str
    message: str
    captured_utc: str | None = None
    source_url: str | None = None
    filename: str | None = None


@dataclass(frozen=True)
class DownloadResult:
    directory: Path
    timezone: str
    images: list[ImageResult]

    def to_dict(self) -> dict[str, Any]:
        saved = sum(image.status == "downloaded" for image in self.images)
        return {
            "success": saved == 4,
            "message": f"Downloaded {saved} of 4 images. See each time window below.",
            "output_directory": str(self.directory),
            "batch_id": self.directory.name,
            "timezone": self.timezone,
            "images": [asdict(image) for image in self.images],
        }


def download_river_images(
    *, camera_url: str, local_hour: str, timezone_name: str, output_root: Path
) -> DownloadResult:
    """Save up to four images and their provenance in a unique local batch folder."""
    slug = camera_slug(camera_url)
    zone = timezone_name.strip() or camera_timezone(slug)
    timestamps = parse_local_datetimes(local_hour.strip(), zone)
    directory = output_root.resolve() / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    images: list[ImageResult] = []
    for timestamp in timestamps:
        requested = timestamp.isoformat()
        try:
            match = archive_image(slug, timestamp)
            if match is None:
                images.append(
                    ImageResult(requested, "missing", "No image in this 15-minute window.")
                )
                continue
            url, captured = match
            data, content_type = _fetch(url, limit=MAX_IMAGE_BYTES)
            if content_type != "image/jpeg" or not data.startswith(b"\xff\xd8\xff"):
                raise RiverImageError("The archive did not return a JPEG image.")
            filename = url.rsplit("/", 1)[-1]
            (directory / filename).write_bytes(data)
            images.append(
                ImageResult(
                    requested, "downloaded", "Saved locally.", captured.isoformat(), url, filename
                )
            )
        except RiverImageError as error:
            images.append(ImageResult(requested, "failed", str(error)))
    result = DownloadResult(directory, zone, images)
    metadata = result.to_dict() | {
        "camera_url": camera_url.strip(),
        "requested_local_hour": local_hour.strip(),
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
    }
    (directory / "download.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return result


def resolve_downloaded_image(root: Path, batch_id: str, filename: str) -> Path:
    """Serve only JPEG files belonging to a downloader batch, never arbitrary local files."""
    if not re.fullmatch(r"[a-f0-9]{32}", batch_id) or not re.fullmatch(
        r"[A-Za-z0-9_-]+___\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z\.jpg", filename
    ):
        raise RiverImageError("Downloaded image not found.")
    batch = root.resolve() / batch_id
    candidate = batch / filename
    if batch.is_symlink() or candidate.is_symlink() or not candidate.is_file():
        raise RiverImageError("Downloaded image not found.")
    candidate.resolve().relative_to(root.resolve())
    metadata = json.loads((batch / "download.json").read_text(encoding="utf-8"))
    images = metadata.get("images") if isinstance(metadata, dict) else None
    if not isinstance(images, list) or not any(
        isinstance(image, dict)
        and image.get("filename") == filename
        and image.get("status") == "downloaded"
        for image in images
    ):
        raise RiverImageError("Downloaded image not found.")
    return candidate


def download_latest_timelapse(*, camera_url: str, output_root: Path) -> dict[str, Any]:
    """Save the camera's latest MP4, without claiming a requested capture date range."""
    slug = camera_slug(camera_url)
    filename = f"{slug}_720.mp4"
    source_url = f"{ARCHIVE_URL}timelapse/{slug}/{filename}"
    directory = output_root.resolve() / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    partial = directory / "video.part"
    started = monotonic()
    try:
        request = Request(source_url, headers={"User-Agent": "OpenFloodAI-river-images/1.0"})
        with (
            build_opener(_NoRedirects()).open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response,
            partial.open("wb") as output,
        ):
            if response.headers.get_content_type() not in {"video/mp4", "application/octet-stream"}:
                raise RiverImageError("USGS did not return an MP4 video for this camera.")
            length = response.headers.get("Content-Length")
            expected = int(length) if length and length.isdigit() else None
            if expected is not None and expected > MAX_VIDEO_BYTES:
                raise RiverImageError("The time-lapse exceeds the 128 MB download limit.")
            size = 0
            while True:
                block = response.read(64 * 1024)
                if monotonic() - started > MAX_VIDEO_SECONDS:
                    raise RiverImageError("The video download took too long. Try again later.")
                if not block:
                    break
                if size == 0 and (len(block) < 12 or block[4:8] != b"ftyp"):
                    raise RiverImageError("USGS did not return a recognisable MP4 video.")
                size += len(block)
                if size > MAX_VIDEO_BYTES:
                    raise RiverImageError("The time-lapse exceeds the 128 MB download limit.")
                output.write(block)
            if size == 0 or (expected is not None and size != expected):
                raise RiverImageError("The video download was incomplete. Try again.")
            last_modified = response.headers.get("Last-Modified")
        partial.rename(directory / filename)
        payload = {
            "success": True,
            "kind": "latest_timelapse",
            "message": "Latest time-lapse saved. It does not use the selected image date or hour.",
            "camera_url": camera_url.strip(),
            "source_url": source_url,
            "filename": filename,
            "batch_id": directory.name,
            "output_directory": str(directory),
            "downloaded_at_utc": datetime.now(UTC).isoformat(),
            "source_last_modified": last_modified,
            "capture_time_range": None,
            "size_bytes": size,
        }
        (directory / "download.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        return payload
    except Exception as error:
        shutil.rmtree(directory)
        if isinstance(error, HTTPError):
            if error.code == 404:
                raise RiverImageError(
                    "No latest time-lapse is available for this camera."
                ) from error
            raise RiverImageError(f"USGS video request failed (HTTP {error.code}).") from error
        if isinstance(error, (URLError, TimeoutError, HTTPException)):
            raise RiverImageError("The video download was interrupted. Try again later.") from error
        raise


_DOWNLOADED_VIDEO_KINDS = {"latest_timelapse", "image_test_timelapse", "live_camera_clip"}


def resolve_downloaded_video(root: Path, batch_id: str, filename: str) -> Path:
    """Limit video playback/download to completed local time-lapse/clip batches."""
    if not re.fullmatch(r"[a-f0-9]{32}", batch_id) or not re.fullmatch(
        r"(?:[A-Za-z0-9_-]+_720|images_test_timelapse|live_camera_clip)\.mp4", filename
    ):
        raise RiverImageError("Downloaded video not found.")
    directory = root.resolve() / batch_id
    video = directory / filename
    if directory.is_symlink() or video.is_symlink() or not video.is_file():
        raise RiverImageError("Downloaded video not found.")
    video.resolve().relative_to(root.resolve())
    metadata = json.loads((directory / "download.json").read_text(encoding="utf-8"))
    if (
        not isinstance(metadata, dict)
        or metadata.get("kind") not in _DOWNLOADED_VIDEO_KINDS
        or metadata.get("success") is not True
        or metadata.get("filename") != filename
    ):
        raise RiverImageError("Downloaded video not found.")
    return video


@dataclass(frozen=True)
class ImageSequenceCandidate:
    """One archived image discovered by listing the archive, before download."""

    source_url: str
    captured_utc: datetime
    size_bytes: int


def _sequence_bucket_key(moment: datetime, mode: str) -> tuple[int, ...]:
    if mode in _DAY_BUCKET_SAMPLING_MODES:
        return (moment.year, moment.month, moment.day)
    return (moment.year, moment.month, moment.day, moment.hour)


def _expected_sequence_buckets(
    start_utc: datetime, end_utc: datetime, zone: ZoneInfo, mode: str
) -> list[tuple[int, ...]]:
    step = timedelta(days=1) if mode in _DAY_BUCKET_SAMPLING_MODES else timedelta(hours=1)
    current = start_utc.astimezone(zone).replace(minute=0, second=0, microsecond=0)
    if mode in _DAY_BUCKET_SAMPLING_MODES:
        current = current.replace(hour=0)
    end_local = end_utc.astimezone(zone)
    buckets: list[tuple[int, ...]] = []
    while current < end_local:
        buckets.append(_sequence_bucket_key(current, mode))
        current += step
    return buckets


def _in_daylight_window(local: datetime, window_start_hour: int, window_end_hour: int) -> bool:
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    return window_start_hour * 3600 <= seconds <= window_end_hour * 3600


def _select_one_daylight_image_per_day(
    candidates: list[ImageSequenceCandidate],
    zone: ZoneInfo,
    window_start_hour: int,
    window_end_hour: int,
) -> list[ImageSequenceCandidate]:
    """Pick the image nearest local noon, inside the daylight window, per local day.

    A day with images only outside the window (or no images at all) gets no
    selection here — it is reported as a `missing` record by the caller
    rather than silently substituted with a nighttime image.
    """

    by_day: dict[tuple[int, int, int], ImageSequenceCandidate] = {}
    best_diff_by_day: dict[tuple[int, int, int], int] = {}
    for candidate in candidates:
        local = candidate.captured_utc.astimezone(zone)
        if not _in_daylight_window(local, window_start_hour, window_end_hour):
            continue
        day_key = (local.year, local.month, local.day)
        seconds = local.hour * 3600 + local.minute * 60 + local.second
        diff = abs(seconds - _NOON_SECONDS)
        # <= (not <) so an exact tie prefers the later image, matching the
        # plan's own worked example (11:45 vs 12:15 -> 12:15).
        if day_key not in best_diff_by_day or diff <= best_diff_by_day[day_key]:
            best_diff_by_day[day_key] = diff
            by_day[day_key] = candidate
    return sorted(by_day.values(), key=lambda candidate: candidate.captured_utc)


def parse_sequence_date_range(
    start_date: str, end_date: str, timezone_name: str
) -> tuple[datetime, datetime]:
    """Return a [start, end) UTC window covering whole local days."""

    if not _SEQUENCE_DATE_PATTERN.fullmatch(start_date) or not _SEQUENCE_DATE_PATTERN.fullmatch(
        end_date
    ):
        raise RiverImageError("Enter start and end dates as YYYY-MM-DD.")
    try:
        zone = ZoneInfo(timezone_name)
        start_local = datetime.strptime(start_date, "%Y-%m-%d")
        end_local = datetime.strptime(end_date, "%Y-%m-%d")
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise RiverImageError("Check the start date, end date, and IANA timezone.") from error
    if end_local < start_local:
        raise RiverImageError("The end date must be on or after the start date.")
    start_utc = start_local.replace(tzinfo=zone).astimezone(UTC)
    end_utc = (end_local + timedelta(days=1)).replace(tzinfo=zone).astimezone(UTC)
    return start_utc, end_utc


def list_archive_images_between(
    slug: str, start_utc: datetime, end_utc: datetime
) -> list[ImageSequenceCandidate]:
    """List archived images in [start_utc, end_utc) without downloading them."""

    prefix = f"720/{slug}/{slug}___"
    key_pattern = re.compile(re.escape(prefix) + r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)\.jpg")
    # S3 start-after is exclusive: omit .jpg so an exact timestamp match is still included.
    start_after = prefix + start_utc.strftime("%Y-%m-%dT%H-%M-%SZ")
    candidates: list[ImageSequenceCandidate] = []
    continuation_token: str | None = None
    for _ in range(MAX_SEQUENCE_LISTING_PAGES):
        query: dict[str, str] = {
            "list-type": "2",
            "prefix": f"720/{slug}/",
            "max-keys": str(_SEQUENCE_LISTING_PAGE_SIZE),
        }
        if continuation_token:
            query["continuation-token"] = continuation_token
        else:
            query["start-after"] = start_after
        data, _ = _fetch(f"{ARCHIVE_URL}?{urlencode(query)}", limit=MAX_METADATA_BYTES)
        try:
            root = ElementTree.fromstring(data)
        except ElementTree.ParseError as error:
            raise RiverImageError("The archive returned an unreadable image listing.") from error
        reached_end = False
        for contents in root.findall("{*}Contents"):
            key = contents.findtext("{*}Key") or ""
            match = key_pattern.fullmatch(key)
            if not match:
                continue
            try:
                captured = datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%SZ").replace(
                    tzinfo=UTC
                )
            except ValueError as error:
                raise RiverImageError("The archive returned an invalid capture time.") from error
            if captured >= end_utc:
                reached_end = True
                break
            size_text = contents.findtext("{*}Size") or "0"
            size_bytes = int(size_text) if size_text.isdigit() else 0
            candidates.append(ImageSequenceCandidate(ARCHIVE_URL + key, captured, size_bytes))
            if len(candidates) > MAX_SEQUENCE_CANDIDATES:
                raise RiverImageError(
                    "This date range has too many images to list. "
                    "Narrow the date range or pick a sparser sampling mode."
                )
        if reached_end:
            break
        if root.findtext("{*}IsTruncated") != "true":
            break
        continuation_token = root.findtext("{*}NextContinuationToken")
        if not continuation_token:
            break
    return candidates


def _utc_calendar_year_windows(
    start_utc: datetime, end_utc: datetime
) -> list[tuple[datetime, datetime]]:
    """Split a UTC [start, end) range into contiguous whole-calendar-year windows."""

    windows: list[tuple[datetime, datetime]] = []
    current = start_utc
    while current < end_utc:
        next_year_start = datetime(current.year + 1, 1, 1, tzinfo=UTC)
        window_end = min(next_year_start, end_utc)
        windows.append((current, window_end))
        current = window_end
    return windows


def list_archive_images_between_windowed(
    slug: str, start_utc: datetime, end_utc: datetime
) -> list[ImageSequenceCandidate]:
    """List archived images across a range, chunked internally by calendar year.

    A multi-year request would otherwise enumerate far more candidates in a
    single S3 listing than MAX_SEQUENCE_CANDIDATES allows. Listing one
    calendar year at a time keeps each underlying call's candidate count
    bounded while still returning one combined, chronologically ordered list
    for the full requested range.
    """

    candidates: list[ImageSequenceCandidate] = []
    for window_start, window_end in _utc_calendar_year_windows(start_utc, end_utc):
        candidates.extend(list_archive_images_between(slug, window_start, window_end))
    return candidates


def sample_image_sequence_candidates(
    candidates: list[ImageSequenceCandidate],
    mode: str,
    *,
    timezone_name: str = "UTC",
    daylight_window_start_hour: int = DEFAULT_DAYLIGHT_WINDOW_START_HOUR,
    daylight_window_end_hour: int = DEFAULT_DAYLIGHT_WINDOW_END_HOUR,
) -> list[ImageSequenceCandidate]:
    """Reduce a chronological candidate list to one per requested time bucket."""

    if mode not in ALLOWED_SEQUENCE_SAMPLING_MODES:
        allowed = ", ".join(sorted(ALLOWED_SEQUENCE_SAMPLING_MODES))
        raise RiverImageError(f"Invalid sampling mode: use one of {allowed}.")
    if mode == "all":
        return list(candidates)
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise RiverImageError("Enter a valid IANA timezone.") from error
    if mode == "one_daylight_image_per_day":
        if not (0 <= daylight_window_start_hour < daylight_window_end_hour <= 24):
            raise RiverImageError(
                "The daylight window needs a start hour before an end hour, both 0-24."
            )
        return _select_one_daylight_image_per_day(
            candidates, zone, daylight_window_start_hour, daylight_window_end_hour
        )
    seen_buckets: set[tuple[int, ...]] = set()
    sampled: list[ImageSequenceCandidate] = []
    for candidate in candidates:
        bucket = _sequence_bucket_key(candidate.captured_utc.astimezone(zone), mode)
        if bucket in seen_buckets:
            continue
        seen_buckets.add(bucket)
        sampled.append(candidate)
    return sampled


@dataclass(frozen=True)
class ImageSequencePreview:
    """A no-download preview of what a sequence request would fetch."""

    camera_id: str
    timezone: str
    candidate_count: int
    sampled_count: int
    earliest_captured_utc: str | None
    latest_captured_utc: str | None
    estimated_bytes: int
    sampling_mode: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def preview_river_image_sequence(
    *,
    camera_url: str,
    start_date: str,
    end_date: str,
    timezone_name: str,
    sampling_mode: str,
    daylight_window_start_hour: int = DEFAULT_DAYLIGHT_WINDOW_START_HOUR,
    daylight_window_end_hour: int = DEFAULT_DAYLIGHT_WINDOW_END_HOUR,
) -> ImageSequencePreview:
    """Report how many images a sequence request would fetch, without downloading."""

    slug = camera_slug(camera_url)
    zone_name = timezone_name.strip() or camera_timezone(slug)
    start_utc, end_utc = parse_sequence_date_range(start_date.strip(), end_date.strip(), zone_name)
    candidates = list_archive_images_between_windowed(slug, start_utc, end_utc)
    sampled = sample_image_sequence_candidates(
        candidates,
        sampling_mode,
        timezone_name=zone_name,
        daylight_window_start_hour=daylight_window_start_hour,
        daylight_window_end_hour=daylight_window_end_hour,
    )
    return ImageSequencePreview(
        camera_id=slug,
        timezone=zone_name,
        candidate_count=len(candidates),
        sampled_count=len(sampled),
        earliest_captured_utc=sampled[0].captured_utc.isoformat() if sampled else None,
        latest_captured_utc=sampled[-1].captured_utc.isoformat() if sampled else None,
        estimated_bytes=sum(candidate.size_bytes for candidate in sampled),
        sampling_mode=sampling_mode,
    )


@dataclass(frozen=True)
class ImageSequenceRecord:
    """One row of a saved image sequence's manifest."""

    site_id: str
    camera_id: str
    source_url: str
    captured_at_utc: str
    local_time: str
    filename: str
    file_size_bytes: int
    download_status: str
    source_system: str = "usgs_nims"


@dataclass(frozen=True)
class ImageSequenceDownloadResult:
    """Result of downloading a sampled, date-ranged image sequence into a site."""

    directory: Path
    sequence_id: str
    timezone: str
    records: list[ImageSequenceRecord]

    def to_dict(self) -> dict[str, Any]:
        downloaded = sum(record.download_status == "downloaded" for record in self.records)
        missing = sum(record.download_status == "missing" for record in self.records)
        failed = sum(record.download_status == "failed" for record in self.records)
        return {
            "success": failed == 0,
            "message": f"Downloaded {downloaded} image(s); {missing} missing; {failed} failed.",
            "output_directory": str(self.directory),
            "sequence_id": self.sequence_id,
            "timezone": self.timezone,
            "downloaded_count": downloaded,
            "missing_count": missing,
            "failed_count": failed,
            "records": [asdict(record) for record in self.records],
        }


def download_river_image_sequence(
    *,
    camera_url: str,
    start_date: str,
    end_date: str,
    timezone_name: str,
    sampling_mode: str,
    site_id: str,
    site_dir: Path,
    overwrite: bool = False,
    resume: bool = False,
    daylight_window_start_hour: int = DEFAULT_DAYLIGHT_WINDOW_START_HOUR,
    daylight_window_end_hour: int = DEFAULT_DAYLIGHT_WINDOW_END_HOUR,
) -> ImageSequenceDownloadResult:
    """Download a sampled, date-ranged image sequence into a site folder.

    `overwrite` replaces an existing sequence from scratch (unchanged,
    existing behavior). `resume` is new: when the sequence already exists
    and `overwrite` is not set, it reuses images already saved on disk
    (matched by source URL) and only fetches what is missing or previously
    failed, instead of raising. Neither flag set, and an existing sequence,
    still raises exactly as before.
    """

    slug = camera_slug(camera_url)
    zone_name = timezone_name.strip() or camera_timezone(slug)
    start = start_date.strip()
    end = end_date.strip()
    start_utc, end_utc = parse_sequence_date_range(start, end, zone_name)
    candidates = list_archive_images_between_windowed(slug, start_utc, end_utc)
    sampled = sample_image_sequence_candidates(
        candidates,
        sampling_mode,
        timezone_name=zone_name,
        daylight_window_start_hour=daylight_window_start_hour,
        daylight_window_end_hour=daylight_window_end_hour,
    )
    zone = ZoneInfo(zone_name)

    sequence_id = f"usgs-{slug}-{start}-{end}-{sampling_mode}"
    sequence_dir = (site_dir / "inputs" / "image-sequences" / sequence_id).resolve()
    already_downloaded: dict[str, ImageSequenceRecord] = {}
    if sequence_dir.exists():
        if overwrite:
            shutil.rmtree(sequence_dir)
        elif resume:
            manifest_path = sequence_dir / "sequence-manifest.jsonl"
            if manifest_path.is_file():
                for raw_record in read_jsonl_records(manifest_path):
                    filename = raw_record.get("filename")
                    if (
                        raw_record.get("download_status") == "downloaded"
                        and isinstance(filename, str)
                        and filename
                        and (sequence_dir / "images" / filename).is_file()
                    ):
                        already_downloaded[str(raw_record.get("source_url"))] = ImageSequenceRecord(
                            site_id=str(raw_record.get("site_id")),
                            camera_id=str(raw_record.get("camera_id")),
                            source_url=str(raw_record.get("source_url")),
                            captured_at_utc=str(raw_record.get("captured_at_utc")),
                            local_time=str(raw_record.get("local_time")),
                            filename=filename,
                            file_size_bytes=int(str(raw_record.get("file_size_bytes") or 0)),
                            download_status="downloaded",
                            source_system=str(raw_record.get("source_system", "usgs_nims")),
                        )
        else:
            raise RiverImageError(
                "An image sequence already exists for this camera and date range: "
                f"{sequence_id}. Use overwrite to replace it."
            )
    images_dir = sequence_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    records: list[ImageSequenceRecord] = []
    for candidate in sampled:
        filename = candidate.source_url.rsplit("/", 1)[-1]
        local_time = candidate.captured_utc.astimezone(zone).isoformat()
        reused = already_downloaded.get(candidate.source_url)
        if reused is not None:
            records.append(reused)
            continue
        try:
            data, content_type = _fetch(candidate.source_url, limit=MAX_IMAGE_BYTES)
            if content_type != "image/jpeg" or not data.startswith(b"\xff\xd8\xff"):
                raise RiverImageError("The archive did not return a JPEG image.")
            (images_dir / filename).write_bytes(data)
            records.append(
                ImageSequenceRecord(
                    site_id=site_id,
                    camera_id=slug,
                    source_url=candidate.source_url,
                    captured_at_utc=candidate.captured_utc.isoformat(),
                    local_time=local_time,
                    filename=filename,
                    file_size_bytes=len(data),
                    download_status="downloaded",
                )
            )
        except RiverImageError:
            records.append(
                ImageSequenceRecord(
                    site_id=site_id,
                    camera_id=slug,
                    source_url=candidate.source_url,
                    captured_at_utc=candidate.captured_utc.isoformat(),
                    local_time=local_time,
                    filename=filename,
                    file_size_bytes=0,
                    download_status="failed",
                )
            )

    if sampling_mode != "all":
        present_buckets = {
            _sequence_bucket_key(candidate.captured_utc.astimezone(zone), sampling_mode)
            for candidate in sampled
        }
        for bucket in _expected_sequence_buckets(start_utc, end_utc, zone, sampling_mode):
            if bucket in present_buckets:
                continue
            if len(bucket) == 3:
                bucket_start_local = datetime(bucket[0], bucket[1], bucket[2], tzinfo=zone)
            else:
                bucket_start_local = datetime(
                    bucket[0], bucket[1], bucket[2], bucket[3], tzinfo=zone
                )
            records.append(
                ImageSequenceRecord(
                    site_id=site_id,
                    camera_id=slug,
                    source_url="",
                    captured_at_utc=bucket_start_local.astimezone(UTC).isoformat(),
                    local_time=bucket_start_local.isoformat(),
                    filename="",
                    file_size_bytes=0,
                    download_status="missing",
                )
            )

    records.sort(key=lambda record: record.captured_at_utc)
    write_jsonl_records(
        sequence_dir / "sequence-manifest.jsonl", [asdict(record) for record in records]
    )

    result = ImageSequenceDownloadResult(sequence_dir, sequence_id, zone_name, records)
    summary = result.to_dict() | {
        "camera_url": camera_url.strip(),
        "requested_start_date": start,
        "requested_end_date": end,
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
    }
    (sequence_dir / "download-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return result


def resolve_sequence_image(site_dir: Path, sequence_id: str, filename: str) -> Path:
    """Serve only JPEG files that belong to a saved image-sequence batch."""

    if not _SEQUENCE_ID_PATTERN.fullmatch(sequence_id) or not re.fullmatch(
        r"[A-Za-z0-9_-]+___\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z\.jpg", filename
    ):
        raise RiverImageError("Image not found.")
    sequences_root = (site_dir / "inputs" / "image-sequences").resolve()
    sequence_dir = sequences_root / sequence_id
    candidate = sequence_dir / "images" / filename
    if sequence_dir.is_symlink() or candidate.is_symlink() or not candidate.is_file():
        raise RiverImageError("Image not found.")
    candidate.resolve().relative_to(sequences_root)
    try:
        records = read_jsonl_records(sequence_dir / "sequence-manifest.jsonl")
    except ValueError as error:
        raise RiverImageError("Image not found.") from error
    if not any(
        record.get("filename") == filename and record.get("download_status") == "downloaded"
        for record in records
    ):
        raise RiverImageError("Image not found.")
    return candidate


def list_site_image_sequences(site_dir: Path) -> list[dict[str, Any]]:
    """Return saved download summaries for every image sequence under a site."""

    sequences_dir = site_dir / "inputs" / "image-sequences"
    if not sequences_dir.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for child in sorted(sequences_dir.iterdir()):
        summary_path = child / "download-summary.json"
        if not child.is_dir() or not summary_path.is_file():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(summary, dict):
            summaries.append(summary)
    return summaries

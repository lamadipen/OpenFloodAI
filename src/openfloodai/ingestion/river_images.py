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

DEFAULT_CAMERA_URL = "https://apps.usgs.gov/hivis/camera/CO_Colorado_River_near_Cameo"
ARCHIVE_URL = "https://usgs-nims-images.s3.amazonaws.com/"
CAMERA_API_URL = "https://api.waterdata.usgs.gov/nims/v0/cameras?enabled=true"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 128 * 1024 * 1024
MAX_VIDEO_SECONDS = 120
MAX_METADATA_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 15


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


def resolve_downloaded_video(root: Path, batch_id: str, filename: str) -> Path:
    """Limit video playback/download to completed local time-lapse batches."""
    if not re.fullmatch(r"[a-f0-9]{32}", batch_id) or not re.fullmatch(
        r"(?:[A-Za-z0-9_-]+_720|images_test_timelapse)\.mp4", filename
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
        or metadata.get("kind") not in {"latest_timelapse", "image_test_timelapse"}
        or metadata.get("success") is not True
        or metadata.get("filename") != filename
    ):
        raise RiverImageError("Downloaded video not found.")
    return video

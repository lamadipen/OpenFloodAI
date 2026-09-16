"""Capture a short local clip from an unreliable live HLS camera stream.

Unlike the USGS archive (``river_images.py``), a live camera stream has no
fixed, trusted host to allowlist: the operator supplies their own camera's
URL. ``validate_stream_url`` therefore checks the URL shape (HTTPS, real
host) and resolves the hostname to reject requests aimed at loopback,
private, or link-local addresses, so the local server cannot be used to
probe the operator's own internal network.

The actual frame grab happens in a separate subprocess (``live_camera_worker``)
so a stalled network read can be killed by ``subprocess.run(timeout=...)``
instead of hanging this process indefinitely.
"""

from __future__ import annotations

import ipaddress
import json
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

CLIP_FILENAME = "live_camera_clip.mp4"
DEFAULT_STREAM_URL = "https://camera.damodarpokhrel.com.np/cam3/index.m3u8"
MIN_CLIP_SECONDS = 2
MAX_CLIP_SECONDS = 30
DEFAULT_CLIP_SECONDS = 8
MAX_CLIP_BYTES = 256 * 1024 * 1024
# Generous: HLS manifest/segment fetches can take a few seconds before any
# frame is available, on top of the clip's own capture time.
SUBPROCESS_TIMEOUT_BUFFER_SECONDS = 25

_WORKER_EXIT_MESSAGES = {
    2: "Could not open the live camera stream. It may be offline right now.",
    3: "The live camera stream opened but sent no usable frames. Try again later.",
    4: "The local MP4 encoder is unavailable. No clip was saved.",
}


class LiveCameraError(ValueError):
    """An invalid stream URL or a failed/unavailable live capture attempt."""


def validate_stream_url(stream_url: str) -> str:
    """Return a normalized HTTPS URL, rejecting requests to local/private hosts."""

    parsed = urlsplit(stream_url.strip())
    if parsed.scheme != "https" or not parsed.hostname or "@" in parsed.netloc:
        raise LiveCameraError("Enter an HTTPS live stream URL, such as a camera's .m3u8 link.")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except OSError as error:
        raise LiveCameraError("Could not resolve the camera stream's hostname.") from error
    for address in addresses:
        parsed_address = ipaddress.ip_address(address)
        if (
            parsed_address.is_loopback
            or parsed_address.is_private
            or parsed_address.is_link_local
            or parsed_address.is_reserved
            or parsed_address.is_multicast
        ):
            raise LiveCameraError(
                "This stream URL resolves to a local or private address and cannot be used."
            )
    return parsed.geturl()


def clamp_duration(duration_seconds: object) -> int:
    """Coerce a requested clip length into the supported whole-second range."""

    try:
        value = int(float(duration_seconds))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        value = DEFAULT_CLIP_SECONDS
    return max(MIN_CLIP_SECONDS, min(MAX_CLIP_SECONDS, value))


def capture_live_clip(
    *, stream_url: str, output_root: Path, duration_seconds: object = DEFAULT_CLIP_SECONDS
) -> dict[str, Any]:
    """Try once to save a short clip; raise LiveCameraError if the feed is not working."""

    url = validate_stream_url(stream_url)
    seconds = clamp_duration(duration_seconds)
    directory = output_root.resolve() / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / CLIP_FILENAME
    started_at = datetime.now(UTC)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "openfloodai.ingestion.live_camera_worker",
                url,
                str(target),
                str(seconds),
            ],
            capture_output=True,
            timeout=seconds + SUBPROCESS_TIMEOUT_BUFFER_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        shutil.rmtree(directory, ignore_errors=True)
        raise LiveCameraError(
            "The live camera did not respond in time. It may be offline right now."
        ) from error
    if completed.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        shutil.rmtree(directory, ignore_errors=True)
        raise LiveCameraError(
            _WORKER_EXIT_MESSAGES.get(
                completed.returncode, "Could not capture a clip from the live camera."
            )
        )
    if target.stat().st_size > MAX_CLIP_BYTES:
        shutil.rmtree(directory, ignore_errors=True)
        raise LiveCameraError("The captured clip exceeded the supported size limit.")
    payload = {
        "success": True,
        "kind": "live_camera_clip",
        "message": "Live camera clip saved.",
        "stream_url": url,
        "batch_id": directory.name,
        "output_directory": str(directory),
        "filename": CLIP_FILENAME,
        "requested_duration_seconds": seconds,
        "captured_at_utc": started_at.isoformat(),
        "size_bytes": target.stat().st_size,
    }
    (directory / "download.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload

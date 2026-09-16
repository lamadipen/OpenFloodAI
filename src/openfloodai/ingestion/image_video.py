"""Make a clearly identified test time-lapse from a local river-image batch."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2

from openfloodai.ingestion.river_images import (
    MAX_IMAGE_BYTES,
    RiverImageError,
    resolve_downloaded_image,
)

TEST_VIDEO_FPS = 10
SECONDS_PER_IMAGE = 5
TEST_VIDEO_FILENAME = "images_test_timelapse.mp4"


def create_image_test_video(*, root: Path, source_batch_id: str) -> dict[str, Any]:
    """Hold each saved image for five playback seconds without inventing motion."""
    if not re.fullmatch(r"[a-f0-9]{32}", source_batch_id):
        raise RiverImageError("Choose a downloaded image batch.")
    source = root.resolve() / source_batch_id
    metadata_path = source / "download.json"
    if source.is_symlink() or metadata_path.is_symlink():
        raise RiverImageError("Choose a local downloaded image batch.")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RiverImageError("Image download details are missing or unreadable.") from error
    images = metadata.get("images") if isinstance(metadata, dict) else None
    if (
        not isinstance(images, list)
        or not 2 <= len(images) <= 4
        or not all(isinstance(image, dict) for image in images)
    ):
        raise RiverImageError("Choose a batch with at least two downloaded images.")
    saved = [image for image in images if image.get("status") == "downloaded"]
    if len(saved) < 2:
        raise RiverImageError("At least two downloaded images are needed to make a test video.")
    try:
        for image in saved:
            captured = datetime.fromisoformat(image["captured_utc"])
            if captured.tzinfo is None:
                raise ValueError("Missing timezone")
        saved.sort(key=lambda image: datetime.fromisoformat(image["captured_utc"]))
        if len({image["captured_utc"] for image in saved}) != len(saved):
            raise ValueError("Duplicate capture times")
    except (KeyError, TypeError, ValueError) as error:
        raise RiverImageError("The image batch has invalid capture timestamps.") from error

    frames: list[Any] = []
    frame_map = []
    shape = None
    for index, image in enumerate(saved):
        filename = image.get("filename")
        if not isinstance(filename, str):
            raise RiverImageError("The image batch is missing a filename.")
        path = resolve_downloaded_image(root, source_batch_id, filename)
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise RiverImageError("A source image exceeds the supported size limit.")
        try:
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        except cv2.error as error:
            raise RiverImageError(f"Could not decode image {filename}.") from error
        if frame is None:
            raise RiverImageError(f"Could not read image {filename}. Download the batch again.")
        height, width = frame.shape[:2]
        if min(width, height) < 2 or max(width, height) > 4096:
            raise RiverImageError("Image dimensions are not supported for a test video.")
        if shape is not None and frame.shape != shape:
            raise RiverImageError(
                "Images have different dimensions. Use a batch from one camera view."
            )
        shape = frame.shape
        # MPEG-4 requires even dimensions; at most one bottom/right pixel is cropped.
        frames.append(frame[: height - height % 2, : width - width % 2])
        frame_map.append(
            {
                "filename": filename,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_url": image.get("source_url"),
                "captured_utc": image["captured_utc"],
                "requested_utc": image.get("requested_utc"),
                "playback_time_window_seconds": [
                    index * SECONDS_PER_IMAGE,
                    (index + 1) * SECONDS_PER_IMAGE,
                ],
            }
        )

    directory = root.resolve() / uuid4().hex
    directory.mkdir(exist_ok=False)
    target = directory / TEST_VIDEO_FILENAME
    try:
        height, width = frames[0].shape[:2]
        writer = cv2.VideoWriter(
            str(target), cv2.VideoWriter.fourcc(*"mp4v"), TEST_VIDEO_FPS, (width, height)
        )
        try:
            if not writer.isOpened():
                raise RiverImageError(
                    "The local MP4 encoder is unavailable. No test video was saved."
                )
            for frame in frames:
                for _ in range(TEST_VIDEO_FPS * SECONDS_PER_IMAGE):
                    writer.write(frame)
        finally:
            writer.release()
        capture = cv2.VideoCapture(str(target))
        try:
            expected = len(frames) * TEST_VIDEO_FPS * SECONDS_PER_IMAGE
            if not capture.isOpened() or int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) != expected:
                raise RiverImageError("The test video could not be encoded completely.")
        finally:
            capture.release()
        payload = {
            "success": True,
            "kind": "image_test_timelapse",
            "message": (
                "Test video created from saved images. Playback time is not real elapsed time."
            ),
            "batch_id": directory.name,
            "source_batch_id": source_batch_id,
            "output_directory": str(directory),
            "filename": TEST_VIDEO_FILENAME,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "camera_url": metadata.get("camera_url"),
            "fps": TEST_VIDEO_FPS,
            "seconds_per_image": SECONDS_PER_IMAGE,
            "duration_seconds": len(frames) * SECONDS_PER_IMAGE,
            "source_image_count": len(frames),
            "frames": frame_map,
            "skipped_slots": [image for image in images if image.get("status") != "downloaded"],
            "encoding": "mp4v",
            "pixel_handling": "No overlays or interpolation; crop bottom/right to even dimensions.",
        }
        (directory / "download.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        return payload
    except Exception as error:
        shutil.rmtree(directory)
        if isinstance(error, cv2.error):
            raise RiverImageError(
                "The local video encoder could not create the test video."
            ) from error
        raise

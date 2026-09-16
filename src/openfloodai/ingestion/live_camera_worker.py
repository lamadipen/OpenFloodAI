"""Subprocess entry point that grabs frames from a live stream into an MP4.

Run in a child process (by ``live_camera.capture_live_clip``) so a network
read that never returns can be killed from outside by
``subprocess.run(timeout=...)`` rather than hanging the caller.

Exit codes: 0 success, 2 could not open the stream, 3 no usable frames,
4 local encoder unavailable, 1 unexpected error.
"""

from __future__ import annotations

import math
import sys
import time
from typing import Any, Protocol

import cv2

DEFAULT_ASSUMED_FPS = 15.0
# The frame count for the requested duration at the reported (or assumed)
# source fps is the primary stop condition. The wall-clock cap is a safety
# net only, in case the feed stalls mid-read rather than serving buffered
# segments quickly.
WALL_CLOCK_SAFETY_MULTIPLIER = 6
WALL_CLOCK_SAFETY_MINIMUM_SECONDS = 10.0


class _FrameSource(Protocol):
    def read(self) -> tuple[bool, Any]: ...


def capture_frames(cap: _FrameSource, writer: Any, *, fps: float, duration_seconds: float) -> int:
    """Write frames from ``cap`` into ``writer`` until ``duration_seconds`` worth are captured.

    Kept separate from ``main`` so tests can pass in fakes instead of a real
    camera/encoder.
    """

    target_frames = max(1, round(duration_seconds * fps))
    wall_clock_cap = max(
        WALL_CLOCK_SAFETY_MINIMUM_SECONDS, duration_seconds * WALL_CLOCK_SAFETY_MULTIPLIER
    )
    started = time.monotonic()
    frames_written = 0
    first_shape = None
    while frames_written < target_frames:
        if time.monotonic() - started > wall_clock_cap:
            break
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        if first_shape is None:
            first_shape = frame.shape
        elif frame.shape != first_shape:
            # A mid-stream resolution change: keep the clip we already have.
            break
        writer.write(frame)
        frames_written += 1
    return frames_written


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        return 1
    stream_url, target_path, duration_text = argv
    try:
        duration_seconds = float(duration_text)
    except ValueError:
        return 1

    cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            return 2
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0 or math.isnan(fps):
            fps = DEFAULT_ASSUMED_FPS
        ok, first_frame = cap.read()
        if not ok or first_frame is None:
            return 3
        height, width = first_frame.shape[:2]
        writer = cv2.VideoWriter(target_path, cv2.VideoWriter.fourcc(*"mp4v"), fps, (width, height))
        try:
            if not writer.isOpened():
                return 4
            writer.write(first_frame)
            capture_frames(cap, writer, fps=fps, duration_seconds=duration_seconds)
        finally:
            writer.release()
        return 0
    finally:
        cap.release()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

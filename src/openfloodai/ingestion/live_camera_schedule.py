"""Persisted schedule for background live-camera clip captures.

The schedule itself is a small JSON file next to the other river-images
downloads. A single background thread (started once per server process by
the launcher) polls it and calls ``capture_live_clip`` when due. Reading and
running the schedule are kept as plain, testable functions
(``read_schedule``/``maybe_run_due_capture``); the thread class is a thin
sleep-loop around them.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from openfloodai.ingestion.live_camera import (
    DEFAULT_CLIP_SECONDS,
    DEFAULT_STREAM_URL,
    LiveCameraError,
    capture_live_clip,
    clamp_duration,
    validate_stream_url,
)

SCHEDULE_FILENAME = "live-camera-schedule.json"
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 24 * 60
DEFAULT_INTERVAL_MINUTES = 60
# How often the background thread wakes up to check whether a capture is due.
POLL_INTERVAL_SECONDS = 30

_DEFAULT_SCHEDULE: dict[str, Any] = {
    "enabled": False,
    "stream_url": DEFAULT_STREAM_URL,
    "interval_minutes": DEFAULT_INTERVAL_MINUTES,
    "duration_seconds": DEFAULT_CLIP_SECONDS,
    "last_run_utc": None,
    "last_result": None,
    "last_message": None,
    "last_batch_id": None,
}

_write_lock = threading.Lock()


def _schedule_path(root: Path) -> Path:
    return root / SCHEDULE_FILENAME


def read_schedule(root: Path) -> dict[str, Any]:
    """Return the saved schedule, or documented defaults if none was saved yet."""

    path = _schedule_path(root)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(_DEFAULT_SCHEDULE)
    if not isinstance(saved, dict):
        return dict(_DEFAULT_SCHEDULE)
    return dict(_DEFAULT_SCHEDULE) | saved


def write_schedule(root: Path, updates: dict[str, Any]) -> dict[str, Any]:
    """Validate and merge ``updates`` into the saved schedule; return the result."""

    with _write_lock:
        schedule = read_schedule(root)
        if "stream_url" in updates:
            schedule["stream_url"] = validate_stream_url(str(updates["stream_url"]))
        if "duration_seconds" in updates:
            schedule["duration_seconds"] = clamp_duration(updates["duration_seconds"])
        if "interval_minutes" in updates:
            try:
                interval = int(float(updates["interval_minutes"]))
            except (TypeError, ValueError) as error:
                raise LiveCameraError(
                    "Enter a whole number of minutes for the interval."
                ) from error
            if not MIN_INTERVAL_MINUTES <= interval <= MAX_INTERVAL_MINUTES:
                raise LiveCameraError(
                    f"Interval must be between {MIN_INTERVAL_MINUTES} and "
                    f"{MAX_INTERVAL_MINUTES} minutes."
                )
            schedule["interval_minutes"] = interval
        if "enabled" in updates:
            schedule["enabled"] = bool(updates["enabled"])
        root.mkdir(parents=True, exist_ok=True)
        _schedule_path(root).write_text(json.dumps(schedule, indent=2) + "\n", encoding="utf-8")
        return schedule


def _record_run(root: Path, *, result: str, message: str, batch_id: str | None) -> dict[str, Any]:
    with _write_lock:
        schedule = read_schedule(root)
        schedule["last_run_utc"] = datetime.now(UTC).isoformat()
        schedule["last_result"] = result
        schedule["last_message"] = message
        schedule["last_batch_id"] = batch_id
        root.mkdir(parents=True, exist_ok=True)
        _schedule_path(root).write_text(json.dumps(schedule, indent=2) + "\n", encoding="utf-8")
        return schedule


def maybe_run_due_capture(root: Path, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Run one capture if the schedule is enabled and due; else return None."""

    schedule = read_schedule(root)
    if not schedule.get("enabled"):
        return None
    now = now or datetime.now(UTC)
    last_run_text = schedule.get("last_run_utc")
    if isinstance(last_run_text, str):
        try:
            last_run = datetime.fromisoformat(last_run_text)
        except ValueError:
            last_run = None
    else:
        last_run = None
    interval = timedelta(minutes=schedule.get("interval_minutes", DEFAULT_INTERVAL_MINUTES))
    if last_run is not None and now - last_run < interval:
        return None
    try:
        payload = capture_live_clip(
            stream_url=str(schedule.get("stream_url", DEFAULT_STREAM_URL)),
            output_root=root,
            duration_seconds=schedule.get("duration_seconds", DEFAULT_CLIP_SECONDS),
        )
    except LiveCameraError as error:
        return _record_run(root, result="failed", message=str(error), batch_id=None)
    return _record_run(
        root, result="success", message=payload["message"], batch_id=payload["batch_id"]
    )


class LiveCameraScheduler(threading.Thread):
    """Background thread that calls ``maybe_run_due_capture`` on a poll interval."""

    def __init__(self, root: Path) -> None:
        super().__init__(daemon=True, name="live-camera-scheduler")
        self._root = root
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                maybe_run_due_capture(self._root)
            except OSError:
                pass
            self._stop_event.wait(POLL_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._stop_event.set()


_scheduler_lock = threading.Lock()
_running_scheduler: LiveCameraScheduler | None = None


def ensure_scheduler_running(root: Path) -> None:
    """Start the single background scheduler thread for this process, if not already running."""

    global _running_scheduler
    with _scheduler_lock:
        if _running_scheduler is not None and _running_scheduler.is_alive():
            return
        _running_scheduler = LiveCameraScheduler(root)
        _running_scheduler.start()

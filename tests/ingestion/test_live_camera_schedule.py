from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openfloodai.ingestion import live_camera
from openfloodai.ingestion import live_camera_schedule as schedule


def test_read_schedule_returns_defaults_when_unsaved(tmp_path: Path) -> None:
    result = schedule.read_schedule(tmp_path)
    assert result["enabled"] is False
    assert result["stream_url"] == live_camera.DEFAULT_STREAM_URL
    assert result["interval_minutes"] == schedule.DEFAULT_INTERVAL_MINUTES
    assert result["last_run_utc"] is None


def test_write_schedule_validates_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schedule, "validate_stream_url", lambda url: url.strip())
    result = schedule.write_schedule(
        tmp_path,
        {
            "enabled": True,
            "stream_url": "https://camera.example.com/s.m3u8",
            "interval_minutes": 15,
            "duration_seconds": 12,
        },
    )
    assert result["enabled"] is True
    assert result["interval_minutes"] == 15
    assert result["duration_seconds"] == 12
    reread = schedule.read_schedule(tmp_path)
    assert reread == result


def test_write_schedule_rejects_out_of_range_interval(tmp_path: Path) -> None:
    with pytest.raises(live_camera.LiveCameraError, match="Interval"):
        schedule.write_schedule(tmp_path, {"interval_minutes": 1})
    with pytest.raises(live_camera.LiveCameraError, match="Interval"):
        schedule.write_schedule(tmp_path, {"interval_minutes": 999999})


def test_write_schedule_partial_update_keeps_other_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schedule, "validate_stream_url", lambda url: url.strip())
    schedule.write_schedule(tmp_path, {"stream_url": "https://camera.example.com/s.m3u8"})
    result = schedule.write_schedule(tmp_path, {"enabled": True})
    assert result["enabled"] is True
    assert result["stream_url"] == "https://camera.example.com/s.m3u8"


def test_maybe_run_due_capture_is_noop_when_disabled(tmp_path: Path) -> None:
    assert schedule.maybe_run_due_capture(tmp_path) is None


def test_maybe_run_due_capture_runs_and_records_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schedule, "validate_stream_url", lambda url: url.strip())
    schedule.write_schedule(
        tmp_path, {"enabled": True, "stream_url": "https://camera.example.com/s.m3u8"}
    )

    def succeed(**kwargs: object) -> dict[str, object]:
        return {"success": True, "message": "Saved.", "batch_id": "abc123"}

    monkeypatch.setattr(schedule, "capture_live_clip", succeed)
    result = schedule.maybe_run_due_capture(tmp_path)
    assert result is not None
    assert result["last_result"] == "success"
    assert result["last_batch_id"] == "abc123"
    assert result["last_run_utc"]


def test_maybe_run_due_capture_records_failure_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schedule, "validate_stream_url", lambda url: url.strip())
    schedule.write_schedule(
        tmp_path, {"enabled": True, "stream_url": "https://camera.example.com/s.m3u8"}
    )

    def fail(**kwargs: object) -> dict[str, object]:
        raise live_camera.LiveCameraError("Camera offline.")

    monkeypatch.setattr(schedule, "capture_live_clip", fail)
    result = schedule.maybe_run_due_capture(tmp_path)
    assert result is not None
    assert result["last_result"] == "failed"
    assert result["last_message"] == "Camera offline."
    assert result["last_batch_id"] is None


def test_maybe_run_due_capture_waits_out_the_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schedule, "validate_stream_url", lambda url: url.strip())
    schedule.write_schedule(
        tmp_path,
        {
            "enabled": True,
            "stream_url": "https://camera.example.com/s.m3u8",
            "interval_minutes": 60,
        },
    )
    calls: list[int] = []

    def succeed(**kwargs: object) -> dict[str, object]:
        calls.append(1)
        return {"success": True, "message": "Saved.", "batch_id": "x"}

    monkeypatch.setattr(schedule, "capture_live_clip", succeed)
    now = datetime.now(UTC)
    first = schedule.maybe_run_due_capture(tmp_path, now=now)
    assert first is not None
    assert len(calls) == 1

    too_soon = schedule.maybe_run_due_capture(tmp_path, now=now + timedelta(minutes=10))
    assert too_soon is None
    assert len(calls) == 1

    due_again = schedule.maybe_run_due_capture(tmp_path, now=now + timedelta(minutes=61))
    assert due_again is not None
    assert len(calls) == 2


def test_scheduler_thread_runs_and_stops_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []

    def record(root: Path) -> None:
        calls.append(root)

    monkeypatch.setattr(schedule, "maybe_run_due_capture", record)
    monkeypatch.setattr(schedule, "POLL_INTERVAL_SECONDS", 0.01)
    thread = schedule.LiveCameraScheduler(tmp_path)
    thread.start()
    thread._stop_event.wait(0.2)
    thread.stop()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(calls) >= 1

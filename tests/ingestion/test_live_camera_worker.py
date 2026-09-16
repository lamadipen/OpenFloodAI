from __future__ import annotations

import time
from typing import Any

import pytest

from openfloodai.ingestion import live_camera_worker


class _FakeFrame:
    def __init__(self, shape: tuple[int, int, int]) -> None:
        self.shape = shape


class _FakeCap:
    def __init__(self, frames: list[_FakeFrame | None]) -> None:
        self._frames = list(frames)

    def read(self) -> tuple[bool, Any]:
        if not self._frames:
            return False, None
        frame = self._frames.pop(0)
        return frame is not None, frame


class _FakeWriter:
    def __init__(self) -> None:
        self.written: list[_FakeFrame] = []

    def write(self, frame: _FakeFrame) -> None:
        self.written.append(frame)


def test_capture_frames_stops_at_target_frame_count() -> None:
    shape = (10, 10, 3)
    cap = _FakeCap([_FakeFrame(shape) for _ in range(100)])
    writer = _FakeWriter()
    written = live_camera_worker.capture_frames(cap, writer, fps=10, duration_seconds=2)
    assert written == 20
    assert len(writer.written) == 20


def test_capture_frames_stops_early_when_stream_drops(monkeypatch: object) -> None:
    shape = (10, 10, 3)
    cap = _FakeCap([_FakeFrame(shape), _FakeFrame(shape), None])
    writer = _FakeWriter()
    written = live_camera_worker.capture_frames(cap, writer, fps=10, duration_seconds=5)
    assert written == 2


def test_capture_frames_stops_on_resolution_change() -> None:
    cap = _FakeCap([_FakeFrame((10, 10, 3)), _FakeFrame((20, 20, 3)), _FakeFrame((10, 10, 3))])
    writer = _FakeWriter()
    written = live_camera_worker.capture_frames(cap, writer, fps=10, duration_seconds=5)
    assert written == 1


def test_capture_frames_stops_at_target_even_when_more_frames_are_buffered() -> None:
    shape = (10, 10, 3)
    cap = _FakeCap([_FakeFrame(shape) for _ in range(10_000)])
    writer = _FakeWriter()
    written = live_camera_worker.capture_frames(cap, writer, fps=10, duration_seconds=1)
    assert written == 10


def test_capture_frames_stops_via_wall_clock_cap_when_reads_stall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shape = (10, 10, 3)
    # An impossibly high fps makes target_frames huge; the wall-clock cap
    # must still cut the loop short rather than waiting for target_frames.
    cap = _FakeCap([_FakeFrame(shape) for _ in range(1_000_000)])
    writer = _FakeWriter()
    clock = iter([0.0, 0.0, 1000.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    written = live_camera_worker.capture_frames(cap, writer, fps=100_000, duration_seconds=5)
    assert written == 1


def test_main_rejects_wrong_argument_count() -> None:
    assert live_camera_worker.main(["only-one-arg"]) == 1


def test_main_rejects_non_numeric_duration() -> None:
    args = ["https://example.com/s.m3u8", "/tmp/out.mp4", "not-a-number"]
    assert live_camera_worker.main(args) == 1

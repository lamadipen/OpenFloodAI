from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest

from openfloodai.ingestion import live_camera


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/stream.m3u8",
        "https://user@example.com/stream.m3u8",
        "https:///stream.m3u8",
        "not-a-url",
    ],
)
def test_validate_stream_url_rejects_bad_shape(url: str) -> None:
    with pytest.raises(live_camera.LiveCameraError):
        live_camera.validate_stream_url(url)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.1.2.3", "169.254.1.1", "::1", "fe80::1"],
)
def test_validate_stream_url_rejects_local_and_private_addresses(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(None, None, None, None, (address, 0))],
    )
    with pytest.raises(live_camera.LiveCameraError, match="local or private"):
        live_camera.validate_stream_url("https://camera.example.com/stream.m3u8")


def test_validate_stream_url_accepts_public_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    url = live_camera.validate_stream_url(" https://camera.example.com/stream.m3u8 ")
    assert url == "https://camera.example.com/stream.m3u8"


def test_validate_stream_url_rejects_unresolvable_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(host: str, port: object) -> list[object]:
        raise OSError("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(live_camera.LiveCameraError, match="resolve"):
        live_camera.validate_stream_url("https://nowhere.example.com/stream.m3u8")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, 5),
        ("12", 12),
        (1, live_camera.MIN_CLIP_SECONDS),
        (999, live_camera.MAX_CLIP_SECONDS),
        ("", live_camera.DEFAULT_CLIP_SECONDS),
        (None, live_camera.DEFAULT_CLIP_SECONDS),
    ],
)
def test_clamp_duration(value: object, expected: int) -> None:
    assert live_camera.clamp_duration(value) == expected


def _resolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(None, None, None, None, ("93.184.216.34", 0))],
    )


def test_capture_live_clip_saves_batch_on_worker_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolvable(monkeypatch)

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        target = Path(args[4])
        target.write_bytes(b"fake mp4 bytes")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    payload = live_camera.capture_live_clip(
        stream_url="https://camera.example.com/stream.m3u8",
        output_root=tmp_path,
        duration_seconds=6,
    )
    assert payload["success"] is True
    assert payload["kind"] == "live_camera_clip"
    directory = Path(payload["output_directory"])
    assert (directory / live_camera.CLIP_FILENAME).read_bytes() == b"fake mp4 bytes"
    metadata = json.loads((directory / "download.json").read_text())
    assert metadata == payload
    assert payload["requested_duration_seconds"] == 6


@pytest.mark.parametrize(
    ("returncode", "expected_snippet"),
    [(2, "offline"), (3, "no usable frames"), (4, "encoder"), (9, "Could not capture")],
)
def test_capture_live_clip_raises_on_worker_failure_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int, expected_snippet: str
) -> None:
    _resolvable(monkeypatch)

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, returncode)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(live_camera.LiveCameraError, match=expected_snippet):
        live_camera.capture_live_clip(
            stream_url="https://camera.example.com/stream.m3u8", output_root=tmp_path
        )
    assert list(tmp_path.iterdir()) == []


def test_capture_live_clip_raises_on_timeout_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolvable(monkeypatch)

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        timeout = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(args, timeout if isinstance(timeout, (int, float)) else 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(live_camera.LiveCameraError, match="did not respond in time"):
        live_camera.capture_live_clip(
            stream_url="https://camera.example.com/stream.m3u8", output_root=tmp_path
        )
    assert list(tmp_path.iterdir()) == []


def test_capture_live_clip_rejects_oversized_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolvable(monkeypatch)
    monkeypatch.setattr(live_camera, "MAX_CLIP_BYTES", 4)

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        Path(args[4]).write_bytes(b"too many bytes")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(live_camera.LiveCameraError, match="size limit"):
        live_camera.capture_live_clip(
            stream_url="https://camera.example.com/stream.m3u8", output_root=tmp_path
        )
    assert list(tmp_path.iterdir()) == []

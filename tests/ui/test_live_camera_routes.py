from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_home_server import get_json, post_json, serve_home_ui

from openfloodai.ingestion.live_camera import LiveCameraError
from openfloodai.ui import home_server


def test_live_camera_schedule_defaults_when_unsaved(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path / "sites") as base:
        payload = get_json(base + "/api/live-camera-schedule")
    assert payload["enabled"] is False
    assert payload["last_run_utc"] is None


def test_download_live_camera_clip_route_saves_and_serves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_capture(
        *, stream_url: str, output_root: Path, duration_seconds: object
    ) -> dict[str, object]:
        assert output_root == tmp_path / "river-images"
        batch = output_root / ("c" * 32)
        batch.mkdir(parents=True)
        (batch / "live_camera_clip.mp4").write_bytes(b"fake clip bytes")
        payload = {
            "success": True,
            "kind": "live_camera_clip",
            "message": "Live camera clip saved.",
            "stream_url": stream_url,
            "batch_id": batch.name,
            "output_directory": str(batch),
            "filename": "live_camera_clip.mp4",
        }
        (batch / "download.json").write_text('{"success": true, "kind": "live_camera_clip"}')
        return payload

    monkeypatch.setattr(home_server, "capture_live_clip", fake_capture)
    with serve_home_ui(tmp_path / "sites") as base:
        result = post_json(
            base + "/api/download-live-camera-clip",
            {"stream_url": "https://camera.example.com/s.m3u8", "duration_seconds": 8},
        )
        assert result["success"] is True
        assert result["batch_id"] == "c" * 32
        assert get_json(base + "/api/sites")["sites"] == []


def test_download_live_camera_clip_route_reports_camera_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*, stream_url: str, output_root: Path, duration_seconds: object) -> dict[str, object]:
        raise LiveCameraError("The live camera is offline.")

    monkeypatch.setattr(home_server, "capture_live_clip", fail)
    with serve_home_ui(tmp_path / "sites") as base:
        result = post_json(
            base + "/api/download-live-camera-clip",
            {"stream_url": "https://camera.example.com/s.m3u8"},
        )
    assert result["message"] == "The live camera is offline."


def test_download_live_camera_clip_route_rejects_cross_origin(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path / "sites") as base:
        request = Request(
            base + "/api/download-live-camera-clip",
            data=b"{}",
            headers={"Content-Type": "application/json", "Origin": "https://other.example"},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)
    assert error.value.code == 403


def test_set_live_camera_schedule_route_persists_and_get_reflects_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "openfloodai.ingestion.live_camera_schedule.validate_stream_url", lambda url: url.strip()
    )
    with serve_home_ui(tmp_path / "sites") as base:
        result = post_json(
            base + "/api/set-live-camera-schedule",
            {
                "enabled": True,
                "stream_url": "https://camera.example.com/s.m3u8",
                "interval_minutes": 30,
                "duration_seconds": 10,
            },
        )
        assert result["enabled"] is True
        assert result["interval_minutes"] == 30
        again = get_json(base + "/api/live-camera-schedule")
        assert again == result


def test_set_live_camera_schedule_route_rejects_invalid_interval(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path / "sites") as base:
        result = post_json(base + "/api/set-live-camera-schedule", {"interval_minutes": 1})
    assert "Interval" in result["message"]


def test_set_live_camera_schedule_route_rejects_non_json(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path / "sites") as base:
        request = Request(
            base + "/api/set-live-camera-schedule",
            data=b"not json",
            headers={"Content-Type": "text/plain"},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)
    assert error.value.code == 400

"""Tests for human label creation CLI and Home UI endpoint."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from openfloodai.review import load_human_label_records
from openfloodai.ui.home_server import OpenFloodAIHomeHandler


def test_create_human_label_cli_creates_record(tmp_path: Path) -> None:
    site_dir = tmp_path / "cli-site"
    site_dir.mkdir()

    cmd = [
        sys.executable,
        "scripts/create_human_label.py",
        "--site-dir",
        str(site_dir),
        "--video-id",
        "rising-001",
        "--start",
        "30",
        "--end",
        "60",
        "--label",
        "water_rising",
        "--confidence",
        "medium",
        "--note",
        "water appears higher near the bridge pillar",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "Success: Added label record" in result.stdout

    labels_file = site_dir / "labels" / "labels.jsonl"
    assert labels_file.exists()
    records = load_human_label_records(labels_file)
    assert len(records) == 1
    assert records[0]["video_id"] == "rising-001"
    assert records[0]["time_window_seconds"] == [30, 60]
    assert records[0]["human_label"] == "water_rising"


def test_add_human_label_cli_alias_works(tmp_path: Path) -> None:
    site_dir = tmp_path / "alias-site"
    site_dir.mkdir()

    cmd = [
        sys.executable,
        "scripts/add_human_label.py",
        "--site-dir",
        str(site_dir),
        "--video-id",
        "test-001",
        "--start-second",
        "0",
        "--end-second",
        "20",
        "--human-label",
        "cannot_judge",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "Success: Added label record" in result.stdout

    records = load_human_label_records(site_dir / "labels" / "labels.jsonl")
    assert len(records) == 1
    assert records[0]["human_label"] == "cannot_judge"


def test_create_human_label_cli_accepts_custom_label(tmp_path: Path) -> None:
    site_dir = tmp_path / "custom-label-site"
    site_dir.mkdir()

    cmd = [
        sys.executable,
        "scripts/create_human_label.py",
        "--site-dir",
        str(site_dir),
        "--video-id",
        "test-001",
        "--start",
        "0",
        "--end",
        "20",
        "--label",
        "bridge_pillar_covered",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0

    records = load_human_label_records(site_dir / "labels" / "labels.jsonl")
    assert records[0]["human_label"] == "bridge_pillar_covered"


def test_create_human_label_cli_rejects_duplicate_without_overwrite(tmp_path: Path) -> None:
    site_dir = tmp_path / "dup-site"
    site_dir.mkdir()

    base_cmd = [
        sys.executable,
        "scripts/create_human_label.py",
        "--site-dir",
        str(site_dir),
        "--video-id",
        "v1",
        "--start",
        "10",
        "--end",
        "20",
        "--label",
        "no_clear_change",
    ]
    res1 = subprocess.run(base_cmd, capture_output=True, text=True, check=False)
    assert res1.returncode == 0

    # Second run without --overwrite
    res2 = subprocess.run(base_cmd, capture_output=True, text=True, check=False)
    assert res2.returncode == 1
    assert "already exists" in res2.stderr
    assert "overwrite=True" in res2.stderr

    # Third run with --overwrite
    overwrite_cmd = base_cmd + ["--overwrite", "--note", "Replaced note"]
    res3 = subprocess.run(overwrite_cmd, capture_output=True, text=True, check=False)
    assert res3.returncode == 0
    assert "Replaced label record" in res3.stdout

    records = load_human_label_records(site_dir / "labels" / "labels.jsonl")
    assert len(records) == 1
    assert records[0]["note"] == "Replaced note"


def test_home_ui_add_label_api_endpoint(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    site_dir = sites_dir / "api-site"
    site_dir.mkdir()

    ui_path = Path("tools/openfloodai-home-ui.html")

    class TestHandler(OpenFloodAIHomeHandler):
        pass

    TestHandler.sites_dir = sites_dir
    TestHandler.ui_path = ui_path

    server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
    host = "127.0.0.1"
    port = int(server.server_port)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        url = f"http://{host}:{port}/api/add-label"
        payload = {
            "folder_name": "api-site",
            "video_id": "rising-001",
            "start_second": 30,
            "end_second": 60,
            "human_label": "water_rising",
            "confidence": "medium",
            "note": "water appears higher near the bridge pillar",
        }
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200
            assert data["success"] is True
            assert "Added label record" in data["message"]

        labels_path = site_dir / "labels" / "labels.jsonl"
        assert labels_path.exists()
        records = load_human_label_records(labels_path)
        assert len(records) == 1
        assert records[0]["human_label"] == "water_rising"

        # Check /api/sites includes label options
        sites_req = Request(f"http://{host}:{port}/api/sites")
        with urlopen(sites_req) as resp:
            sites_data = json.loads(resp.read().decode("utf-8"))
            assert "human_label_options" in sites_data
            assert "water_rising" in sites_data["human_label_options"]
            assert "confidence_options" in sites_data
            assert "water_rising" in sites_data["sites"][0]["human_label_options"]

        # Test error rejection on invalid time window
        bad_payload = {
            "folder_name": "api-site",
            "video_id": "rising-001",
            "start_second": 60,
            "end_second": 30,
            "human_label": "water_rising",
        }
        bad_req = Request(
            url,
            data=json.dumps(bad_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(bad_req)
        assert exc_info.value.code == 400
        err_data = json.loads(exc_info.value.read().decode("utf-8"))
        assert err_data["success"] is False
        assert "end must be greater than start" in err_data["message"]
    finally:
        server.shutdown()
        server.server_close()

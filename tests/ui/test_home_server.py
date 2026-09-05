from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen

from openfloodai.ui.home_server import OpenFloodAIHomeHandler

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_PATH = REPO_ROOT / "tools" / "openfloodai-home-ui.html"


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_site(site_dir: Path) -> Path:
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    (site_dir / "outputs").mkdir(parents=True)
    write_json(site_dir / "configs" / "site-config.json", {"site_id": site_dir.name})
    (site_dir / "inputs" / "videos" / "river-001.mp4").write_bytes(b"not-real-video")
    (site_dir / "labels" / "labels.jsonl").write_text(
        '{"video_id":"river-001","time_window_seconds":[0,30],"human_label":"cannot_judge"}\n',
        encoding="utf-8",
    )
    (site_dir / "manifest.jsonl").write_text(
        (
            '{"video_id":"river-001","filename":"river-001.mp4","purpose":"practice",'
            '"split":"practice","approved_for_repo":false,"has_human_label":true,'
            '"notes":"Synthetic test metadata."}\n'
        ),
        encoding="utf-8",
    )
    return site_dir


@contextmanager
def serve_home_ui(sites_dir: Path, ui_path: Path = UI_PATH) -> Iterator[str]:
    """Run the real Home UI handler on a loopback port and yield its base URL."""

    OpenFloodAIHomeHandler.sites_dir = sites_dir
    OpenFloodAIHomeHandler.ui_path = ui_path
    server = ThreadingHTTPServer(("127.0.0.1", 0), OpenFloodAIHomeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get_text(url: str) -> tuple[int, str, str]:
    with urlopen(url, timeout=5) as response:
        return (
            int(response.status),
            str(response.headers.get("Content-Type", "")),
            response.read().decode("utf-8"),
        )


def get_json(url: str) -> dict[str, Any]:
    _, _, body = get_text(url)
    payload: dict[str, Any] = json.loads(body)
    return payload


def test_home_ui_page_loads_with_heading(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        status, content_type, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert status == 200
    assert "text/html" in content_type
    assert "<title>OpenFloodAI Home UI</title>" in body
    assert "<h1>OpenFloodAI Home UI</h1>" in body


def test_home_ui_page_is_served_at_root(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        status, _, body = get_text(f"{base_url}/")

    assert status == 200
    assert "<h1>OpenFloodAI Home UI</h1>" in body


def test_home_ui_page_has_safety_note_container(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert 'id="safetyNote"' in body


def test_sites_api_reports_ready_site(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    make_site(sites_dir / "example-site")

    with serve_home_ui(sites_dir) as base_url:
        payload = get_json(f"{base_url}/api/sites")

    assert payload["sites_dir"] == str(sites_dir)
    assert len(payload["sites"]) == 1

    site = payload["sites"][0]
    assert site["site_name"] == "example-site"
    assert site["config_found"] is True
    assert site["video_count"] == 1
    assert site["labels_found"] is True
    assert site["manifest_found"] is True
    assert site["latest_report_path"] is None


def test_sites_api_includes_status_fields_the_ui_renders(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    make_site(sites_dir / "example-site")

    with serve_home_ui(sites_dir) as base_url:
        site = get_json(f"{base_url}/api/sites")["sites"][0]

    for field in (
        "config_found",
        "video_count",
        "labels_found",
        "manifest_found",
        "report_count",
        "latest_report_path",
        "machine_review_explanation",
        "human_comparison_explanation",
    ):
        assert field in site, f"Home UI needs {field} to render site status"


def test_sites_api_includes_safety_note(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        payload = get_json(f"{base_url}/api/sites")

    safety_note = str(payload["safety_note"])
    assert "does not upload videos" in safety_note
    assert "publish warnings" in safety_note


def test_sites_api_handles_empty_sites_directory(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        payload = get_json(f"{base_url}/api/sites")

    assert payload["sites"] == []


def test_unknown_path_returns_404(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        try:
            get_text(f"{base_url}/not-a-real-page")
        except HTTPError as error:
            assert error.code == 404
        else:  # pragma: no cover - only reached if the handler regresses
            raise AssertionError("Expected 404 for an unknown path")

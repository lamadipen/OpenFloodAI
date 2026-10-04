"""Hosted SAM HTTP routes: opt-in, masked credentials, explicit start (no network)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import cv2
import numpy as np
import pytest

from openfloodai.evidence.hosted_sam_credentials import ENV_VAR, HostedSamCredentials
from openfloodai.ui.home_server import OpenFloodAIHomeHandler

KEY = "sk-test-0123456789abcdef"
SEQUENCE_ID = "usgs-camera-demo-2026-09-01-2026-09-01-all"
IMAGE_A = "cam___2026-09-01T00-00-00Z.jpg"
IMAGE_B = "cam___2026-09-01T01-00-00Z.jpg"
REGION = {"x": 10, "y": 20, "width": 40, "height": 50}


def reply(text: str) -> str:
    lane = {"item_id": "m1", "output_index": 0, "content_index": 0}
    events = [
        {"type": "response.output_text.delta", **lane, "delta": text},
        {"type": "response.output_text.done", **lane, "text": text},
        {"type": "response.completed"},
    ]
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


def mask_payload(width: int, height: int) -> str:
    from meta_sam_parser._mask_codec import _encode_raster

    return str(_encode_raster([1] * (width * height), width, height))


def detection_text(
    x1: int = 1, y1: int = 2, x2: int = 20, y2: int = 25, w: int = 40, h: int = 30
) -> str:
    """One object. Box corners are inclusive; the mask is the size of the box."""

    mask_w, mask_h = x2 - x1 + 1, y2 - y1 + 1
    box = f"x1={x1};y1={y1};x2={x2};y2={y2};w={w};h={h};c=0.9"
    return (
        f"<0f>0<|box;{box}|>"
        f"<|mask;x=0;y=0;data={mask_h},{mask_w},{mask_payload(mask_w, mask_h)}|>\n"
    )


def ones_decoder(height: int, width: int, encoding: str, payload: str) -> Any:
    return np.ones((height, width), dtype=np.uint8)


class FakeTransport:
    def __init__(self, *responses: tuple[int, str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes, timeout: float):  # type: ignore[no-untyped-def]
        self.calls.append({"headers": headers, "body": json.loads(body)})
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


def make_site(tmp_path: Path, *, region: dict[str, object] | None = None) -> Path:
    site = tmp_path / "site"
    (site / "configs").mkdir(parents=True)
    config: dict[str, object] = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo",
        "input_type": "local_video",
        "reference_region": region or REGION,
        "normal_waterline_guides": [],
    }
    (site / "configs" / "site.json").write_text(json.dumps(config), encoding="utf-8")
    sequence = site / "inputs" / "image-sequences" / SEQUENCE_ID
    (sequence / "images").mkdir(parents=True)
    rows = []
    for name, value in ((IMAGE_A, 40), (IMAGE_B, 80)):
        frame = np.full((60, 100, 3), value, dtype=np.uint8)
        assert cv2.imwrite(str(sequence / "images" / name), frame)
        rows.append(
            {
                "filename": name,
                "captured_at_utc": "2026-09-01T00:00:00+00:00",
                "download_status": "downloaded",
            }
        )
    (sequence / "sequence-manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    return site


UI_PATH = Path(__file__).resolve().parents[2] / "tools" / "openfloodai-home-ui.html"


@contextmanager
def serve_home_ui(sites_dir: Path) -> Iterator[str]:
    OpenFloodAIHomeHandler.sites_dir = sites_dir
    OpenFloodAIHomeHandler.ui_path = UI_PATH
    server = ThreadingHTTPServer(("127.0.0.1", 0), OpenFloodAIHomeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def fresh_handler_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(OpenFloodAIHomeHandler, "hosted_sam_credentials", HostedSamCredentials())
    monkeypatch.setattr(OpenFloodAIHomeHandler, "hosted_sam_decoder", None)
    monkeypatch.setattr(
        OpenFloodAIHomeHandler,
        "hosted_sam_transport",
        staticmethod(FakeTransport((500, "{}"))),
    )
    yield


def post(url: str, data: dict[str, object]) -> tuple[int, dict[str, Any]]:
    request = Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return int(error.code), json.loads(error.read().decode("utf-8"))


def get(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=5) as response:
        return dict(json.loads(response.read().decode("utf-8")))


def enable_globally(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    reference.mkdir(exist_ok=True)
    (reference / "evidence-adapter-settings.json").write_text(
        json.dumps({"adapters": {"hosted_sam_v1": True}}), encoding="utf-8"
    )


def setup(tmp_path: Path) -> tuple[Path, Path]:
    sites = tmp_path / "sites"
    sites.mkdir()
    site = make_site(tmp_path)
    site.rename(sites / "demo")
    return sites, sites / "demo"


def test_fresh_install_has_hosted_sam_off_and_unconfigured(tmp_path: Path) -> None:
    sites, _ = setup(tmp_path)
    with serve_home_ui(sites) as base:
        status = get(f"{base}/api/hosted-sam/status")

    assert status["enabled"] is False
    assert status["credential"]["configured"] is False
    assert status["decoder_available"] is False
    assert status["provider"]["signup_url"] == "https://dev.meta.ai/models/sam-3-1"
    assert (
        "retained" in status["provider"]["retention_note"]
        or "kept" in status["provider"]["retention_note"]
    )
    assert status["limits"]["automatic_retries"] == 0


def test_credential_is_masked_replaceable_and_removable_and_never_echoed(tmp_path: Path) -> None:
    sites, _ = setup(tmp_path)
    with serve_home_ui(sites) as base:
        code, saved = post(f"{base}/api/hosted-sam/credential", {"api_key": KEY})
        status = get(f"{base}/api/hosted-sam/status")
        replaced = post(
            f"{base}/api/hosted-sam/credential", {"api_key": "sk-test-replacement-9999"}
        )
        removed = post(f"{base}/api/hosted-sam/credential", {"remove": True})
        bad_code, bad = post(f"{base}/api/hosted-sam/credential", {"api_key": "x"})

    assert code == 200 and saved["credential"]["configured"] is True
    for payload in (saved, status, replaced[1], removed[1]):
        assert KEY not in json.dumps(payload)
        assert "replacement-9999" not in json.dumps(payload)
    assert status["credential"]["masked"].endswith(KEY[-4:])
    assert removed[1]["credential"]["configured"] is False
    assert bad_code == 400 and bad["success"] is False


def test_nothing_is_sent_until_enabled_configured_acknowledged_and_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sites, _ = setup(tmp_path)
    transport = FakeTransport((200, reply(detection_text())))
    monkeypatch.setattr(OpenFloodAIHomeHandler, "hosted_sam_transport", staticmethod(transport))
    monkeypatch.setattr(OpenFloodAIHomeHandler, "hosted_sam_decoder", ones_decoder)
    body = {
        "folder_name": "demo",
        "sequence_id": SEQUENCE_ID,
        "filenames": [IMAGE_A],
        "concepts": ["water"],
        "confirmed_request_count": 1,
    }
    with serve_home_ui(sites) as base:
        disabled = post(f"{base}/api/hosted-sam/run", body)
        enable_globally(tmp_path)
        no_key = post(f"{base}/api/hosted-sam/run", body)
        post(f"{base}/api/hosted-sam/credential", {"api_key": KEY})
        no_ack = post(f"{base}/api/hosted-sam/run", body)
        refused_ack = post(f"{base}/api/hosted-sam/acknowledge", {"acknowledged": False})
        post(f"{base}/api/hosted-sam/acknowledge", {"acknowledged": True})
        preflight = post(f"{base}/api/hosted-sam/preflight", body)
        wrong_count = post(f"{base}/api/hosted-sam/run", {**body, "confirmed_request_count": 5})
        assert transport.calls == []
        started = post(f"{base}/api/hosted-sam/run", body)
        runs = get(f"{base}/api/hosted-sam/runs?folder_name=demo&sequence_id={SEQUENCE_ID}")
        run_id = started[1]["run"]["run_id"]
        result_id = started[1]["run"]["results"][0]["result_id"]
        review = post(
            f"{base}/api/hosted-sam/review",
            {
                "folder_name": "demo",
                "run_id": run_id,
                "result_id": result_id,
                "decision": "accepted",
            },
        )
        detail = get(f"{base}/api/hosted-sam/run?folder_name=demo&run_id={run_id}")
        with urlopen(
            f"{base}/api/hosted-sam/overlay?folder_name=demo&run_id={run_id}&result_id={result_id}",
            timeout=5,
        ) as overlay:
            overlay_type = overlay.headers["Content-Type"]
            overlay_bytes = overlay.read()

    assert (disabled[0], disabled[1]["code"]) == (409, "plugin_disabled")
    assert no_key[1]["code"] == "not_configured"
    assert no_ack[1]["code"] == "acknowledgement_required"
    assert refused_ack[0] == 400
    assert preflight[1]["plan"]["request_count"] == 1
    assert wrong_count[1]["code"] == "confirm_count_mismatch"
    assert started[0] == 200 and len(transport.calls) == 1
    assert KEY not in json.dumps(started[1]) and KEY not in json.dumps(runs)
    assert len(runs["runs"]) == 1
    assert review[1]["review"]["decision"] == "accepted"
    assert detail["results"][0]["review_status"] == "accepted"
    assert overlay_type == "image/png" and overlay_bytes.startswith(b"\x89PNG")


def test_without_a_decoder_a_run_is_refused_before_any_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sites, _ = setup(tmp_path)
    transport = FakeTransport((200, reply(detection_text())))
    monkeypatch.setattr(OpenFloodAIHomeHandler, "hosted_sam_transport", staticmethod(transport))
    enable_globally(tmp_path)
    with serve_home_ui(sites) as base:
        post(f"{base}/api/hosted-sam/credential", {"api_key": KEY})
        post(f"{base}/api/hosted-sam/acknowledge", {"acknowledged": True})
        refused = post(
            f"{base}/api/hosted-sam/run",
            {
                "folder_name": "demo",
                "sequence_id": SEQUENCE_ID,
                "filenames": [IMAGE_A],
                "concepts": ["water"],
                "confirmed_request_count": 1,
            },
        )

    assert refused[1]["code"] == "decoder_unavailable"
    assert transport.calls == []


def test_a_cross_origin_post_cannot_start_anything(tmp_path: Path) -> None:
    sites, _ = setup(tmp_path)
    with serve_home_ui(sites) as base:
        request = Request(
            f"{base}/api/hosted-sam/credential",
            data=json.dumps({"api_key": KEY}).encode(),
            headers={"Content-Type": "application/json", "Origin": "http://evil.example"},
            method="POST",
        )
        with pytest.raises(HTTPError) as raised:
            urlopen(request, timeout=5)
        status = get(f"{base}/api/hosted-sam/status")

    assert raised.value.code == 403
    assert status["credential"]["configured"] is False

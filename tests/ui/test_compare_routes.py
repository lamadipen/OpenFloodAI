"""Compare routes: read-only, ordered, and one explicit save (Issue #223)."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "water_change"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "curation"))

from water_helpers import (  # noqa: E402
    add_water_mask,
    tree_fingerprint,
    two_image_run,
    water,
)

from openfloodai.ui.home_server import OpenFloodAIHomeHandler  # noqa: E402

UI_PATH = Path(__file__).resolve().parents[2] / "tools" / "openfloodai-home-ui.html"
RUN_A = "20261002T100000Z-aaaaaaaa"
RUN_B = "20261003T100000Z-bbbbbbbb"


@contextmanager
def serve(sites_dir: Path) -> Iterator[str]:
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


def post(url: str, data: dict[str, Any], headers: dict[str, str] | None = None) -> tuple[int, Any]:
    request = Request(
        url,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return int(response.status), json.loads(response.read().decode())
    except HTTPError as error:
        return int(error.code), json.loads(error.read().decode())


def fetch(url: str) -> tuple[int, str, bytes]:
    try:
        with urlopen(url, timeout=10) as response:
            return int(response.status), response.headers["Content-Type"], response.read()
    except HTTPError as error:
        return int(error.code), error.headers.get("Content-Type", ""), error.read()


@pytest.fixture
def env(tmp_path: Path) -> dict[str, Any]:
    fixture = two_image_run(tmp_path)
    sequence = fixture.site_dir / "inputs" / "image-sequences" / fixture.sequence_id
    rows = [
        json.loads(line)
        for line in (sequence / "sequence-manifest.jsonl").read_text().splitlines()
        if line
    ]
    (sequence / "download-summary.json").write_text(
        json.dumps({"sequence_id": fixture.sequence_id, "records": rows}), encoding="utf-8"
    )
    add_water_mask(fixture, 0, water(10), run_id=RUN_A)
    add_water_mask(fixture, 1, water(18), run_id=RUN_B)
    return {"fx": fixture, "sites": fixture.sites_dir}


def body(env: dict[str, Any], **extra: Any) -> dict[str, Any]:
    fx = env["fx"]
    return {
        "folder_name": fx.folder_name,
        "a": {"run_id": fx.run_id, "filename": fx.filenames[1]},
        "b": {"run_id": fx.run_id, "filename": fx.filenames[0]},
        "framing_confirmed": True,
        **extra,
    }


def test_measure_orders_the_pair_and_writes_nothing(env: dict[str, Any]) -> None:
    before = tree_fingerprint(env["fx"].site_dir)
    with serve(env["sites"]) as base:
        code, out = post(f"{base}/api/compare/measure", body(env))
    assert code == 200 and out["success"] is True and out["available"] is True
    assert out["earlier"]["filename"] == env["fx"].filenames[0]  # chosen second, still earlier
    assert out["evidence"]["value"] == pytest.approx(40.0) and out["saved"] is None
    assert tree_fingerprint(env["fx"].site_dir) == before


def test_save_is_a_separate_explicit_call_that_keeps_the_exact_references(
    env: dict[str, Any],
) -> None:
    with serve(env["sites"]) as base:
        code, saved = post(f"{base}/api/compare/save", body(env))
        again = post(f"{base}/api/compare/save", body(env))
    assert code == 200 and saved["saved"]["reused"] is False
    assert (
        again[1]["saved"]["reused"] is True
        and again[1]["saved"]["pair_key"] == saved["saved"]["pair_key"]
    )
    record = json.loads(Path(saved["saved"]["path"]).read_text())
    assert record["earlier"]["image_sha256"] and record["later"]["mask_sha256s"]
    assert len(list((env["fx"].site_dir / "outputs" / "water-change-pairs").iterdir())) == 1


def test_candidates_thumbnail_and_overlay_are_served(env: dict[str, Any]) -> None:
    fx = env["fx"]
    with serve(env["sites"]) as base:
        listing = json.loads(
            fetch(f"{base}/api/compare/candidates?folder_name={fx.folder_name}&run_id={fx.run_id}")[
                2
            ]
        )
        thumb = fetch(
            f"{base}/api/compare/thumbnail?folder_name={fx.folder_name}"
            f"&sequence_id={fx.sequence_id}&filename={fx.filenames[0]}"
        )
        overlay = fetch(
            f"{base}/api/compare/overlay?folder_name={fx.folder_name}"
            f"&a_run={fx.run_id}&a_file={fx.filenames[0]}&b_run={fx.run_id}&b_file={fx.filenames[1]}"
        )
        missing = fetch(
            f"{base}/api/compare/overlay?folder_name={fx.folder_name}"
            f"&a_run={fx.run_id}&a_file={fx.filenames[0]}&b_run={fx.run_id}&b_file=nope"
        )
    assert len(listing["images"]) == 2 and listing["images"][0]["mask_state"] == "accepted"
    assert thumb[0] == 200 and thumb[1] == "image/jpeg" and thumb[2].startswith(b"\xff\xd8")
    assert overlay[0] == 200 and overlay[1] == "image/png" and overlay[2].startswith(b"\x89PNG")
    assert missing[0] in (404, 409)


def test_unavailable_pairs_say_why_and_a_bad_request_is_refused(env: dict[str, Any]) -> None:
    with serve(env["sites"]) as base:
        unconfirmed = post(f"{base}/api/compare/measure", body(env, framing_confirmed=False))
        string_true = post(f"{base}/api/compare/measure", body(env, framing_confirmed="true"))
        missing = post(f"{base}/api/compare/measure", {"folder_name": env["fx"].folder_name})
        wrong_site = post(f"{base}/api/compare/measure", body(env, folder_name="nope"))
        cross_origin = post(
            f"{base}/api/compare/measure", body(env), headers={"Origin": "https://evil.example"}
        )
    assert unconfirmed[1]["available"] is False
    assert "FRAMING_NOT_CONFIRMED" in unconfirmed[1]["evidence"]["reason_codes"]
    assert string_true[1]["framing_confirmed"] is False  # only a real true counts
    assert missing[0] == 400 and wrong_site[0] == 400
    assert cross_origin[0] in (400, 403)

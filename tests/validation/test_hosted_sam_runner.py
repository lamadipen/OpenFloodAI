"""Hosted SAM runs: gates, persistence, caching, review, and key safety (no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from openfloodai.evidence.hosted_sam_credentials import ENV_VAR, HostedSamCredentials
from openfloodai.validation import hosted_sam_runner as runner

KEY = "sk-test-0123456789abcdef"
SEQUENCE_ID = "usgs-camera-demo-2026-09-01-2026-09-01-all"
IMAGE_A = "cam___2026-09-01T00-00-00Z.jpg"
IMAGE_B = "cam___2026-09-01T01-00-00Z.jpg"
REGION = {"x": 10, "y": 20, "width": 40, "height": 50}


def reply(text: str) -> str:
    return "data: " + json.dumps({"type": "response.output_text.delta", "delta": text}) + "\n\n"


def detection_text(w: int = 40, h: int = 30) -> str:
    return f"<0f>0<|box;x1=1;y1=2;x2=20;y2=25;w={w};h={h}|><|mask;x=3;y=4;data=5,6,!AB|>"


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


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> HostedSamCredentials:
    monkeypatch.delenv(ENV_VAR, raising=False)
    holder = HostedSamCredentials()
    holder.set_session_key(KEY)
    holder.acknowledge_upload()
    return holder


def go(
    site: Path,
    credentials: HostedSamCredentials,
    transport: FakeTransport,
    *,
    names: tuple[str, ...] = (IMAGE_A,),
    concepts: tuple[str, ...] = ("water",),
    count: object | None = None,
    enabled: bool = True,
    decoder: Any = ones_decoder,
) -> dict[str, Any]:
    plan = runner.plan_segmentation(site, SEQUENCE_ID, names, concepts)
    return runner.run_segmentation(
        site,
        SEQUENCE_ID,
        names,
        concepts,
        plugin_enabled=enabled,
        credentials=credentials,
        confirmed_request_count=plan.request_count if count is None else count,
        decoder=decoder,
        transport=transport,
    )


def test_preflight_counts_one_request_per_image_and_concept(tmp_path: Path) -> None:
    site = make_site(tmp_path)

    plan = runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_A, IMAGE_B], ["water", "riverbank"])

    assert plan.request_count == 4 and plan.total == 4 and plan.reused_count == 0
    assert plan.to_dict()["concepts"] == ["riverbank", "water"]


def test_batch_bounds_and_selection_are_enforced(tmp_path: Path) -> None:
    site = make_site(tmp_path)
    with pytest.raises(ValueError):
        runner.plan_segmentation(site, SEQUENCE_ID, [], ["water"])
    with pytest.raises(ValueError):
        runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_A], [])
    with pytest.raises(ValueError):
        runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_A], ["a", "b", "c"])
    with pytest.raises(ValueError):
        runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_A], ["water and riverbank"])
    many = [f"cam___2026-09-01T{h:02d}-00-00Z.jpg" for h in range(11)]
    with pytest.raises(ValueError):
        runner.plan_segmentation(site, SEQUENCE_ID, many, ["water"])


def test_a_site_without_a_watched_area_cannot_be_planned(tmp_path: Path) -> None:
    site = make_site(tmp_path)
    config_path = site / "configs" / "site.json"
    config = json.loads(config_path.read_text())
    del config["reference_region"]
    config_path.write_text(json.dumps(config))

    with pytest.raises(ValueError, match="watched area"):
        runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_A], ["water"])


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("disabled", "plugin_disabled"),
        ("no_key", "not_configured"),
        ("no_ack", "acknowledgement_required"),
        ("no_decoder", "decoder_unavailable"),
        ("wrong_count", "confirm_count_mismatch"),
        ("bool_count", "confirm_count_mismatch"),
    ],
)
def test_every_gate_refuses_before_anything_is_uploaded(
    tmp_path: Path, credentials: HostedSamCredentials, case: str, code: str
) -> None:
    site = make_site(tmp_path)
    transport = FakeTransport((200, reply(detection_text())))
    kwargs: dict[str, Any] = {}
    if case == "disabled":
        kwargs["enabled"] = False
    elif case == "no_key":
        credentials.remove_session_key()
    elif case == "no_ack":
        credentials._acknowledged_at = None
    elif case == "no_decoder":
        kwargs["decoder"] = None
    elif case == "wrong_count":
        kwargs["count"] = 7
    elif case == "bool_count":
        kwargs["count"] = True

    with pytest.raises(runner.HostedSamRefused) as raised:
        if case == "no_decoder":
            runner.run_segmentation(
                site,
                SEQUENCE_ID,
                [IMAGE_A],
                ["water"],
                plugin_enabled=True,
                credentials=credentials,
                confirmed_request_count=1,
                decoder=None,
                transport=transport,
            )
        else:
            go(site, credentials, transport, **kwargs)

    assert raised.value.code == code
    assert transport.calls == []
    assert not (site / "outputs" / "hosted-sam-runs").exists()


def test_a_completed_run_saves_provenance_and_masks_in_original_pixels(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    transport = FakeTransport((200, reply(detection_text())))

    summary = go(site, credentials, transport)

    assert len(transport.calls) == 1
    sent = transport.calls[0]["body"]["input"][0]["content"]
    assert sent[0]["text"] == "water"
    assert sent[1]["image_url"].startswith("data:image/jpeg;base64,")
    result = summary["results"][0]
    assert result["status"] == "completed"
    assert result["review_status"] == "unreviewed"
    assert result["scores_provided"] is False
    assert result["provider"] == "meta_sam_hosted" and result["model_requested"] == "sam-3.1"
    assert result["prompt"] == "water" and len(result["image_sha256"]) == 64
    assert result["transform"]["crop_px"] == [10, 12, 50, 42]
    assert result["transform"]["source_size"] == [100, 60]
    assert result["captured_at_utc"] == "2026-09-01T00:00:00+00:00"
    run_dir = site / "outputs" / "hosted-sam-runs" / summary["run_id"]
    mask = cv2.imread(str(run_dir / result["detections"][0]["mask_png"]), cv2.IMREAD_GRAYSCALE)
    assert mask is not None and mask.shape == (60, 100)
    ys, xs = np.nonzero(mask)
    assert tuple(int(v) for v in (xs.min(), ys.min(), xs.max(), ys.max())) == (13, 16, 18, 20)
    assert result["detections"][0]["box_source_px"] == [11, 14, 30, 37]


def test_the_api_key_appears_in_no_saved_file(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    leaky = json.dumps({"error": {"message": f"key {KEY} rejected"}})

    go(site, credentials, FakeTransport((200, reply(detection_text()))))
    go(site, credentials, FakeTransport((401, leaky)), names=(IMAGE_B,))

    for path in (site / "outputs").rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes(), path
    assert KEY not in json.dumps(runner.list_sam_runs(site))


def test_zero_matches_is_a_distinct_state_not_a_failure_or_a_safe_result(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)

    summary = go(site, credentials, FakeTransport((200, reply(""))))

    result = summary["results"][0]
    assert result["status"] == "no_match" and result["detections"] == []
    assert "nothing" in result["message"]


@pytest.mark.parametrize(
    ("response", "code"),
    [
        ((401, "{}"), "invalid_key"),
        ((402, "{}"), "insufficient_quota"),
        ((429, "{}"), "rate_limited"),
        ((500, "{}"), "provider_error"),
        ((200, "garbage"), "malformed_response"),
        ((200, reply("<0f>0<|box;broken|>")), "malformed_response"),
        ((200, reply(detection_text(w=99))), "malformed_response"),
    ],
)
def test_provider_failures_are_distinct_and_leave_core_data_alone(
    tmp_path: Path, credentials: HostedSamCredentials, response: tuple[int, str], code: str
) -> None:
    site = make_site(tmp_path)
    before = (site / "configs" / "site.json").read_bytes()

    summary = go(site, credentials, FakeTransport(response))

    result = summary["results"][0]
    assert result["status"] == "failed" and result["error_code"] == code
    assert (site / "configs" / "site.json").read_bytes() == before


def test_a_stopping_error_halts_the_rest_of_the_batch(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    transport = FakeTransport((429, "{}"))

    summary = go(site, credentials, transport, names=(IMAGE_A, IMAGE_B))

    assert len(transport.calls) == 1
    statuses = [r["status"] for r in summary["results"]]
    assert statuses == ["failed", "not_attempted"]
    assert summary["results"][1]["error_code"] == "rate_limited"


def test_a_malformed_reply_does_not_stop_the_other_images(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    transport = FakeTransport((200, "garbage"), (200, reply(detection_text())))

    summary = go(site, credentials, transport, names=(IMAGE_A, IMAGE_B))

    assert [r["status"] for r in summary["results"]] == ["failed", "completed"]


def test_an_identical_rerun_reuses_saved_results_without_a_paid_request(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    first = go(site, credentials, FakeTransport((200, reply(detection_text()))))
    transport = FakeTransport((500, "{}"))

    plan = runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_A], ["water"])
    second = go(site, credentials, transport)

    assert plan.request_count == 0 and plan.reused_count == 1
    assert transport.calls == []
    assert second["run_id"] != first["run_id"]
    reused = second["results"][0]
    assert reused["status"] == "completed"
    assert reused["reused_from"]["run_id"] == first["run_id"]
    new_dir = site / "outputs" / "hosted-sam-runs" / second["run_id"]
    assert (new_dir / reused["detections"][0]["mask_png"]).is_file()


def test_changed_image_region_prompt_or_failure_is_never_served_from_cache(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    go(site, credentials, FakeTransport((200, reply(detection_text()))))
    go(site, credentials, FakeTransport((500, "{}")), names=(IMAGE_B,))

    # different concept
    assert runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_A], ["riverbank"]).request_count == 1
    # a failed earlier attempt is retried, not reused
    assert runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_B], ["water"]).request_count == 1
    # changed image bytes
    image_path = site / "inputs" / "image-sequences" / SEQUENCE_ID / "images" / IMAGE_A
    assert cv2.imwrite(str(image_path), np.full((60, 100, 3), 200, dtype=np.uint8))
    assert runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_A], ["water"]).request_count == 1
    # changed watch region
    config_path = site / "configs" / "site.json"
    config = json.loads(config_path.read_text())
    config["reference_region"] = {"x": 0, "y": 0, "width": 100, "height": 100}
    config_path.write_text(json.dumps(config))
    assert runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_B], ["water"]).request_count == 1


def test_saved_results_stay_unchanged_after_later_runs_and_config_changes(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    first = go(site, credentials, FakeTransport((200, reply(detection_text()))))
    run_dir = site / "outputs" / "hosted-sam-runs" / first["run_id"]
    snapshot = {p: p.read_bytes() for p in run_dir.rglob("*") if p.is_file()}

    go(site, credentials, FakeTransport((200, reply(detection_text()))), names=(IMAGE_B,))
    go(site, credentials, FakeTransport((200, reply(""))))
    (site / "configs" / "site.json").write_text(json.dumps({"changed": True}))

    assert {p: p.read_bytes() for p in run_dir.rglob("*") if p.is_file()} == snapshot


def test_results_refuse_to_overwrite_existing_evidence(tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    runner._write_new_json(target, {"a": 1})
    with pytest.raises(FileExistsError):
        runner._write_new_json(target, {"a": 2})


def test_review_decisions_are_appended_and_never_edit_the_result(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    summary = go(site, credentials, FakeTransport((200, reply(detection_text()))))
    run_id, result_id = summary["run_id"], summary["results"][0]["result_id"]
    result_file = site / "outputs" / "hosted-sam-runs" / run_id / "results" / f"{result_id}.json"
    saved = result_file.read_bytes()

    runner.record_sam_review(site, run_id, result_id, "needs_correction")
    runner.record_sam_review(site, run_id, result_id, "accepted")

    assert result_file.read_bytes() == saved
    reread = runner.read_sam_run(site, run_id)["results"][0]
    assert reread["review_status"] == "accepted"
    with pytest.raises(ValueError):
        runner.record_sam_review(site, run_id, result_id, "trusted_label")
    with pytest.raises(ValueError):
        runner.record_sam_review(site, run_id, "missing", "accepted")
    with pytest.raises(ValueError):
        runner.read_sam_run(site, "../../etc")


def test_overlay_draws_masks_on_the_source_image_and_leaves_the_guide_config_alone(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    summary = go(site, credentials, FakeTransport((200, reply(detection_text()))))
    config_before = (site / "configs" / "site.json").read_bytes()

    png = runner.render_overlay(site, summary["run_id"], summary["results"][0]["result_id"])

    image = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None and image.shape == (60, 100, 3)
    assert (site / "configs" / "site.json").read_bytes() == config_before
    original = cv2.imread(
        str(site / "inputs" / "image-sequences" / SEQUENCE_ID / "images" / IMAGE_A)
    )
    assert original is not None and not np.array_equal(image, original)
    # The raw mask file is separate and still pure 0/255.
    run_dir = site / "outputs" / "hosted-sam-runs" / summary["run_id"]
    raw = cv2.imread(str(run_dir / "masks" / f"{summary['results'][0]['result_id']}-0.png"), 0)
    assert raw is not None and {int(v) for v in np.unique(raw)} <= {0, 255}

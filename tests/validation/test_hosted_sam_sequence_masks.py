"""Fetching water masks for a whole sequence: only images without a mask are ever sent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_hosted_sam_runner import (
    IMAGE_A,
    IMAGE_B,
    KEY,
    SEQUENCE_ID,
    FakeTransport,
    detection_text,
    make_site,
    ones_decoder,
    reply,
)

from openfloodai.evidence.hosted_sam_credentials import ENV_VAR, HostedSamCredentials
from openfloodai.validation import hosted_sam_runner as runner

OK = (200, reply(detection_text()))
MISSING = object()


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> HostedSamCredentials:
    monkeypatch.delenv(ENV_VAR, raising=False)
    holder = HostedSamCredentials()
    holder.set_session_key(KEY)
    holder.acknowledge_upload()
    return holder


def fetch(
    site: Path,
    creds: HostedSamCredentials,
    transport: FakeTransport,
    *,
    count: object = MISSING,
    enabled: bool = True,
) -> dict[str, Any]:
    plan = runner.plan_sequence_masks(site, SEQUENCE_ID)
    return runner.run_sequence_masks(
        site,
        SEQUENCE_ID,
        plugin_enabled=enabled,
        credentials=creds,
        confirmed_request_count=plan["to_send"] if count is MISSING else count,
        decoder=ones_decoder,
        transport=transport,
    )


def run_dirs(site: Path) -> list[str]:
    root = site / "outputs" / "hosted-sam-runs"
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


def test_the_plan_counts_images_that_still_need_a_mask(tmp_path: Path) -> None:
    plan = runner.plan_sequence_masks(make_site(tmp_path), SEQUENCE_ID)
    assert plan["total_images"] == 2 and plan["already_have_masks"] == 0
    assert plan["to_send"] == 2 and plan["concept"] == "river water"
    assert plan["over_limit"] is False and plan["limit"] == runner.MAX_BULK_REQUESTS


def test_every_image_without_a_mask_is_sent_once_and_saved_as_an_unreviewed_draft(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    transport = FakeTransport(OK)
    result = fetch(site, credentials, transport)
    assert len(transport.calls) == 2 and result["sent"] == 2 and result["completed"] == 2
    assert result["skipped"] is False and result["not_sent"] == 0
    saved = runner.list_sam_results(site, SEQUENCE_ID)
    assert {r["filename"] for r in saved} == {IMAGE_A, IMAGE_B}
    assert {r["prompt"] for r in saved} == {"river water"}
    assert {r["review_status"] for r in saved} == {"unreviewed"}  # a draft, never a verified mask


def test_when_every_image_already_has_a_mask_nothing_is_sent_or_created(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    fetch(site, credentials, FakeTransport(OK))
    runs_before = run_dirs(site)
    runner.record_sam_review(
        site, runs_before[0], runner.read_sam_run(site, runs_before[0])["result_ids"][0], "accepted"
    )

    again = HostedSamCredentials()  # no key and no acknowledgement: nothing needs them
    transport = FakeTransport(OK)
    result = runner.run_sequence_masks(
        site,
        SEQUENCE_ID,
        plugin_enabled=False,
        credentials=again,
        confirmed_request_count=None,  # no confirmation is needed when nothing is sent
        decoder=None,
        transport=transport,
    )
    assert result["skipped"] is True and result["to_send"] == 0
    assert result["already_have_masks"] == 2 and result["runs"] == []
    assert transport.calls == [] and run_dirs(site) == runs_before
    statuses = {r["review_status"] for r in runner.list_sam_results(site, SEQUENCE_ID)}
    assert "accepted" in statuses  # an earlier human decision is untouched


def test_only_the_images_that_lack_a_mask_are_sent(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    first = FakeTransport(OK)
    plan = runner.plan_segmentation(site, SEQUENCE_ID, [IMAGE_A], ["river water"])
    runner.run_segmentation(
        site,
        SEQUENCE_ID,
        [IMAGE_A],
        ["river water"],
        plugin_enabled=True,
        credentials=credentials,
        confirmed_request_count=plan.request_count,
        decoder=ones_decoder,
        transport=first,
    )
    transport = FakeTransport(OK)
    result = fetch(site, credentials, transport)
    assert result["already_have_masks"] == 1 and result["to_send"] == 1
    assert len(transport.calls) == 1
    new_run = [r for r in runner.list_sam_runs(site) if r["run_id"] == result["runs"][0]["run_id"]]
    assert new_run[0]["filenames"] == [IMAGE_B]  # IMAGE_A's mask is not duplicated


def test_a_wrong_or_missing_confirmation_refuses_before_any_upload(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    transport = FakeTransport(OK)
    for bad in (1, 3, None, True, "2"):
        with pytest.raises(runner.HostedSamRefused) as raised:
            fetch(site, credentials, transport, count=bad)
        assert raised.value.code == "confirm_count_mismatch"
    assert transport.calls == [] and run_dirs(site) == []


def test_the_gates_still_apply_when_masks_are_needed(
    tmp_path: Path, credentials: HostedSamCredentials
) -> None:
    site = make_site(tmp_path)
    with pytest.raises(runner.HostedSamRefused) as disabled:
        fetch(site, credentials, FakeTransport(OK), enabled=False)
    assert disabled.value.code == "plugin_disabled"
    credentials.remove_session_key()
    with pytest.raises(runner.HostedSamRefused) as no_key:
        fetch(site, credentials, FakeTransport(OK))
    assert no_key.value.code == "not_configured"
    assert run_dirs(site) == []


def test_one_click_is_limited_to_a_ceiling_of_paid_requests(
    tmp_path: Path, credentials: HostedSamCredentials, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = make_site(tmp_path)
    monkeypatch.setattr(runner, "MAX_BULK_REQUESTS", 1)
    assert runner.plan_sequence_masks(site, SEQUENCE_ID)["over_limit"] is True
    transport = FakeTransport(OK)
    with pytest.raises(runner.HostedSamRefused) as raised:
        fetch(site, credentials, transport)
    assert raised.value.code == "bulk_limit" and transport.calls == []


def test_a_quota_error_stops_the_remaining_batches(
    tmp_path: Path, credentials: HostedSamCredentials, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = make_site(tmp_path)
    monkeypatch.setattr(runner, "MAX_IMAGES_PER_BATCH", 1)  # two images = two batches
    transport = FakeTransport((402, "{}"))
    result = fetch(site, credentials, transport)
    assert len(transport.calls) == 1  # the second batch is never sent
    assert result["stopped_because"] == "insufficient_quota"
    assert result["failed"] == 1 and result["not_sent"] == 1 and result["sent"] == 1
    assert len(result["runs"]) == 1


def test_a_sequence_without_downloaded_images_is_a_clear_error(tmp_path: Path) -> None:
    site = make_site(tmp_path)
    manifest = site / "inputs" / "image-sequences" / SEQUENCE_ID / "sequence-manifest.jsonl"
    manifest.write_text('{"filename": "x.jpg", "download_status": "failed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="no downloaded images"):
        runner.plan_sequence_masks(site, SEQUENCE_ID)

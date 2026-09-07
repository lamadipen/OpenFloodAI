from __future__ import annotations

import json
import os
import socket
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

from openfloodai.review import load_manifest_records
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


def write_validation_report(site_dir: Path) -> None:
    (site_dir / "outputs").mkdir(exist_ok=True)
    (site_dir / "outputs" / "validation-report.md").write_text(
        "\n".join(
            [
                "# Site Validation Report",
                "",
                "## Validation Scorecard",
                "- Videos tested: 8",
                "- Label windows: 14",
                "- Agree: 5",
                "- Disagree: 2",
                "- Cannot compare: 1",
                "- Summary: Reviewed 8 video(s) and 14 label window(s): 5 agree, 2 "
                "disagree, and 1 cannot compare.",
            ]
        ),
        encoding="utf-8",
    )


def write_history_report(site_dir: Path, filename: str, counts: tuple[int, int, int]) -> Path:
    report_path = site_dir / "outputs" / filename
    report_path.write_text(
        "\n".join(
            [
                "# Site Validation Report",
                "",
                "## Counts",
                f"- Agree: {counts[0]}",
                f"- Disagree: {counts[1]}",
                f"- Cannot compare: {counts[2]}",
            ]
        ),
        encoding="utf-8",
    )
    return report_path


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


def test_site_details_page_loads_from_its_local_route(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        status, content_type, body = get_text(f"{base_url}/site-details.html?site=example-site")

    assert status == 200
    assert "text/html" in content_type
    assert 'id="detailSiteSelect"' in body


def test_home_ui_page_has_safety_note_container(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert 'id="safetyNote"' in body


def test_home_ui_page_has_validation_summary_and_evidence_labels(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert "Latest validation summary" in body
    assert "Human review is still needed" in body
    assert "Evidence folder" in body
    assert "function scorecardValue(value)" in body
    assert "Not available" in body
    assert "Videos tested: undefined" not in body


def test_sites_api_handles_partial_scorecard_report(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir = make_site(sites_dir / "example-site")
    (site_dir / "outputs").mkdir(exist_ok=True)
    (site_dir / "outputs" / "validation-report.md").write_text(
        "# Site Validation Report\n\n## Validation Scorecard\n- Agree: 2\n",
        encoding="utf-8",
    )

    with serve_home_ui(sites_dir) as base_url:
        site = get_json(f"{base_url}/api/sites")["sites"][0]

    assert site["latest_scorecard"] == {
        "agree": 2,
        "human_review_needed": 0,
    }


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
    assert site["latest_scorecard"] is None
    assert site["report_history"] == []


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
        "latest_scorecard",
        "review_images_path",
        "report_history",
    ):
        assert field in site, f"Home UI needs {field} to render site status"


def test_sites_api_exposes_scorecard_and_review_state(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir = make_site(sites_dir / "example-site")
    write_validation_report(site_dir)
    review_images = site_dir / "outputs" / "river-001" / "review-images"
    review_images.mkdir(parents=True)

    with serve_home_ui(sites_dir) as base_url:
        site = get_json(f"{base_url}/api/sites")["sites"][0]

    assert site["latest_scorecard"] == {
        "videos_tested": 8,
        "label_windows": 14,
        "agree": 5,
        "disagree": 2,
        "cannot_compare": 1,
        "summary": (
            "Reviewed 8 video(s) and 14 label window(s): 5 agree, 2 disagree, and 1 cannot compare."
        ),
        "human_review_needed": 3,
    }
    assert site["review_images_path"] == str(review_images)


def test_sites_api_exposes_one_report_history_entry(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir = make_site(sites_dir / "example-site")
    report_path = write_history_report(site_dir, "validation-report-2026-09-05.md", (2, 1, 3))

    with serve_home_ui(sites_dir) as base_url:
        site = get_json(f"{base_url}/api/sites")["sites"][0]

    assert len(site["report_history"]) == 1
    assert site["report_history"][0]["path"] == str(report_path)
    assert site["report_history"][0]["counts"] == {
        "agree": 2,
        "disagree": 1,
        "cannot_compare": 3,
    }


def test_sites_api_returns_report_history_newest_first(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir = make_site(sites_dir / "example-site")
    older = write_history_report(site_dir, "validation-report-older.md", (4, 3, 1))
    newer = write_history_report(site_dir, "validation-report-newer.md", (5, 2, 1))
    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))

    with serve_home_ui(sites_dir) as base_url:
        site = get_json(f"{base_url}/api/sites")["sites"][0]

    assert [entry["path"] for entry in site["report_history"]] == [
        str(newer),
        str(older),
    ]
    assert site["report_history"][0]["counts"]["cannot_compare"] == 1


def test_sites_api_prefers_saved_run_history_and_keeps_run_evidence_together(
    tmp_path: Path,
) -> None:
    sites_dir = tmp_path / "sites"
    site_dir = make_site(sites_dir / "example-site")
    runs_dir = site_dir / "outputs" / "runs"
    newer = runs_dir / "run-new"
    older = runs_dir / "run-old"
    for run_dir, created_at, counts in (
        (older, "2026-09-05T10:00:00+00:00", (1, 2, 3)),
        (newer, "2026-09-05T11:00:00+00:00", (4, 1, 2)),
    ):
        (run_dir / "review-images").mkdir(parents=True)
        (run_dir / "validation-report.md").write_text(
            "\n".join(
                [
                    "# Site Validation Report",
                    "",
                    f"- Agree: {counts[0]}",
                    f"- Disagree: {counts[1]}",
                    f"- Cannot compare: {counts[2]}",
                ]
            ),
            encoding="utf-8",
        )
        (run_dir / "run-metadata.json").write_text(
            json.dumps(
                {
                    "run_id": run_dir.name,
                    "created_at": created_at,
                    "status": "completed_with_warnings",
                    "report_path": str(run_dir / "validation-report.md"),
                    "review_images_path": str(run_dir / "review-images"),
                }
            ),
            encoding="utf-8",
        )

    with serve_home_ui(sites_dir) as base_url:
        site = get_json(f"{base_url}/api/sites")["sites"][0]

    assert [entry["run_id"] for entry in site["report_history"]] == ["run-new", "run-old"]
    assert site["report_history"][0]["evidence_path"] == str(newer / "review-images")
    assert site["report_history"][0]["status"] == "completed_with_warnings"


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


def test_home_ui_page_has_guided_workflow_section(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert 'id="workflowPanel"' in body
    assert 'id="workflowSteps"' in body
    assert "Guided validation workflow" in body
    assert "function renderWorkflow(site)" in body
    assert "window.startWorkflowStep" in body


def test_home_ui_offers_separate_guided_and_classic_views(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert 'data-view="classic"' in body
    assert 'data-page="home"' in body
    assert 'id="guidedViewButton"' in body
    assert 'id="classicViewButton"' in body
    assert 'body[data-view="classic"] #workflowPanel' in body
    assert 'body[data-view="guided"] #classicToolbar' in body
    assert "function setActiveView(view)" in body
    assert 'setActiveView("guided")' in body
    assert 'setActiveView("classic")' in body
    assert 'document.body.dataset.view !== "guided"' in body
    assert "grid-template-columns: 42px minmax(0, 1fr);" in body
    assert 'id="detailSiteSelect"' in body
    assert "isDetailsPage" in body
    assert "requestedSiteName" in body
    assert 'body[data-page="details"] .view-switch' in body
    assert "if (!site || !isDetailsPage)" in body


def test_home_ui_page_keeps_standalone_actions_next_to_the_workflow(tmp_path: Path) -> None:
    """Users must still be able to run one action without walking the whole workflow."""

    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert 'id="createSiteButton"' in body
    assert 'id="addVideoButton"' in body
    assert 'id="addLabelButton"' in body
    assert "window.runValidationForSite" in body


def test_create_site_form_generates_fields_from_a_selected_video(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert 'id="setupVideoFileInput"' in body
    assert body.index('id="setupVideoFileInput"') < body.index('id="setupSiteNameInput"')
    assert 'id="setupSiteIdInput"' in body
    assert 'id="setupCameraIdInput"' in body
    assert "function sanitizeSiteFolderName(value)" in body
    assert "function fillSiteFieldsFromVideo(videoName)" in body
    assert "`${folderName}_sid`" in body
    assert "`${folderName}_camid`" in body
    assert 'setupVideoFileInput.addEventListener("change"' in body


def test_create_site_form_collects_the_first_video_and_watched_area(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert 'name="video_file" id="setupVideoFileInput"' in body
    assert 'id="setupVideoRegionCanvas"' in body
    assert 'name="reference_region" id="setupReferenceRegionInput"' in body
    assert 'name="video_id" id="setupVideoIdInput"' in body
    assert 'name="purpose" id="setupPurposeSelect"' in body
    assert 'name="notes" required' in body
    assert 'fetch("/api/setup-site-with-video"' in body


def test_home_server_exposes_combined_site_and_first_video_endpoint(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert "/api/setup-site-with-video" in body


def test_classic_site_cards_offer_a_dedicated_details_view(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert "Details View" in body
    assert "/site-details.html?site=${encodeURIComponent(site.site_name)}" in body
    assert 'body[data-page="details"] #siteGrid' in body
    assert 'body[data-page="details"] #detailPanel' not in body
    assert "Back to dashboard" in body


def test_classic_site_cards_offer_video_intake_for_existing_sites(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert "+ Add Video" in body
    assert "window.openVideoFormForSite" in body
    assert "openVideoFormForSite('${escapeHtml(site.site_name)}')" in body
    assert "videoSiteSelect.value = siteName" in body


def test_sites_api_exposes_workflow_steps_for_the_home_ui(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    make_site(sites_dir / "example-site")

    with serve_home_ui(sites_dir) as base_url:
        payload = get_json(f"{base_url}/api/sites")

    steps = payload["sites"][0]["workflow_steps"]

    assert [step["key"] for step in steps] == [
        "site_setup",
        "video_intake",
        "watched_area",
        "human_labels",
        "manifest",
        "run_validation",
        "review_results",
    ]
    for step in steps:
        assert step["status"] in {"complete", "missing", "needs_review"}
        assert step["meaning"]
        assert step["actions"]
        assert all(action["label"] and action["action_id"] for action in step["actions"])


def test_sites_api_reports_missing_watched_area_as_a_required_step(tmp_path: Path) -> None:
    """make_site writes a config with no reference_region, so validation cannot run yet."""

    sites_dir = tmp_path / "sites"
    make_site(sites_dir / "example-site")

    with serve_home_ui(sites_dir) as base_url:
        payload = get_json(f"{base_url}/api/sites")

    site = payload["sites"][0]
    watched_area = next(step for step in site["workflow_steps"] if step["key"] == "watched_area")

    assert site["reference_region_found"] is False
    assert watched_area["status"] == "missing"
    assert watched_area["status_text"] == "Missing"
    assert watched_area["required_for_validation"] is True


def test_sites_api_shows_missing_manifest_and_create_action(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir = make_site(sites_dir / "example-site")
    (site_dir / "manifest.jsonl").unlink()

    with serve_home_ui(sites_dir) as base_url:
        site = get_json(f"{base_url}/api/sites")["sites"][0]

    manifest_step = next(step for step in site["workflow_steps"] if step["key"] == "manifest")
    assert site["manifest_status"] == "Missing"
    assert site["manifest_tracked_video_count"] == 0
    assert manifest_step["actions"] == [
        {"label": "Create manifest from local videos", "action_id": "repair_manifest"}
    ]


def test_repair_manifest_api_creates_manifest_for_existing_local_videos(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir = make_site(sites_dir / "example-site")
    (site_dir / "manifest.jsonl").unlink()

    with serve_home_ui(sites_dir) as base_url:
        request = Request(
            f"{base_url}/api/repair-manifest",
            data=json.dumps({"folder_name": "example-site"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["success"] is True
    assert payload["created_count"] == 1
    records = json.loads((site_dir / "manifest.jsonl").read_text(encoding="utf-8"))
    assert records["approved_for_repo"] is False


def test_workflow_step_actions_open_their_form_inside_the_step(tmp_path: Path) -> None:
    """A step action expands its form in the step card, not as a separate panel."""

    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert 'data-step-slot="${escapeHtml(step.key)}"' in body
    assert "function mountWorkflowForm()" in body
    assert "slot.append(panel)" in body
    assert "function detachWorkflowForm()" in body


def test_open_workflow_form_survives_a_workflow_rerender(tmp_path: Path) -> None:
    """Re-rendering replaces step markup, so the open form must be re-mounted."""

    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    render_start = body.index("function renderWorkflow(site)")
    render_body = body[render_start : body.index("function renderSiteDetails(site)")]

    assert "detachWorkflowForm();" in render_body
    assert "mountWorkflowForm();" in render_body
    assert 'id="formHome"' in body


def test_workflow_panel_appears_before_the_forms_it_opens(tmp_path: Path) -> None:
    """Step actions must reveal their form below the workflow, not above it."""

    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    workflow_index = body.index('id="workflowPanel"')

    assert workflow_index < body.index('id="setupForm"')
    assert workflow_index < body.index('id="videoFormPanel"')
    assert workflow_index < body.index('id="labelFormPanel"')


def test_sites_api_offers_select_and_create_actions_on_filled_steps(tmp_path: Path) -> None:
    """A site with a config, videos, and labels can be switched to, not only added to."""

    sites_dir = tmp_path / "sites"
    make_site(sites_dir / "example-site")

    with serve_home_ui(sites_dir) as base_url:
        payload = get_json(f"{base_url}/api/sites")

    steps = {step["key"]: step for step in payload["sites"][0]["workflow_steps"]}

    def action_ids(key: str) -> list[str]:
        return [action["action_id"] for action in steps[key]["actions"]]

    assert action_ids("site_setup") == ["select_site", "create_site"]
    assert action_ids("video_intake") == ["select_video", "add_video"]
    assert action_ids("human_labels") == ["select_label", "add_label"]


def test_home_ui_renders_every_action_for_a_step(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert "(step.actions || [])" in body
    assert 'class="workflow-actions"' in body
    assert 'id="videoListPanel"' in body
    assert 'id="labelListPanel"' in body
    assert "function fillWorkflowList(actionId, siteName)" in body
    assert "Manifest details" in body
    assert "site.manifest_issues" in body


def test_select_site_picks_a_site_inline_instead_of_jumping_to_details(
    tmp_path: Path,
) -> None:
    """Selecting a site should switch the workflow in place, not scroll to a dropdown."""

    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert 'id="siteListPanel"' in body
    assert "window.selectSiteFromWorkflow" in body
    assert "selectSiteFromWorkflow('${escapeHtml(entry.site_name)}')" in body
    assert "renderWorkflow(selectedSite);" in body


def test_sites_api_exposes_validation_readiness(tmp_path: Path) -> None:
    """make_site has no reference_region, so the run is blocked until one is set."""

    sites_dir = tmp_path / "sites"
    make_site(sites_dir / "example-site")

    with serve_home_ui(sites_dir) as base_url:
        payload = get_json(f"{base_url}/api/sites")

    readiness = payload["sites"][0]["validation_readiness"]

    assert readiness["mode"] == "blocked"
    assert readiness["can_run"] is False
    assert readiness["missing"] == ["watched area"]
    assert [check["label"] for check in readiness["checks"]] == [
        "Site config",
        "Videos",
        "Watched area",
        "Human labels",
        "Manifest",
        "Output",
    ]


def test_sites_api_blocks_run_validation_without_a_watched_area(tmp_path: Path) -> None:
    """The Run Validation button must not promise a run the pipeline will refuse."""

    sites_dir = tmp_path / "sites"
    make_site(sites_dir / "example-site")

    with serve_home_ui(sites_dir) as base_url:
        payload = get_json(f"{base_url}/api/sites")

    site = payload["sites"][0]

    assert site["video_count"] == 1
    assert site["reference_region_found"] is False
    assert site["ready_for_machine_review"] is False
    assert site["ready_for_validation"] is False


def test_home_ui_renders_the_readiness_summary_in_the_run_step(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert "function renderReadiness(site)" in body
    assert 'step.key === "run_validation" ? renderReadiness(site) : ""' in body
    assert "readiness-headline" in body
    assert '!site.ready_for_validation ? "disabled" : ""' in body


def test_run_validation_uses_the_main_site_validation_path(tmp_path: Path) -> None:
    """The run must produce the full main-path evidence, not a shortcut result."""

    sites_dir = tmp_path / "sites"
    site_dir = make_site(sites_dir / "example-site")
    write_json(
        site_dir / "configs" / "site-config.json",
        {
            "site_id": "example-site",
            "camera_id": "camera-demo-01",
            "site_name": "Example Site",
            "public_location": "Demo River near Example Town",
            "input_type": "local_video",
            "reference_region": {"x": 0, "y": 50, "width": 100, "height": 50},
        },
    )

    with serve_home_ui(sites_dir) as base_url:
        request = Request(
            f"{base_url}/api/run-validation",
            data=json.dumps({"folder_name": "example-site"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["success"] is True
    assert set(payload["counts"]) == {"agree", "disagree", "cannot_compare"}

    # The main path preserves each run with its own report and scorecard.
    runs = sorted((site_dir / "outputs" / "runs").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "validation-report.md").is_file()
    assert (runs[0] / "scorecard.json").is_file()
    assert (runs[0] / "run-metadata.json").is_file()
    assert Path(payload["report_path"]).is_file()


def test_readiness_panel_spans_the_whole_step_card(tmp_path: Path) -> None:
    """The step card is a grid, so a child without a span lands in the 42px number column."""

    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    readiness_rule = body[body.index(".readiness {") : body.index(".readiness.is-full")]

    assert "grid-column: 1 / -1;" in readiness_rule


def test_mvp_rehearsal_setup_to_five_video_result_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise real endpoints and real decoding using only generated local media."""

    original_connect = socket.socket.connect

    def local_only(sock: socket.socket, address: Any) -> None:
        assert isinstance(address, tuple) and address[0] == "127.0.0.1", (
            "Rehearsal must not connect to external services"
        )
        original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    sites = tmp_path / "sites"
    sites.mkdir()
    cases = [
        ("stable", [80] * 20, "no_clear_change"),
        ("rising", list(range(50, 90, 2)), "water_rising"),
        ("falling", list(range(90, 50, -2)), "water_falling"),
        ("dark", [0] * 20, "cannot_judge"),
        ("unclear", [80] * 20, "cannot_judge"),
    ]
    region = {"x": 0, "y": 50, "width": 100, "height": 50}
    with serve_home_ui(sites) as base:

        def post(endpoint: str, data: dict[str, object]) -> dict[str, Any]:
            request = Request(
                base + endpoint,
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=30) as response:
                result: dict[str, Any] = json.load(response)
            assert result["success"], result
            return result

        created = post(
            "/api/setup-site",
            {
                "folder_name": "rehearsal",
                "site_id": "rehearsal",
                "camera_id": "test-camera",
                "site_name": "Rehearsal",
                "privacy_notes": "Generated images only.",
            },
        )
        site = Path(created["site_dir"])
        assert get_json(base + "/api/sites")["sites"][0]["validation_readiness"]["can_run"] is False

        for video_id, values, _ in cases:
            source = tmp_path / f"{video_id}.avi"
            writer = cv2.VideoWriter(
                str(source),
                cv2.VideoWriter_fourcc(*"MJPG"),  # type: ignore[attr-defined]
                2.0,
                (32, 24),
            )
            assert writer.isOpened()
            try:
                for value in values:
                    writer.write(np.full((24, 32, 3), value, dtype=np.uint8))
            finally:
                writer.release()
            original = source.read_bytes()
            post(
                "/api/intake-video",
                {
                    "folder_name": "rehearsal",
                    "video_path": str(source),
                    "video_id": video_id,
                    "purpose": "practice_normal_water",
                    "split": "practice",
                    "notes": "Synthetic workflow test; not flood evidence.",
                    "reference_region": region,
                },
            )
            assert source.read_bytes() == original
            assert (site / "inputs/videos" / source.name).read_bytes() == original

        assert json.loads(Path(created["config_path"]).read_text())["reference_region"] == region
        rows = load_manifest_records(site / "manifest.jsonl")
        assert len(rows) == 5
        assert all(row["approved_for_repo"] is False for row in rows)
        assert all(row["has_human_label"] is False for row in rows)
        post("/api/repair-manifest", {"folder_name": "rehearsal"})
        assert load_manifest_records(site / "manifest.jsonl") == rows

        assert (
            get_json(base + "/api/sites")["sites"][0]["validation_readiness"]["mode"]
            == "machine_only"
        )
        machine = post("/api/run-validation", {"folder_name": "rehearsal"})
        machine_report = Path(machine["report_path"]).read_text()
        assert machine["counts"]["agree"] == 0
        assert machine["counts"]["cannot_compare"] == 5
        assert "No human label" in machine_report

        for video_id, _, human_label in cases:
            post(
                "/api/add-label",
                {
                    "folder_name": "rehearsal",
                    "video_id": video_id,
                    "start_second": 0,
                    "end_second": 10,
                    "human_label": human_label,
                },
            )
        reviewed = post("/api/run-validation", {"folder_name": "rehearsal"})
        run = Path(reviewed["report_path"]).parent
        # Flat synthetic scenes do not establish water-level evidence. Do not count
        # successful API execution as successful human/machine agreement.
        assert reviewed["counts"] == {"agree": 0, "disagree": 0, "cannot_compare": 5}
        assert Path(machine["report_path"]).read_text() == machine_report
        assert run != Path(machine["report_path"]).parent
        assert len(list((run / "records").glob("*.jsonl"))) == 5
        assert list((run / "review-images").rglob("*.png"))
        assert not list((run / "review-images/dark").glob("*.png"))
        assert (run / "scorecard.json").is_file()
        assert (run / "run-metadata.json").is_file()
        report_text = Path(reviewed["report_path"]).read_text()
        assert "No human label was found" not in report_text
        assert "- Label windows compared: 5" in report_text
        assert "dark" in report_text and "cannot_compare" in report_text
        assert "unclear" in report_text
        refreshed = get_json(base + "/api/sites")["sites"][0]
        assert refreshed["latest_report_path"] == reviewed["report_path"]
        assert refreshed["latest_scorecard"]["cannot_compare"] == 5
        assert refreshed["review_images_path"]
        assert len(refreshed["report_history"]) == 2
        assert all(
            row["approved_for_repo"] is False
            for row in load_manifest_records(site / "manifest.jsonl")
        )
        assert {p.name for p in (site / "outputs").iterdir()} == {".gitkeep", "runs"}

    print(f"Synthetic rehearsal files: {tmp_path}")

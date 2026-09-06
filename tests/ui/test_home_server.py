from __future__ import annotations

import json
import os
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


def test_home_ui_page_keeps_standalone_actions_next_to_the_workflow(tmp_path: Path) -> None:
    """Users must still be able to run one action without walking the whole workflow."""

    with serve_home_ui(tmp_path) as base_url:
        _, _, body = get_text(f"{base_url}/openfloodai-home-ui.html")

    assert 'id="createSiteButton"' in body
    assert 'id="addVideoButton"' in body
    assert 'id="addLabelButton"' in body
    assert "window.runValidationForSite" in body


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

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from test_home_server import get_json, get_text, make_site, serve_home_ui

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_DETAILS_PATH = REPO_ROOT / "tools" / "openfloodai-site-details.html"


def write_run_dir(
    site_dir: Path,
    run_id: str,
    *,
    with_inputs: bool = True,
    with_scorecard: bool = True,
    with_metadata: bool = True,
    with_report: bool = True,
) -> Path:
    """Build a run folder with the exact shape _send_run_detail/read_input_snapshot expect."""

    run_dir = site_dir / "outputs" / "runs" / run_id
    run_dir.mkdir(parents=True)
    if with_metadata:
        (run_dir / "run-metadata.json").write_text(
            json.dumps({"run_id": run_id, "site_name": site_dir.name, "status": "completed"}),
            encoding="utf-8",
        )
    if with_scorecard:
        (run_dir / "scorecard.json").write_text(
            json.dumps(
                {
                    "videos_reviewed": 2,
                    "videos_with_human_label": 1,
                    "label_windows": 1,
                    "agree_count": 0,
                    "disagree_count": 0,
                    "cannot_compare_count": 2,
                    "baseline_ready_count": 0,
                    "practice_only_count": 1,
                }
            ),
            encoding="utf-8",
        )
    if with_report:
        (run_dir / "validation-report.md").write_text(
            "# Site Validation Report\n\n## Counts\n- Agree: 0\n", encoding="utf-8"
        )
    if with_inputs:
        inputs_dir = run_dir / "inputs-used"
        inputs_dir.mkdir()
        (inputs_dir / "receipt.json").write_text(
            json.dumps({"run_id": run_id, "site_id": "demo_sid", "mode": "machine_only"}),
            encoding="utf-8",
        )
        (inputs_dir / "site-config.snapshot.json").write_text(
            json.dumps({"site_id": "demo_sid"}), encoding="utf-8"
        )
        (inputs_dir / "watched-area.snapshot.json").write_text(
            json.dumps({"x": 0, "y": 0, "width": 100, "height": 100}), encoding="utf-8"
        )
        (inputs_dir / "manifest.snapshot.jsonl").write_text("", encoding="utf-8")
        (inputs_dir / "labels.snapshot.jsonl").write_text("", encoding="utf-8")
        (inputs_dir / "video-list.snapshot.json").write_text(
            json.dumps([{"video_id": "river-001", "filename": "river-001.mp4", "size_bytes": 42}]),
            encoding="utf-8",
        )
    return run_dir


def test_site_details_page_is_served_at_its_dedicated_route(tmp_path: Path) -> None:
    with serve_home_ui(tmp_path / "sites") as base:
        status, content_type, page = get_text(base + "/site-details.html")
        dashboard_status, _, dashboard_page = get_text(base + "/openfloodai-home-ui.html")
    assert status == 200
    assert "text/html" in content_type
    assert 'id="siteSwitcher"' in page
    assert page != dashboard_page
    assert dashboard_status == 200


def test_packaged_site_details_page_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "package"
    (package / "static").mkdir(parents=True)
    (package / "static" / "openfloodai-site-details.html").write_text("<h1>Packaged page</h1>")
    monkeypatch.setattr(resources, "files", lambda name: package)
    with serve_home_ui(tmp_path / "sites", ui_path=tmp_path / "absent" / "home.html") as base:
        assert get_text(base + "/site-details.html")[2] == "<h1>Packaged page</h1>"


def test_site_config_route_returns_the_current_config(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    make_site(sites / "example-site")
    with serve_home_ui(sites) as base:
        payload = get_json(base + "/api/site-config?folder_name=example-site")
    assert payload["config"] == {"site_id": "example-site"}
    assert payload["config_path"].endswith("site-config.json")


def test_site_config_route_404s_when_site_has_no_config(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    (sites / "no-config-site").mkdir(parents=True)
    with serve_home_ui(sites) as base:
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/site-config?folder_name=no-config-site")
    assert error.value.code == 404


@pytest.mark.parametrize("folder_name", ["../escape", "", "/etc"])
def test_site_config_route_rejects_a_folder_name_outside_the_sites_dir(
    tmp_path: Path, folder_name: str
) -> None:
    sites = tmp_path / "sites"
    sites.mkdir()
    with serve_home_ui(sites) as base:
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/site-config?folder_name=" + folder_name)
    assert error.value.code == 404


def test_site_manifest_route_returns_parsed_rows(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    make_site(sites / "example-site")
    with serve_home_ui(sites) as base:
        payload = get_json(base + "/api/site-manifest?folder_name=example-site")
    assert payload["records"] == [
        {
            "video_id": "river-001",
            "filename": "river-001.mp4",
            "purpose": "practice",
            "split": "practice",
            "approved_for_repo": False,
            "has_human_label": True,
            "notes": "Synthetic test metadata.",
        }
    ]


def test_site_manifest_route_returns_an_empty_list_when_manifest_is_missing(
    tmp_path: Path,
) -> None:
    sites = tmp_path / "sites"
    (sites / "bare-site").mkdir(parents=True)
    with serve_home_ui(sites) as base:
        payload = get_json(base + "/api/site-manifest?folder_name=bare-site")
    assert payload["records"] == []


def test_site_manifest_route_rejects_a_folder_name_outside_the_sites_dir(
    tmp_path: Path,
) -> None:
    sites = tmp_path / "sites"
    sites.mkdir()
    with serve_home_ui(sites) as base:
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/site-manifest?folder_name=../escape")
    assert error.value.code == 404


def test_run_detail_route_returns_report_scorecard_metadata_and_inputs(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    site_dir = sites / "example-site"
    site_dir.mkdir(parents=True)
    run_dir = write_run_dir(site_dir, "20260101T000000Z-aaaaaaaa")
    with serve_home_ui(sites) as base:
        payload = get_json(base + "/api/run-detail?run_dir=" + str(run_dir))
    assert payload["run_metadata"]["run_id"] == "20260101T000000Z-aaaaaaaa"
    assert payload["scorecard"]["videos_reviewed"] == 2
    assert payload["scorecard"]["videos_with_human_label"] == 1
    assert payload["report"].startswith("# Site Validation Report")
    assert payload["inputs"]["receipt"]["site_id"] == "demo_sid"
    assert payload["inputs"]["videos"][0]["video_id"] == "river-001"


def test_run_detail_route_tolerates_missing_optional_files(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    site_dir = sites / "example-site"
    site_dir.mkdir(parents=True)
    run_dir = write_run_dir(
        site_dir,
        "20260101T000000Z-bbbbbbbb",
        with_inputs=False,
        with_scorecard=False,
        with_metadata=False,
        with_report=False,
    )
    with serve_home_ui(sites) as base:
        payload = get_json(base + "/api/run-detail?run_dir=" + str(run_dir))
    assert payload["run_metadata"] is None
    assert payload["scorecard"] is None
    assert payload["report"] is None
    assert payload["inputs"] is None


def test_run_detail_route_404s_for_a_run_dir_outside_the_sites_dir(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    sites.mkdir()
    outside = tmp_path / "outside" / "outputs" / "runs" / "20260101T000000Z-cccccccc"
    outside.mkdir(parents=True)
    with serve_home_ui(sites) as base:
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/run-detail?run_dir=" + str(outside))
    assert error.value.code == 404


def test_run_detail_route_404s_for_a_malformed_run_dir_shape(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    site_dir = sites / "example-site"
    site_dir.mkdir(parents=True)
    with serve_home_ui(sites) as base:
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/run-detail?run_dir=" + str(site_dir))
    assert error.value.code == 404


def test_run_detail_route_404s_for_a_nonexistent_run(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    site_dir = sites / "example-site"
    site_dir.mkdir(parents=True)
    missing_run = site_dir / "outputs" / "runs" / "20260101T000000Z-dddddddd"
    with serve_home_ui(sites) as base:
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/run-detail?run_dir=" + str(missing_run))
    assert error.value.code == 404

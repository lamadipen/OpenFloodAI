from __future__ import annotations

import json
from pathlib import Path

from openfloodai.validation import (
    discover_validation_site_statuses,
    read_validation_site_status,
)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_site(site_dir: Path) -> Path:
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    (site_dir / "outputs").mkdir(parents=True)
    write_json(
        site_dir / "configs" / "site-config.json",
        {
            "site_id": site_dir.name,
            "reference_region": {"x": 0, "y": 50, "width": 100, "height": 50},
        },
    )
    (site_dir / "inputs" / "videos" / "river-001.mp4").write_bytes(b"not-real-video")
    (site_dir / "labels" / "labels.jsonl").write_text(
        (
            '{"video_id":"river-001","time_window_seconds":[0,30],'
            '"human_label":"cannot_judge"}\n'
            '{"video_id":"river-001","time_window_seconds":[30,60],'
            '"human_label":"bridge_pillar_covered"}\n'
        ),
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
    (site_dir / "outputs" / "validation-report.md").write_text(
        "# Site Validation Report\n",
        encoding="utf-8",
    )
    return site_dir


def test_read_validation_site_status_reports_ready_site(tmp_path: Path) -> None:
    site_dir = make_site(tmp_path / "example-site")

    status = read_validation_site_status(site_dir)

    assert status.site_name == "example-site"
    assert status.config_found is True
    assert status.config_count == 1
    assert status.video_count == 1
    assert status.to_dict()["video_ids"] == ["river-001"]
    assert status.labels_found is True
    assert status.label_count == 1
    assert status.human_label_options == ["bridge_pillar_covered", "cannot_judge"]
    assert status.manifest_found is True
    assert status.outputs_found is True
    assert status.report_count == 1
    assert status.latest_report_path == str(site_dir / "outputs" / "validation-report.md")
    assert status.ready_for_machine_review is True
    assert status.ready_for_human_comparison is True
    assert status.ready_for_validation is True
    assert (
        status.machine_review_explanation
        == "Ready because config, videos, and a watched area are found."
    )
    assert (
        status.human_comparison_explanation
        == "Ready because config, videos, labels, and manifest are found."
    )


def test_read_validation_site_status_allows_machine_review_without_labels(
    tmp_path: Path,
) -> None:
    site_dir = tmp_path / "machine-only-site"
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    write_json(
        site_dir / "configs" / "site-config.json",
        {
            "site_id": site_dir.name,
            "reference_region": {"x": 0, "y": 50, "width": 100, "height": 50},
        },
    )
    (site_dir / "inputs" / "videos" / "river-001.mp4").write_bytes(b"not-real-video")

    status = read_validation_site_status(site_dir)

    assert status.ready_for_machine_review is True
    assert status.ready_for_human_comparison is False
    assert status.ready_for_validation is True
    assert status.labels_found is False
    assert status.human_label_options == []
    assert status.manifest_found is False
    assert (
        status.machine_review_explanation
        == "Ready because config, videos, and a watched area are found."
    )
    assert (
        status.human_comparison_explanation == "Not ready because labels and manifest are missing."
    )


def test_read_validation_site_status_reports_missing_files(tmp_path: Path) -> None:
    site_dir = tmp_path / "empty-site"
    site_dir.mkdir()

    status = read_validation_site_status(site_dir)

    assert status.config_found is False
    assert status.video_count == 0
    assert status.video_ids == []
    assert status.labels_found is False
    assert status.manifest_found is False
    assert status.outputs_found is False
    assert status.latest_report_path is None
    assert status.ready_for_machine_review is False
    assert status.ready_for_human_comparison is False
    assert status.ready_for_validation is False
    assert (
        status.machine_review_explanation
        == "Not ready because config, videos, and watched area are missing."
    )
    assert (
        status.human_comparison_explanation
        == "Not ready because config, videos, watched area, labels, and manifest are missing."
    )
    assert "Choose a watched area so validation knows where to look." in status.next_steps


def test_next_steps_explain_when_a_watched_area_is_missing(tmp_path: Path) -> None:
    site_dir = tmp_path / "missing-watched-area"
    (site_dir / "configs").mkdir(parents=True)
    write_json(site_dir / "configs" / "site-config.json", {"site_id": site_dir.name})

    status = read_validation_site_status(site_dir)

    assert status.reference_region_found is False
    assert status.next_steps == [
        "Add video files under inputs/videos/.",
        "Choose a watched area so validation knows where to look.",
        "Machine review can still run, but human comparison needs labels.",
        "Add manifest.jsonl so videos can be tracked clearly.",
        "Run validation to create the first report.",
    ]


def test_discover_validation_site_statuses_lists_site_folders(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    make_site(sites_dir / "b-site")
    make_site(sites_dir / "a-site")
    (sites_dir / "README.md").write_text("# Sites\n", encoding="utf-8")

    statuses = discover_validation_site_statuses(sites_dir)

    assert [status.site_name for status in statuses] == ["a-site", "b-site"]


def test_discover_validation_site_statuses_handles_missing_root(tmp_path: Path) -> None:
    assert discover_validation_site_statuses(tmp_path / "missing") == []


def test_status_to_dict_includes_ready_flag(tmp_path: Path) -> None:
    status = read_validation_site_status(make_site(tmp_path / "example-site"))

    assert status.to_dict()["ready_for_machine_review"] is True
    assert status.to_dict()["ready_for_human_comparison"] is True
    assert status.to_dict()["ready_for_validation"] is True
    assert status.to_dict()["human_label_options"] == [
        "bridge_pillar_covered",
        "cannot_judge",
    ]


def test_video_ids_are_sorted_unique_and_scoped_to_site(tmp_path: Path) -> None:
    site = make_site(tmp_path / "first")
    videos = site / "inputs" / "videos"
    (videos / "river-001.MOV").write_bytes(b"test")
    (videos / "another.mp4").write_bytes(b"test")
    (videos / "ignore.txt").write_text("test")
    (videos / "directory.mp4").mkdir()
    other = make_site(tmp_path / "other")
    (other / "inputs" / "videos" / "other-only.mp4").write_bytes(b"test")

    assert read_validation_site_status(site).video_ids == ["another", "river-001"]

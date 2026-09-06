"""Tests for the pre-run validation readiness summary."""

import json
from pathlib import Path

from openfloodai.validation import read_validation_site_status


def _write_config(site_dir: Path, *, reference_region: bool = True) -> None:
    config: dict[str, object] = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo River Bridge",
        "public_location": "Demo River near Example Town",
        "input_type": "local_video",
    }
    if reference_region:
        config["reference_region"] = {"x": 0, "y": 50, "width": 100, "height": 50}
    configs_dir = site_dir / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    (configs_dir / "site-config.json").write_text(json.dumps(config), encoding="utf-8")


def _add_video(site_dir: Path) -> None:
    videos_dir = site_dir / "inputs" / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    (videos_dir / "rising-001.mp4").write_bytes(b"not a real video")


def _add_labels_and_manifest(site_dir: Path) -> None:
    labels_dir = site_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    (labels_dir / "labels.jsonl").write_text(
        '{"video_id":"rising-001","time_window_seconds":[0,30],"human_label":"water_rising"}\n',
        encoding="utf-8",
    )
    (site_dir / "manifest.jsonl").write_text(
        (
            '{"video_id":"rising-001","filename":"rising-001.mp4","purpose":"practice",'
            '"split":"practice","approved_for_repo":false,"has_human_label":true,'
            '"notes":"Synthetic test metadata."}\n'
        ),
        encoding="utf-8",
    )


def _ready_site(tmp_path: Path) -> Path:
    site_dir = tmp_path / "example-site"
    _write_config(site_dir)
    _add_video(site_dir)
    _add_labels_and_manifest(site_dir)
    return site_dir


def test_full_ready_site_runs_human_comparison(tmp_path: Path) -> None:
    readiness = read_validation_site_status(_ready_site(tmp_path)).validation_readiness

    assert readiness.mode == "full"
    assert readiness.can_run is True
    assert readiness.compares_with_human_labels is True
    assert readiness.missing == []
    assert readiness.headline == "Ready to run. The system will compare with human labels."


def test_missing_labels_gives_a_machine_only_run(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    _write_config(site_dir)
    _add_video(site_dir)

    readiness = read_validation_site_status(site_dir).validation_readiness

    assert readiness.mode == "machine_only"
    assert readiness.can_run is True
    assert readiness.compares_with_human_labels is False
    assert readiness.missing == ["human labels", "manifest"]


def test_machine_only_run_is_labelled_honestly(tmp_path: Path) -> None:
    """A machine-only run must say results stay cannot_compare."""

    site_dir = tmp_path / "example-site"
    _write_config(site_dir)
    _add_video(site_dir)

    readiness = read_validation_site_status(site_dir).validation_readiness
    notes = " ".join(readiness.notes)

    assert "nothing to compare with" in readiness.headline.lower()
    assert "cannot_compare" in notes
    assert "does not show that the system is right" in notes


def test_missing_video_blocks_the_run(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    _write_config(site_dir)

    readiness = read_validation_site_status(site_dir).validation_readiness

    assert readiness.mode == "blocked"
    assert readiness.can_run is False
    assert readiness.missing == ["videos"]
    assert readiness.headline == "Cannot run yet. Something is missing."


def test_missing_config_blocks_the_run(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    site_dir.mkdir()

    readiness = read_validation_site_status(site_dir).validation_readiness

    assert readiness.mode == "blocked"
    assert readiness.missing == ["config", "videos", "watched area"]


def test_missing_watched_area_blocks_the_run(tmp_path: Path) -> None:
    """run_local_video_review needs a reference_region, so a site without one cannot run."""

    site_dir = tmp_path / "example-site"
    _write_config(site_dir, reference_region=False)
    _add_video(site_dir)
    _add_labels_and_manifest(site_dir)

    status = read_validation_site_status(site_dir)

    assert status.ready_for_machine_review is False
    assert status.ready_for_validation is False
    assert status.validation_readiness.mode == "blocked"
    assert status.validation_readiness.missing == ["watched area"]


def test_blocked_run_says_nothing_is_processed(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    site_dir.mkdir()

    notes = " ".join(read_validation_site_status(site_dir).validation_readiness.notes)

    assert "Add the missing items above" in notes
    assert "no report is saved yet" in notes.lower()


def test_readiness_lists_every_input_the_run_depends_on(tmp_path: Path) -> None:
    readiness = read_validation_site_status(_ready_site(tmp_path)).validation_readiness

    assert [check.label for check in readiness.checks] == [
        "Site config",
        "Videos",
        "Watched area",
        "Human labels",
        "Manifest",
        "Output",
    ]
    assert all(check.ok for check in readiness.checks)


def test_readiness_shows_counts_not_just_found(tmp_path: Path) -> None:
    checks = {
        check.label: check.value
        for check in read_validation_site_status(_ready_site(tmp_path)).validation_readiness.checks
    }

    assert checks["Videos"] == "1 found"
    assert checks["Human labels"] == "1 label file(s) found"
    assert checks["Output"] == "Saved on this computer"


def test_readiness_is_serialized_for_the_home_ui(tmp_path: Path) -> None:
    payload = read_validation_site_status(_ready_site(tmp_path)).to_dict()
    readiness = payload["validation_readiness"]

    assert readiness["mode"] == "full"
    assert readiness["can_run"] is True
    assert readiness["compares_with_human_labels"] is True
    assert readiness["checks"][0] == {"label": "Site config", "value": "Found", "ok": True}

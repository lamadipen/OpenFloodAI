"""Tests for the guided local validation workflow steps."""

import json
from pathlib import Path

from openfloodai.validation import WorkflowStep, read_validation_site_status

EXPECTED_STEP_KEYS = [
    "site_setup",
    "video_intake",
    "watched_area",
    "human_labels",
    "manifest",
    "run_validation",
    "review_results",
]


def _write_config(site_dir: Path, *, reference_region: bool) -> None:
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


def _steps_by_key(site_dir: Path) -> dict[str, WorkflowStep]:
    status = read_validation_site_status(site_dir)
    return {step.key: step for step in status.workflow_steps}


def _action_ids(step: WorkflowStep) -> list[str]:
    return [action.action_id for action in step.actions]


def _action_labels(step: WorkflowStep) -> list[str]:
    return [action.label for action in step.actions]


def test_workflow_lists_every_expected_step_in_order(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    site_dir.mkdir()

    steps = read_validation_site_status(site_dir).workflow_steps

    assert [step.key for step in steps] == EXPECTED_STEP_KEYS
    assert [step.number for step in steps] == [1, 2, 3, 4, 5, 6, 7]


def test_empty_site_shows_required_steps_as_missing(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    site_dir.mkdir()

    steps = _steps_by_key(site_dir)

    assert steps["site_setup"].status == "missing"
    assert steps["video_intake"].status == "missing"
    assert steps["watched_area"].status == "missing"
    assert steps["run_validation"].status == "missing"


def test_missing_labels_and_manifest_are_needs_review_not_missing(tmp_path: Path) -> None:
    """Machine review can still run without labels, so these are not hard blockers."""

    site_dir = tmp_path / "example-site"
    _write_config(site_dir, reference_region=True)
    _add_video(site_dir)

    steps = _steps_by_key(site_dir)

    assert steps["human_labels"].status == "needs_review"
    assert steps["manifest"].status == "needs_review"
    assert steps["human_labels"].required_for_validation is False
    assert steps["manifest"].required_for_validation is False


def test_watched_area_is_required_because_validation_needs_it(tmp_path: Path) -> None:
    """run_local_video_review raises without a reference_region, so the step is required."""

    site_dir = tmp_path / "example-site"
    _write_config(site_dir, reference_region=False)
    _add_video(site_dir)

    steps = _steps_by_key(site_dir)

    assert steps["watched_area"].status == "missing"
    assert steps["watched_area"].required_for_validation is True


def test_watched_area_completes_when_config_has_reference_region(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    _write_config(site_dir, reference_region=True)

    status = read_validation_site_status(site_dir)

    assert status.reference_region_found is True
    assert _steps_by_key(site_dir)["watched_area"].status == "complete"


def test_unreadable_config_does_not_report_a_watched_area(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    configs_dir = site_dir / "configs"
    configs_dir.mkdir(parents=True)
    (configs_dir / "broken.json").write_text("{ not json", encoding="utf-8")

    status = read_validation_site_status(site_dir)

    assert status.reference_region_found is False


def test_every_step_has_action_and_plain_language_meaning(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    site_dir.mkdir()

    for step in read_validation_site_status(site_dir).workflow_steps:
        assert step.title
        assert step.meaning
        assert step.actions
        assert all(action.label and action.action_id for action in step.actions)
        assert step.status_text in {"Complete", "Missing", "Needs review"}


def test_workflow_steps_are_serialized_for_the_home_ui(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    _write_config(site_dir, reference_region=True)

    payload = read_validation_site_status(site_dir).to_dict()

    assert payload["reference_region_found"] is True
    assert [step["key"] for step in payload["workflow_steps"]] == EXPECTED_STEP_KEYS
    first_step = payload["workflow_steps"][0]
    assert first_step["status_text"] == "Complete"
    assert first_step["required_for_validation"] is True
    assert [action["action_id"] for action in first_step["actions"]] == [
        "select_site",
        "create_site",
    ]


def test_configured_site_offers_both_select_and_create(tmp_path: Path) -> None:
    """A finished site should let you switch sites, not only make another one."""

    site_dir = tmp_path / "example-site"
    _write_config(site_dir, reference_region=True)

    step = _steps_by_key(site_dir)["site_setup"]

    assert step.status == "complete"
    assert _action_ids(step) == ["select_site", "create_site"]
    assert _action_labels(step) == ["Select site", "Create another site"]


def test_site_without_config_offers_only_creation(tmp_path: Path) -> None:
    """There is nothing to select yet, so a new site gets a single action."""

    site_dir = tmp_path / "example-site"
    site_dir.mkdir()

    step = _steps_by_key(site_dir)["site_setup"]

    assert step.status == "missing"
    assert _action_ids(step) == ["create_site"]
    assert _action_labels(step) == ["Create site"]


def test_video_step_offers_select_only_when_videos_exist(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    _write_config(site_dir, reference_region=True)

    assert _action_ids(_steps_by_key(site_dir)["video_intake"]) == ["add_video"]

    _add_video(site_dir)

    assert _action_ids(_steps_by_key(site_dir)["video_intake"]) == [
        "select_video",
        "add_video",
    ]


def test_label_step_offers_select_only_when_labels_exist(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    _write_config(site_dir, reference_region=True)

    assert _action_ids(_steps_by_key(site_dir)["human_labels"]) == ["add_label"]

    labels_dir = site_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    (labels_dir / "labels.jsonl").write_text(
        '{"video_id":"rising-001","time_window_seconds":[0,30],"human_label":"water_rising"}\n',
        encoding="utf-8",
    )

    assert _action_ids(_steps_by_key(site_dir)["human_labels"]) == [
        "select_label",
        "add_label",
    ]


def test_watched_area_step_says_where_the_selector_actually_lives(tmp_path: Path) -> None:
    """The selector ships inside video intake, so the step must not imply a standalone tool."""

    site_dir = tmp_path / "example-site"
    _write_config(site_dir, reference_region=False)
    _add_video(site_dir)

    step = _steps_by_key(site_dir)["watched_area"]

    assert _action_labels(step) == ["Set area in video intake"]
    assert _action_ids(step) == ["add_video"]
    assert "when you add a video" in step.meaning

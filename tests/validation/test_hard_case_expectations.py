from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.validation import render_site_validation_report, run_site_validation

HARD_CASE_FIXTURE = Path("data/sites/example-site/expected-behavior/hard-cases.jsonl")


def load_hard_case_records() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in HARD_CASE_FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_site_config(path: Path) -> None:
    config = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo River Bridge",
        "public_location": "Demo River near Example Town",
        "input_type": "local_video",
        "reference_region": {
            "x": 0,
            "y": 0,
            "width": 100,
            "height": 100,
        },
        "privacy_notes": "Synthetic test config only.",
    }
    path.write_text(json.dumps(config), encoding="utf-8")


def write_labels(path: Path) -> None:
    rows = [
        {
            "video_id": "rising-001",
            "time_window_seconds": [0, 30],
            "human_label": "water_rising",
        },
        {
            "video_id": "rising-001",
            "time_window_seconds": [30, 60],
            "human_label": "cannot_judge",
        },
        {
            "video_id": "normal-001",
            "time_window_seconds": [0, 30],
            "human_label": "water_rising",
        },
        {
            "video_id": "unclear-001",
            "time_window_seconds": [0, 30],
            "human_label": "cannot_judge",
        },
        {
            "video_id": "missing-001",
            "time_window_seconds": [0, 30],
            "human_label": "water_rising",
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_hard_case_expectations_are_plain_and_safe() -> None:
    records = load_hard_case_records()

    assert {record["case_type"] for record in records} >= {
        "missing_video",
        "empty_video",
        "unreadable_video",
        "camera_offline",
        "heavy_glare",
        "rain_or_noisy_image",
        "night_or_dark_frame",
        "camera_shake",
        "blocked_view",
        "compression_or_noise_artifacts",
    }

    for record in records:
        assert set(record) == {
            "case_id",
            "case_type",
            "input_quality_state",
            "validation_result",
            "plain_reason",
        }
        assert record["input_quality_state"] in {"USABLE", "DEGRADED", "UNKNOWN"}
        assert record["validation_result"] in {"agree", "disagree", "cannot_compare"}
        assert record["validation_result"] != "agree"
        assert isinstance(record["plain_reason"], str)
        assert record["plain_reason"].strip()


@pytest.mark.parametrize(
    ("case_type", "expected_quality_state"),
    [
        ("missing_video", "UNKNOWN"),
        ("empty_video", "UNKNOWN"),
        ("unreadable_video", "UNKNOWN"),
        ("camera_offline", "UNKNOWN"),
        ("heavy_glare", "DEGRADED"),
        ("rain_or_noisy_image", "DEGRADED"),
        ("night_or_dark_frame", "DEGRADED"),
        ("camera_shake", "DEGRADED"),
        ("blocked_view", "DEGRADED"),
        ("compression_or_noise_artifacts", "DEGRADED"),
    ],
)
def test_hard_case_fixture_records_expected_quality_state(
    case_type: str,
    expected_quality_state: str,
) -> None:
    records_by_case_type = {record["case_type"]: record for record in load_hard_case_records()}

    assert records_by_case_type[case_type]["input_quality_state"] == expected_quality_state


def test_unreadable_video_stays_visible_as_cannot_compare(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    write_site_config(site_dir / "configs" / "site-config.json")
    write_labels(site_dir / "labels" / "labels.jsonl")
    (site_dir / "inputs" / "videos" / "bad-001.mp4").write_text(
        "not a video",
        encoding="utf-8",
    )

    report = run_site_validation(site_dir)
    rendered = render_site_validation_report(report)
    result = report.results[0]

    assert result.video_id == "bad-001"
    assert result.processed is False
    assert result.system_result == "processing_failed"
    assert result.result == "cannot_compare"
    assert report.agree_count == 0
    assert report.cannot_compare_count == 6
    assert "bad-001.mp4 | no | missing | processing_failed | cannot_compare" in rendered
    assert "Cases marked `cannot_compare` are not counted as success." in rendered

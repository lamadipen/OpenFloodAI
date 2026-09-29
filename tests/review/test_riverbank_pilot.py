from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.review import (
    RiverbankPilotError,
    evaluate_riverbank_pilot,
    evaluate_riverbank_pilot_files,
    render_riverbank_pilot_report,
)


def evidence(
    record_id: str,
    *,
    status: str = "available",
    value: float | None = 0.0,
    processing_time_ms: float | None = None,
    memory_bytes: int | None = None,
) -> dict[str, object]:
    quality: dict[str, object] = {}
    if processing_time_ms is not None:
        quality["processing_time_ms"] = processing_time_ms
    if memory_bytes is not None:
        quality["estimated_frame_memory_bytes"] = memory_bytes
    return {
        "record_id": record_id,
        "plugin_id": "riverbank_crossing_v1",
        "status": status,
        "value": value if status == "available" else None,
        "quality": quality,
    }


def review(
    observation_id: str,
    evidence_record_id: str,
    expected_result: str,
    conditions: list[str],
    *,
    overlay_review: str = "not_reviewed",
    false_crossing_cause: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "observation_id": observation_id,
        "evidence_record_id": evidence_record_id,
        "expected_result": expected_result,
        "conditions": conditions,
        "overlay_review": overlay_review,
    }
    if false_crossing_cause is not None:
        record["false_crossing_cause"] = false_crossing_cause
    return record


def test_evaluates_metrics_cost_failures_conditions_and_overlay_reviews() -> None:
    report = evaluate_riverbank_pilot(
        evidence_records=[
            evidence("e1", value=25, processing_time_ms=2, memory_bytes=1_000_000),
            evidence("e2", value=10, processing_time_ms=4, memory_bytes=2_000_000),
            evidence("e3", value=0, processing_time_ms=6, memory_bytes=3_000_000),
            evidence("e4", value=0, processing_time_ms=8, memory_bytes=4_000_000),
            evidence("e5", status="failed", value=None),
            evidence("e6", value=0),
        ],
        reviewed_observations=[
            review("o1", "e1", "change", ["muddy_water", "summer"], overlay_review="accepted"),
            review(
                "o2",
                "e2",
                "no_change",
                ["camera_movement", "clear_water"],
                overlay_review="rejected",
                false_crossing_cause="camera_movement",
            ),
            review("o3", "e3", "change", ["low_light", "winter"]),
            review("o4", "e4", "no_change", ["shadows", "vegetation"], overlay_review="accepted"),
            review("o5", "e5", "change", ["glare"]),
            review("o6", "e6", "unclear", ["snow"]),
        ],
    )

    assert report.reviewed_count == 6
    assert report.available_count == 5
    assert report.unavailable_or_failure_count == 1
    assert report.unavailable_or_failure_rate == pytest.approx(1 / 6)
    assert report.unclear_count == 1
    assert report.metrics.sample_count == 4
    assert report.metrics.precision == 0.5
    assert report.metrics.recall == 0.5
    assert report.metrics.false_crossing_rate == 0.5
    assert report.metrics.false_positive == 1
    assert report.false_crossing_causes == {"camera_movement": 1}
    assert report.overlay_acceptance_rate == pytest.approx(2 / 3)
    assert report.processing_cost.mean_processing_time_ms == 5
    assert report.processing_cost.p95_processing_time_ms == 8
    assert report.processing_cost.mean_estimated_frame_memory_bytes == 2_500_000
    assert report.processing_cost.max_estimated_frame_memory_bytes == 4_000_000

    movement = next(
        metric for metric in report.condition_metrics if metric.condition == "camera_movement"
    )
    assert movement.reviewed_count == 1
    assert movement.metrics.false_positive == 1


def test_missing_evidence_is_a_visible_failure_not_a_negative_prediction() -> None:
    report = evaluate_riverbank_pilot(
        evidence_records=[],
        reviewed_observations=[review("o1", "missing", "change", ["glare"])],
    )

    assert report.matched_count == 0
    assert report.unavailable_or_failure_rate == 1.0
    assert report.metrics.sample_count == 0
    assert report.metrics.precision is None
    assert report.samples[0].system_result == "unavailable"
    assert report.samples[0].outcome == "cannot_compare"


def test_render_report_uses_safety_wording_and_marks_untested_slices() -> None:
    report = evaluate_riverbank_pilot(
        evidence_records=[evidence("e1", value=0)],
        reviewed_observations=[review("o1", "e1", "no_change", ["clear_water"])],
    )

    rendered = render_riverbank_pilot_report(report)

    assert "Precision: Not available" in rendered
    assert "| muddy_water | 0 | 0 | Not available | Not available | 0 |" in rendered
    assert "does not confirm flooding" in rendered
    assert "not tested" in rendered
    assert "Human review and independent evidence remain required" in rendered


def test_rejects_unknown_conditions_and_duplicate_observations() -> None:
    with pytest.raises(RiverbankPilotError, match="every condition"):
        evaluate_riverbank_pilot(
            evidence_records=[],
            reviewed_observations=[review("o1", "e1", "change", ["sunny"])],
        )

    duplicate = review("same", "e1", "change", ["glare"])
    with pytest.raises(RiverbankPilotError, match="duplicate observation_id"):
        evaluate_riverbank_pilot(
            evidence_records=[evidence("e1", value=1)],
            reviewed_observations=[duplicate, duplicate],
        )


def test_reads_jsonl_files(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.jsonl"
    reviews_path = tmp_path / "reviews.jsonl"
    evidence_path.write_text(json.dumps(evidence("e1", value=12)) + "\n", encoding="utf-8")
    reviews_path.write_text(
        json.dumps(review("o1", "e1", "change", ["high_water"])) + "\n",
        encoding="utf-8",
    )

    report = evaluate_riverbank_pilot_files(
        evidence_path=evidence_path,
        reviewed_observations_path=reviews_path,
    )

    assert report.metrics.true_positive == 1


def test_rejects_an_available_evidence_record_without_a_numeric_value() -> None:
    with pytest.raises(RiverbankPilotError, match="invalid available value"):
        evaluate_riverbank_pilot(
            evidence_records=[evidence("e1", value=None)],
            reviewed_observations=[review("o1", "e1", "change", ["high_water"])],
        )

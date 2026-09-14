from __future__ import annotations

import pytest

from openfloodai.review import (
    ALLOWED_FAILURE_REASONS,
    compute_failure_reason,
    find_matching_label,
    friendly_failure_reason,
    is_baseline_ready,
    is_normal_baseline_confirmed,
    summarize_sample_quality,
)

CONFIRMED = {"status": "confirmed", "normal_condition": True}
CONFIRMED_NOT_NORMAL = {"status": "confirmed", "normal_condition": False}
DRAFT = {"status": "draft", "normal_condition": True}


@pytest.mark.parametrize(
    ("record", "confirmed_reference", "expected_reason"),
    [
        ({"riverbank_visible": "no"}, CONFIRMED, "riverbank_not_visible"),
        ({"stable_marker_visible": "no"}, CONFIRMED, None),
        ({"visibility_condition": "obstruction"}, CONFIRMED, "obstructed_view"),
        ({"camera_stable": "no"}, CONFIRMED, "camera_moved"),
        ({"water_boundary_visible": "no"}, CONFIRMED, "water_boundary_unclear"),
        ({"visibility_condition": "dark"}, CONFIRMED, "poor_visibility"),
        ({"visibility_condition": "glare"}, CONFIRMED, "poor_visibility"),
        ({}, DRAFT, "baseline_not_confirmed"),
        ({}, None, "baseline_not_confirmed"),
        ({}, CONFIRMED, None),
        ({}, CONFIRMED_NOT_NORMAL, "baseline_not_confirmed"),
    ],
)
def test_compute_failure_reason_priority_order(
    record: dict[str, str],
    confirmed_reference: dict[str, str] | None,
    expected_reason: str | None,
) -> None:
    assert compute_failure_reason(record, confirmed_reference) == expected_reason


def test_compute_failure_reason_higher_priority_wins_over_lower() -> None:
    record = {"riverbank_visible": "no", "camera_stable": "no"}

    assert compute_failure_reason(record, CONFIRMED) == "riverbank_not_visible"


def test_compute_failure_reason_ignores_unsure_and_missing() -> None:
    record = {
        "riverbank_visible": "unsure",
        "stable_marker_visible": "unsure",
        "water_boundary_visible": "unsure",
        "camera_stable": "unsure",
    }

    assert compute_failure_reason(record, CONFIRMED) is None


@pytest.mark.parametrize(
    ("confirmed_reference", "expected"),
    [
        (CONFIRMED, True),
        (CONFIRMED_NOT_NORMAL, False),
        ({"status": "confirmed"}, False),
        (DRAFT, False),
        ({"status": "invalid", "normal_condition": True}, False),
        (None, False),
        ({}, False),
    ],
)
def test_is_normal_baseline_confirmed_reads_status(
    confirmed_reference: dict[str, object] | None, expected: bool
) -> None:
    assert is_normal_baseline_confirmed(confirmed_reference) is expected


def test_stable_marker_visible_is_optional_evidence_not_a_requirement() -> None:
    record = {
        "riverbank_visible": "yes",
        "water_boundary_visible": "yes",
        "stable_marker_visible": "no",
    }

    assert compute_failure_reason(record, CONFIRMED) is None
    assert is_baseline_ready(record, CONFIRMED) is True


def test_is_baseline_ready_requires_explicit_yes_on_core_fields() -> None:
    record = {
        "riverbank_visible": "unsure",
        "water_boundary_visible": "yes",
    }

    assert compute_failure_reason(record, CONFIRMED) is None
    assert is_baseline_ready(record, CONFIRMED) is False


def test_is_baseline_ready_true_case() -> None:
    record = {
        "riverbank_visible": "yes",
        "stable_marker_visible": "unsure",
        "water_boundary_visible": "yes",
        "camera_stable": "unsure",
        "visibility_condition": "clear",
    }

    assert is_baseline_ready(record, CONFIRMED) is True


def test_is_baseline_ready_false_when_baseline_not_confirmed() -> None:
    record = {"riverbank_visible": "yes", "water_boundary_visible": "yes"}

    assert is_baseline_ready(record, DRAFT) is False


def test_summarize_sample_quality_counts_and_reasons() -> None:
    records = [
        {"riverbank_visible": "yes", "water_boundary_visible": "yes"},
        {"riverbank_visible": "no"},
        {"riverbank_visible": "no"},
        {"camera_stable": "no"},
    ]

    summary = summarize_sample_quality(records, CONFIRMED)

    assert summary.total_samples == 4
    assert summary.baseline_ready_count == 1
    assert summary.practice_only_count == 3
    assert summary.failure_reason_counts == [
        ("riverbank_not_visible", 2),
        ("camera_moved", 1),
    ]


def test_summarize_sample_quality_empty_list() -> None:
    summary = summarize_sample_quality([], CONFIRMED)

    assert summary.total_samples == 0
    assert summary.baseline_ready_count == 0
    assert summary.practice_only_count == 0
    assert summary.failure_reason_counts == []


def test_friendly_failure_reason_covers_all_codes() -> None:
    seen_texts = set()
    for reason in ALLOWED_FAILURE_REASONS:
        text = friendly_failure_reason(reason)
        assert text
        assert text != reason
        seen_texts.add(text)
    assert len(seen_texts) == len(ALLOWED_FAILURE_REASONS)


def test_friendly_failure_reason_handles_none() -> None:
    assert friendly_failure_reason(None) == "No reference-quality issue was recorded."


def test_find_matching_label_matches_video_and_window() -> None:
    labels = [
        {"video_id": "rising-001", "time_window_seconds": [0, 30], "human_label": "water_rising"},
        {"video_id": "rising-001", "time_window_seconds": [30, 60], "human_label": "cannot_judge"},
        {"video_id": "other-001", "time_window_seconds": [0, 30], "human_label": "no_clear_change"},
    ]

    match = find_matching_label(labels, video_id="rising-001", time_window_seconds=(30.0, 60.0))

    assert match is not None
    assert match["human_label"] == "cannot_judge"


def test_find_matching_label_returns_none_when_no_exact_match() -> None:
    labels = [
        {"video_id": "rising-001", "time_window_seconds": [0, 30], "human_label": "water_rising"}
    ]

    assert (
        find_matching_label(labels, video_id="rising-001", time_window_seconds=(5.0, 25.0)) is None
    )
    assert (
        find_matching_label(labels, video_id="other-001", time_window_seconds=(0.0, 30.0)) is None
    )


def test_find_matching_label_ignores_malformed_windows() -> None:
    labels: list[dict[str, object]] = [
        {"video_id": "rising-001", "time_window_seconds": "not-a-list"},
        {"video_id": "rising-001", "time_window_seconds": [0]},
        {"video_id": "rising-001"},
    ]

    assert (
        find_matching_label(labels, video_id="rising-001", time_window_seconds=(0.0, 30.0)) is None
    )

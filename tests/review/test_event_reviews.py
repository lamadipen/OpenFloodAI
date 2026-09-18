from __future__ import annotations

from pathlib import Path

import pytest

from openfloodai.review.event_reviews import (
    EventReviewError,
    compute_evidence_key,
    list_event_reviews,
    set_event_review,
)

EVIDENCE = compute_evidence_key("baseline.jpg", {"top": 0, "left": 0, "width": 10, "height": 10})
OTHER_EVIDENCE = compute_evidence_key(
    "other-baseline.jpg", {"top": 0, "left": 0, "width": 10, "height": 10}
)


def test_list_event_reviews_returns_empty_when_no_file(tmp_path: Path) -> None:
    assert list_event_reviews(tmp_path, evidence_key=EVIDENCE) == {}


def test_set_event_review_records_and_lists_status(tmp_path: Path) -> None:
    record = set_event_review(
        tmp_path,
        event_key="2026-06-20-2026-06-23-P",
        status="confirmed_real",
        evidence_key=EVIDENCE,
    )
    assert record.status == "confirmed_real"

    assert list_event_reviews(tmp_path, evidence_key=EVIDENCE) == {
        "2026-06-20-2026-06-23-P": "confirmed_real"
    }


def test_set_event_review_rejects_invalid_status(tmp_path: Path) -> None:
    with pytest.raises(EventReviewError):
        set_event_review(
            tmp_path, event_key="2026-06-20-2026-06-23-P", status="bogus", evidence_key=EVIDENCE
        )


def test_set_event_review_rejects_empty_key(tmp_path: Path) -> None:
    with pytest.raises(EventReviewError):
        set_event_review(tmp_path, event_key="   ", status="acknowledged", evidence_key=EVIDENCE)


def test_set_event_review_can_change_status(tmp_path: Path) -> None:
    set_event_review(tmp_path, event_key="k1", status="confirmed_real", evidence_key=EVIDENCE)
    set_event_review(tmp_path, event_key="k1", status="not_real", evidence_key=EVIDENCE)

    assert list_event_reviews(tmp_path, evidence_key=EVIDENCE) == {"k1": "not_real"}


def test_set_event_review_undo_clears_status(tmp_path: Path) -> None:
    set_event_review(tmp_path, event_key="k1", status="acknowledged", evidence_key=EVIDENCE)
    set_event_review(tmp_path, event_key="k1", status=None, evidence_key=EVIDENCE)

    assert list_event_reviews(tmp_path, evidence_key=EVIDENCE) == {}


def test_event_reviews_are_independent_per_key(tmp_path: Path) -> None:
    set_event_review(tmp_path, event_key="k1", status="confirmed_real", evidence_key=EVIDENCE)
    set_event_review(tmp_path, event_key="k2", status="acknowledged", evidence_key=EVIDENCE)

    assert list_event_reviews(tmp_path, evidence_key=EVIDENCE) == {
        "k1": "confirmed_real",
        "k2": "acknowledged",
    }


def test_event_reviews_are_independent_per_sequence_directory(tmp_path: Path) -> None:
    seq_a = tmp_path / "seq-a"
    seq_b = tmp_path / "seq-b"
    set_event_review(seq_a, event_key="k1", status="confirmed_real", evidence_key=EVIDENCE)

    assert list_event_reviews(seq_a, evidence_key=EVIDENCE) == {"k1": "confirmed_real"}
    assert list_event_reviews(seq_b, evidence_key=EVIDENCE) == {}


def test_compute_evidence_key_changes_with_baseline_or_watched_area() -> None:
    region = {"top": 0, "left": 0, "width": 10, "height": 10}
    base = compute_evidence_key("a.jpg", region)
    assert compute_evidence_key("b.jpg", region) != base
    assert compute_evidence_key("a.jpg", {**region, "top": 5}) != base
    assert compute_evidence_key("a.jpg", region) == base


def test_a_review_does_not_carry_over_when_the_baseline_or_watched_area_changes(
    tmp_path: Path,
) -> None:
    # A human confirms a real change against the original baseline/watched area.
    set_event_review(
        tmp_path,
        event_key="2026-06-20-2026-06-23-P",
        status="confirmed_real",
        evidence_key=EVIDENCE,
    )
    assert list_event_reviews(tmp_path, evidence_key=EVIDENCE) == {
        "2026-06-20-2026-06-23-P": "confirmed_real"
    }

    # The baseline (or watched area) is changed and validation rerun, producing
    # the same event_key (same dates/result code) but different evidence. The
    # old "confirmed real" must not silently apply to the new comparison.
    assert list_event_reviews(tmp_path, evidence_key=OTHER_EVIDENCE) == {}

    # Reverting to the original evidence must resurface the original review —
    # nothing was lost, it's just not trusted under evidence it wasn't made for.
    assert list_event_reviews(tmp_path, evidence_key=EVIDENCE) == {
        "2026-06-20-2026-06-23-P": "confirmed_real"
    }

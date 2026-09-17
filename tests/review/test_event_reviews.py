from __future__ import annotations

from pathlib import Path

import pytest

from openfloodai.review.event_reviews import (
    EventReviewError,
    list_event_reviews,
    set_event_review,
)


def test_list_event_reviews_returns_empty_when_no_file(tmp_path: Path) -> None:
    assert list_event_reviews(tmp_path) == {}


def test_set_event_review_records_and_lists_status(tmp_path: Path) -> None:
    record = set_event_review(
        tmp_path, event_key="2026-06-20-2026-06-23-P", status="confirmed_real"
    )
    assert record.status == "confirmed_real"

    assert list_event_reviews(tmp_path) == {"2026-06-20-2026-06-23-P": "confirmed_real"}


def test_set_event_review_rejects_invalid_status(tmp_path: Path) -> None:
    with pytest.raises(EventReviewError):
        set_event_review(tmp_path, event_key="2026-06-20-2026-06-23-P", status="bogus")


def test_set_event_review_rejects_empty_key(tmp_path: Path) -> None:
    with pytest.raises(EventReviewError):
        set_event_review(tmp_path, event_key="   ", status="acknowledged")


def test_set_event_review_can_change_status(tmp_path: Path) -> None:
    set_event_review(tmp_path, event_key="k1", status="confirmed_real")
    set_event_review(tmp_path, event_key="k1", status="not_real")

    assert list_event_reviews(tmp_path) == {"k1": "not_real"}


def test_set_event_review_undo_clears_status(tmp_path: Path) -> None:
    set_event_review(tmp_path, event_key="k1", status="acknowledged")
    set_event_review(tmp_path, event_key="k1", status=None)

    assert list_event_reviews(tmp_path) == {}


def test_event_reviews_are_independent_per_key(tmp_path: Path) -> None:
    set_event_review(tmp_path, event_key="k1", status="confirmed_real")
    set_event_review(tmp_path, event_key="k2", status="acknowledged")

    assert list_event_reviews(tmp_path) == {"k1": "confirmed_real", "k2": "acknowledged"}


def test_event_reviews_are_independent_per_sequence_directory(tmp_path: Path) -> None:
    seq_a = tmp_path / "seq-a"
    seq_b = tmp_path / "seq-b"
    set_event_review(seq_a, event_key="k1", status="confirmed_real")

    assert list_event_reviews(seq_a) == {"k1": "confirmed_real"}
    assert list_event_reviews(seq_b) == {}

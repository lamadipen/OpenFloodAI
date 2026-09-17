"""Per-event review-status persistence for image-sequence review (issue #152).

Distinct from `dataset_groups.py`: that tracks whole date ranges for a
site's data moving through development/practice/locked_validation/excluded.
This tracks a much smaller-grained thing — whether a human has looked at
one machine-detected event (a run of consecutive same-result days) and
confirmed, dismissed, or acknowledged it — so review effort compounds
across sessions instead of resetting every time the page reloads.

Stored per sequence (not per validation run), keyed by an event key built
from its date range and result code, so marks stay attached to the same
event even after re-running validation on the same downloaded images.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from openfloodai.contracts import read_jsonl_records, write_jsonl_records

ALLOWED_EVENT_REVIEW_STATUSES = {"confirmed_real", "not_real", "acknowledged"}
_CLEARED_STATUS = "cleared"
_EVENT_REVIEWS_FILENAME = "event-reviews.jsonl"


class EventReviewError(ValueError):
    """Raised when an event-review update is invalid."""


@dataclass(frozen=True)
class EventReviewRecord:
    """One review-status change for one event."""

    event_key: str
    status: str
    reviewed_at_utc: str


def set_event_review(
    sequence_dir: Path, *, event_key: str, status: str | None
) -> EventReviewRecord:
    """Record a review status for one event, or clear it when `status` is None.

    Appends rather than overwrites — `list_event_reviews` reduces to the
    latest status per event key, so this stays a plain append-only log like
    the rest of this project's JSONL records.
    """

    if not event_key.strip():
        raise EventReviewError("event_key must be non-empty.")
    if status is not None and status not in ALLOWED_EVENT_REVIEW_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_EVENT_REVIEW_STATUSES))
        raise EventReviewError(f"Invalid review status: use one of {allowed}, or null to clear.")

    record = EventReviewRecord(
        event_key=event_key,
        status=status if status is not None else _CLEARED_STATUS,
        reviewed_at_utc=datetime.now(UTC).isoformat(),
    )
    write_jsonl_records(sequence_dir / _EVENT_REVIEWS_FILENAME, [asdict(record)])
    return record


def list_event_reviews(sequence_dir: Path) -> dict[str, str]:
    """Return the current status for every reviewed event, keyed by event_key.

    An event whose latest recorded status is `cleared` (an undo) is left
    out entirely, matching an event that was never reviewed.
    """

    path = sequence_dir / _EVENT_REVIEWS_FILENAME
    if not path.is_file():
        return {}
    try:
        records = read_jsonl_records(path)
    except ValueError as error:
        raise EventReviewError(f"Could not read {path}: {error}") from error

    latest: dict[str, str] = {}
    for record in records:
        event_key = str(record.get("event_key", ""))
        if not event_key:
            continue
        latest[event_key] = str(record.get("status", _CLEARED_STATUS))
    return {key: status for key, status in latest.items() if status != _CLEARED_STATUS}

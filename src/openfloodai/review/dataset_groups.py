"""Dataset-group assignments for a site's image-sequence data (issue #152).

Distinct from the existing per-video `manifest.jsonl` practice/locked
split: this tracks whole date ranges of a site's downloaded image
sequences as they move from development through human review into
`practice`, `locked_validation`, or `excluded`. A date with no assignment
is implicitly `development_candidate` — the starting state for all pilot
data.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from openfloodai.contracts import read_jsonl_records, write_jsonl_records

ALLOWED_DATASET_GROUPS = {"development_candidate", "practice", "locked_validation", "excluded"}
DEFAULT_DATASET_GROUP = "development_candidate"
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATASET_GROUPS_FILENAME = "dataset-groups.jsonl"


class DatasetGroupError(ValueError):
    """Raised when a dataset-group assignment is invalid."""


@dataclass(frozen=True)
class DatasetGroupAssignment:
    """One (group, date range) assignment for a site."""

    group: str
    start_date: str
    end_date: str
    note: str
    assigned_at_utc: str


def _parse_date(value: str, *, field: str) -> date:
    if not _DATE_PATTERN.fullmatch(value):
        raise DatasetGroupError(f"{field} must be a date as YYYY-MM-DD.")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise DatasetGroupError(f"{field} is not a valid calendar date.") from error


def _ranges_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def list_dataset_group_assignments(site_dir: Path) -> list[DatasetGroupAssignment]:
    """Return every dataset-group assignment recorded for a site, oldest first."""

    path = site_dir / _DATASET_GROUPS_FILENAME
    if not path.is_file():
        return []
    try:
        records = read_jsonl_records(path)
    except ValueError as error:
        raise DatasetGroupError(f"Could not read {path}: {error}") from error
    return [
        DatasetGroupAssignment(
            group=str(record.get("group")),
            start_date=str(record.get("start_date")),
            end_date=str(record.get("end_date")),
            note=str(record.get("note", "")),
            assigned_at_utc=str(record.get("assigned_at_utc")),
        )
        for record in records
    ]


def assign_dataset_group(
    site_dir: Path, *, group: str, start_date: str, end_date: str, note: str = ""
) -> DatasetGroupAssignment:
    """Assign a date range to a dataset group.

    A PARTIAL overlap with an existing assignment is refused: it would
    leave it ambiguous which group the non-overlapping days belong to.
    A new range that fully CONTAINS one or more existing assignments is
    allowed — that is an unambiguous, deliberate promotion/re-grouping of
    that whole range (e.g. `practice` -> `locked_validation`), and
    `dataset_group_for_date` always resolves an overlap to the most
    recently assigned covering range, so the new group takes effect.
    """

    if group not in ALLOWED_DATASET_GROUPS:
        allowed = ", ".join(sorted(ALLOWED_DATASET_GROUPS))
        raise DatasetGroupError(f"Invalid dataset group: use one of {allowed}.")
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    if end < start:
        raise DatasetGroupError("end_date must be on or after start_date.")

    existing = list_dataset_group_assignments(site_dir)
    for assignment in existing:
        other_start = _parse_date(assignment.start_date, field="start_date")
        other_end = _parse_date(assignment.end_date, field="end_date")
        if _ranges_overlap(start, end, other_start, other_end) and not (
            start <= other_start and other_end <= end
        ):
            raise DatasetGroupError(
                f"{start_date} to {end_date} partially overlaps an existing '{assignment.group}' "
                f"assignment ({assignment.start_date} to {assignment.end_date}). "
                "Narrow the range, or cover that whole assignment's range to replace it."
            )

    assignment = DatasetGroupAssignment(
        group=group,
        start_date=start_date,
        end_date=end_date,
        note=note,
        assigned_at_utc=datetime.now(UTC).isoformat(),
    )
    # write_jsonl_records appends: pass only the new record, not the full history.
    write_jsonl_records(site_dir / _DATASET_GROUPS_FILENAME, [asdict(assignment)])
    return assignment


def dataset_group_for_date(assignments: list[DatasetGroupAssignment], target_date: str) -> str:
    """Return the assigned group covering a date, or the development default.

    `assignments` is in append order (oldest first). When more than one
    covers the same date (a later assignment promoted/replaced part or all
    of an earlier one), the MOST RECENT one wins — scan in reverse — so a
    promotion (e.g. `practice` -> `locked_validation`) actually takes
    effect instead of the original, superseded assignment still winning.
    """

    target = _parse_date(target_date, field="target_date")
    for assignment in reversed(assignments):
        start = _parse_date(assignment.start_date, field="start_date")
        end = _parse_date(assignment.end_date, field="end_date")
        if start <= target <= end:
            return assignment.group
    return DEFAULT_DATASET_GROUP

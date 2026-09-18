from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.review.dataset_groups import (
    DatasetGroupError,
    assign_dataset_group,
    dataset_group_for_date,
    list_dataset_group_assignments,
)


def test_list_dataset_group_assignments_returns_empty_when_no_file(tmp_path: Path) -> None:
    assert list_dataset_group_assignments(tmp_path) == []


def test_assign_dataset_group_writes_and_lists_assignment(tmp_path: Path) -> None:
    assignment = assign_dataset_group(
        tmp_path, group="practice", start_date="2026-06-18", end_date="2026-07-31", note="warm-up"
    )
    assert assignment.group == "practice"
    listed = list_dataset_group_assignments(tmp_path)
    assert len(listed) == 1
    assert listed[0].start_date == "2026-06-18"

    path = tmp_path / "dataset-groups.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["group"] == "practice"


def test_assign_dataset_group_rejects_invalid_group(tmp_path: Path) -> None:
    with pytest.raises(DatasetGroupError, match="Invalid dataset group"):
        assign_dataset_group(
            tmp_path, group="bogus", start_date="2026-06-18", end_date="2026-06-30"
        )


def test_assign_dataset_group_rejects_reversed_range(tmp_path: Path) -> None:
    with pytest.raises(DatasetGroupError, match="end_date must be on or after"):
        assign_dataset_group(
            tmp_path, group="practice", start_date="2026-07-01", end_date="2026-06-01"
        )


def test_assign_dataset_group_rejects_overlap_with_existing_assignment(tmp_path: Path) -> None:
    assign_dataset_group(tmp_path, group="practice", start_date="2026-06-18", end_date="2026-07-31")
    with pytest.raises(DatasetGroupError, match="overlaps an existing 'practice' assignment"):
        assign_dataset_group(
            tmp_path, group="locked_validation", start_date="2026-07-15", end_date="2026-08-15"
        )


def test_assign_dataset_group_allows_adjacent_non_overlapping_ranges(tmp_path: Path) -> None:
    assign_dataset_group(tmp_path, group="practice", start_date="2026-06-18", end_date="2026-07-31")
    second = assign_dataset_group(
        tmp_path, group="excluded", start_date="2026-08-01", end_date="2026-08-31"
    )
    assert second.group == "excluded"
    assert len(list_dataset_group_assignments(tmp_path)) == 2


def test_dataset_group_for_date_falls_back_to_development_candidate(tmp_path: Path) -> None:
    assignments = list_dataset_group_assignments(tmp_path)
    assert dataset_group_for_date(assignments, "2026-06-18") == "development_candidate"


def test_dataset_group_for_date_matches_covering_assignment(tmp_path: Path) -> None:
    assign_dataset_group(
        tmp_path, group="locked_validation", start_date="2026-06-18", end_date="2026-09-16"
    )
    assignments = list_dataset_group_assignments(tmp_path)
    assert dataset_group_for_date(assignments, "2026-07-04") == "locked_validation"
    assert dataset_group_for_date(assignments, "2026-09-17") == "development_candidate"


def test_matches_the_plans_worked_example(tmp_path: Path) -> None:
    # Cameo, Jan-Feb -> practice; Cameo, March -> excluded (same camera already
    # in practice); a separate site (Cisco) gets its own independent history.
    cameo_dir = tmp_path / "colorado-river-cameo"
    cisco_dir = tmp_path / "colorado-river-cisco"
    assign_dataset_group(
        cameo_dir, group="practice", start_date="2025-01-01", end_date="2025-02-28"
    )
    assign_dataset_group(
        cameo_dir,
        group="excluded",
        start_date="2025-03-01",
        end_date="2025-03-31",
        note="Same camera already committed to practice.",
    )
    assign_dataset_group(
        cisco_dir, group="locked_validation", start_date="2025-01-01", end_date="2025-03-31"
    )

    cameo_assignments = list_dataset_group_assignments(cameo_dir)
    assert dataset_group_for_date(cameo_assignments, "2025-01-15") == "practice"
    assert dataset_group_for_date(cameo_assignments, "2025-03-15") == "excluded"
    cisco_assignments = list_dataset_group_assignments(cisco_dir)
    assert dataset_group_for_date(cisco_assignments, "2025-02-01") == "locked_validation"

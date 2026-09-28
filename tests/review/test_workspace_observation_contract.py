"""Tests for the reviewed-observation contract in review/workspace.py.

Covers what test_image_sequence_runner.py's existing workspace test
doesn't: the new contract fields (schema_version, observation_id, source,
change_presence, event_validity, dataset_group, label_revision), backward
compatibility for pre-contract records, and revision/duplicate behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from openfloodai.contracts import read_jsonl_records
from openfloodai.review.dataset_groups import assign_dataset_group
from openfloodai.review.workspace import (
    ALLOWED_EVENT_VALIDITY,
    OBSERVATION_SCHEMA_VERSION,
    load_observations,
    normalize_observation,
    save_group,
    save_observation,
)
from openfloodai.validation.image_sequence_runner import run_image_sequence_validation

SEQUENCE_ID = "usgs-camera-demo-2026-09-01-2026-09-01-all"


def _make_site(site_dir: Path) -> None:
    (site_dir / "configs").mkdir(parents=True)
    config: dict[str, object] = {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo Site",
        "input_type": "local_video",
        "reference_region": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    (site_dir / "configs" / "site.json").write_text(json.dumps(config), encoding="utf-8")


def _write_frame(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = np.full((20, 20, 3), value, dtype=np.uint8)
    assert cv2.imwrite(str(path), frame)


def _write_manifest(sequence_dir: Path, records: list[dict[str, object]]) -> None:
    sequence_dir.mkdir(parents=True, exist_ok=True)
    with (sequence_dir / "sequence-manifest.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _run_a_real_image_sequence(site: Path) -> tuple[str, str]:
    """Build and run a minimal real image-sequence validation. Returns (run_id, sample_key)."""

    _make_site(site)
    sequence = site / "inputs" / "image-sequences" / SEQUENCE_ID
    baseline = "camera___2026-09-01T00-00-00Z.jpg"
    selected = "camera___2026-09-01T01-00-00Z.jpg"
    _write_frame(sequence / "images" / baseline, 100)
    _write_frame(sequence / "images" / selected, 100)
    _write_manifest(
        sequence,
        [
            {
                "filename": baseline,
                "captured_at_utc": "2026-09-01T00:00:00+00:00",
                "download_status": "downloaded",
            },
            {
                "filename": selected,
                "captured_at_utc": "2026-09-01T01:00:00+00:00",
                "download_status": "downloaded",
            },
        ],
    )
    report = run_image_sequence_validation(site, SEQUENCE_ID)

    from openfloodai.review.workspace import evidence

    payload = evidence(site, "image", report.run_id, SEQUENCE_ID)
    return report.run_id, str(payload["points"][0]["key"])


def _saved_rows(site: Path, run_id: str) -> list[dict[str, Any]]:
    run_dir = site / "outputs" / "image-sequence-runs" / run_id
    path = run_dir / "human-review" / "observations.jsonl"
    return list(read_jsonl_records(path)) if path.exists() else []


def test_save_observation_writes_the_full_contract(tmp_path: Path) -> None:
    site = tmp_path / "site"
    run_id, sample_key = _run_a_real_image_sequence(site)

    save_observation(
        site,
        {
            "kind": "image",
            "run_id": run_id,
            "media_id": SEQUENCE_ID,
            "sample_key": sample_key,
            "human_label": "water_level_rising",
            "event_validity": "real",
        },
    )

    row = _saved_rows(site, run_id)[0]
    assert row["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert row["source"] == "image_pair"
    assert row["change_presence"] == "change"
    assert row["event_validity"] == "real"
    assert row["dataset_group"] == "development_candidate"
    assert row["label_revision"] == 1
    assert isinstance(row["observation_id"], str) and row["observation_id"]


def test_event_validity_defaults_to_not_reviewed(tmp_path: Path) -> None:
    site = tmp_path / "site"
    run_id, sample_key = _run_a_real_image_sequence(site)

    save_observation(
        site,
        {
            "kind": "image",
            "run_id": run_id,
            "media_id": SEQUENCE_ID,
            "sample_key": sample_key,
            "human_label": "no_water_level_change",
        },
    )

    assert _saved_rows(site, run_id)[0]["event_validity"] == "not_reviewed"


def test_event_validity_rejects_an_unknown_value(tmp_path: Path) -> None:
    site = tmp_path / "site"
    run_id, sample_key = _run_a_real_image_sequence(site)

    with pytest.raises(ValueError, match="event_validity"):
        save_observation(
            site,
            {
                "kind": "image",
                "run_id": run_id,
                "media_id": SEQUENCE_ID,
                "sample_key": sample_key,
                "human_label": "no_water_level_change",
                "event_validity": "definitely-maybe",
            },
        )


@pytest.mark.parametrize(
    "human_label,expected",
    [
        ("water_level_rising", "change"),
        ("water_level_falling", "change"),
        ("no_water_level_change", "no_change"),
        ("cannot_judge_water_level", "cannot_judge"),
        ("camera_video_problem", "cannot_judge"),
    ],
)
def test_change_presence_is_derived_from_the_human_label(
    tmp_path: Path, human_label: str, expected: str
) -> None:
    site = tmp_path / "site"
    run_id, sample_key = _run_a_real_image_sequence(site)

    save_observation(
        site,
        {
            "kind": "image",
            "run_id": run_id,
            "media_id": SEQUENCE_ID,
            "sample_key": sample_key,
            "human_label": human_label,
        },
    )

    assert _saved_rows(site, run_id)[0]["change_presence"] == expected


def test_re_reviewing_the_same_sample_appends_a_new_revision_not_an_overwrite(
    tmp_path: Path,
) -> None:
    site = tmp_path / "site"
    run_id, sample_key = _run_a_real_image_sequence(site)
    request = {
        "kind": "image",
        "run_id": run_id,
        "media_id": SEQUENCE_ID,
        "sample_key": sample_key,
        "human_label": "no_water_level_change",
    }

    save_observation(site, request)
    save_observation(site, {**request, "human_label": "water_level_rising"})

    rows = _saved_rows(site, run_id)
    assert len(rows) == 2, "both reviews must be preserved, not overwritten"
    ids = {row["observation_id"] for row in rows}
    assert len(ids) == 1, "same sample must keep the same identity across revisions"
    assert [row["label_revision"] for row in rows] == [1, 2]
    # The latest revision is what a reader should treat as current.
    latest = max(rows, key=lambda row: int(row["label_revision"]))
    assert latest["label"]["human_label"] == "water_level_rising"


def test_dataset_group_is_stamped_from_the_assignment_at_review_time(tmp_path: Path) -> None:
    site = tmp_path / "site"
    run_id, sample_key = _run_a_real_image_sequence(site)
    request = {
        "kind": "image",
        "run_id": run_id,
        "media_id": SEQUENCE_ID,
        "sample_key": sample_key,
        "human_label": "no_water_level_change",
    }

    # Before any group assignment exists, the image pipeline's own default applies.
    save_observation(site, request)
    assert _saved_rows(site, run_id)[0]["dataset_group"] == "development_candidate"

    # Assigning a group afterward must not retroactively change the first
    # review's frozen record -- only a new review reflects it.
    assign_dataset_group(site, group="practice", start_date="2026-09-01", end_date="2026-09-01")
    rows_before_second_review = _saved_rows(site, run_id)
    assert rows_before_second_review[0]["dataset_group"] == "development_candidate"

    save_observation(site, {**request, "human_label": "water_level_rising"})
    rows = _saved_rows(site, run_id)
    assert rows[0]["dataset_group"] == "development_candidate"
    assert rows[1]["dataset_group"] == "practice"


def test_normalize_observation_fills_defaults_for_a_pre_contract_record() -> None:
    legacy_record = {
        "sample_key": "abc123",
        "media_id": "seq-1",
        "kind": "image",
        "run_id": "run-1",
        "label": {"human_label": "water_level_falling"},
        "baseline_filename": "baseline.jpg",
        "filename": "selected.jpg",
        "captured_at_utc": "2026-09-01T00:00:00+00:00",
        "config_sha256": "deadbeef",
        "reviewed_at_utc": "2026-09-01T00:00:00+00:00",
    }
    original = dict(legacy_record)

    normalized = normalize_observation(legacy_record)

    assert legacy_record == original, "normalize_observation must not mutate its input"
    assert normalized["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert normalized["source"] == "image_pair"
    assert normalized["change_presence"] == "change"
    assert normalized["event_validity"] == "not_reviewed"
    assert normalized["dataset_group"] == "unassigned"
    assert normalized["label_revision"] == 1
    assert isinstance(normalized["observation_id"], str) and normalized["observation_id"]


def test_normalize_observation_is_idempotent_for_an_already_current_record() -> None:
    record = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_id": "fixed-id",
        "source": "video_window",
        "kind": "video",
        "run_id": "run-1",
        "media_id": "video-1",
        "sample_key": "abc",
        "label": {"human_label": "no_water_level_change"},
        "change_presence": "no_change",
        "event_validity": "real",
        "dataset_group": "practice",
        "label_revision": 3,
    }

    assert normalize_observation(record) == record


def test_load_observations_returns_empty_list_when_the_file_does_not_exist(
    tmp_path: Path,
) -> None:
    site = tmp_path / "site"
    run_id, _sample_key = _run_a_real_image_sequence(site)
    run_dir = site / "outputs" / "image-sequence-runs" / run_id

    assert load_observations(run_dir) == []


def test_load_observations_normalizes_every_row(tmp_path: Path) -> None:
    site = tmp_path / "site"
    run_id, sample_key = _run_a_real_image_sequence(site)
    save_observation(
        site,
        {
            "kind": "image",
            "run_id": run_id,
            "media_id": SEQUENCE_ID,
            "sample_key": sample_key,
            "human_label": "no_water_level_change",
        },
    )

    run_dir = site / "outputs" / "image-sequence-runs" / run_id
    observations = load_observations(run_dir)

    assert len(observations) == 1
    assert observations[0]["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert observations[0]["event_validity"] == "not_reviewed"


def test_allowed_event_validity_values_are_exactly_the_documented_set() -> None:
    assert ALLOWED_EVENT_VALIDITY == {"real", "not_real", "uncertain", "not_reviewed"}


def test_save_group_still_works_alongside_the_new_contract_fields(tmp_path: Path) -> None:
    """save_group() (dataset-group assignment) must be unaffected by this change."""

    site = tmp_path / "site"
    run_id, sample_key = _run_a_real_image_sequence(site)
    request = {
        "kind": "image",
        "run_id": run_id,
        "media_id": SEQUENCE_ID,
        "sample_key": sample_key,
        "human_label": "no_water_level_change",
    }

    save_observation(site, request)
    save_group(site, {**request, "group": "practice"})

    from openfloodai.review.workspace import evidence

    assert len(evidence(site, "image", run_id, SEQUENCE_ID)["groups"]) == 1

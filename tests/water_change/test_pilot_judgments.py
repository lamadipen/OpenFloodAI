"""Exporting a reviewer's blind labels from the focused review page as pilot judgments."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from water_helpers import Fixture, Img, make_run

from openfloodai.water_change.pilot import PilotError, _load_judgments
from openfloodai.water_change.pilot_judgments import export_reviewer_judgments

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "curation"))


def label(
    fx: Fixture,
    current: int,
    reference: int,
    reviewer: str,
    human: str,
    *,
    stage: str | None = "blind",
    at: str = "2026-10-08T10:00:00+00:00",
    revision: int = 1,
) -> None:
    path = fx.site_dir / "outputs" / "image-sequence-runs" / fx.run_id / "human-review"
    path.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {
        "kind": "image",
        "filename": fx.filenames[current],
        "label": {"human_label": human, "reviewer_id": reviewer},
        "label_revision": revision,
        "reviewed_at_utc": at,
        "baseline_filename": fx.filenames[0],
        "reference": {
            "sequence_id": fx.sequence_id,
            "run_id": fx.run_id,
            "filename": fx.filenames[reference],
        },
    }
    if stage:
        row["review_stage"] = stage
    with (path / "observations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def pilot(tmp_path: Path, fx: Fixture) -> Path:
    directory = tmp_path / "pilot"
    directory.mkdir()

    def pair(pair_id: str, a: int, b: int) -> dict[str, Any]:
        return {
            "pair_id": pair_id,
            "case_type": "rising",
            "held_out": False,
            "framing_confirmed_by": "Dipen",
            "earlier": {"run_id": fx.run_id, "filename": fx.filenames[a]},
            "later": {"run_id": fx.run_id, "filename": fx.filenames[b]},
        }

    (directory / "pairs.json").write_text(
        json.dumps({"site_folder": fx.folder_name, "pairs": [pair("p1", 0, 1), pair("p2", 1, 2)]}),
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    return make_run(tmp_path, [Img(day=d, human=None) for d in (1, 2, 3)], baseline=0)


def test_blind_labels_become_a_judgments_file_the_pilot_accepts(
    tmp_path: Path, fx: Fixture
) -> None:
    label(fx, 1, 0, "reviewer-a", "water_level_rising")
    label(fx, 2, 1, "reviewer-a", "no_water_level_change", at="2026-10-08T11:00:00+00:00")
    directory = pilot(tmp_path, fx)

    result = export_reviewer_judgments(directory, fx.sites_dir, "reviewer-a")

    saved = json.loads(Path(result["path"]).read_text())
    assert saved["judgments"] == {
        "p1": {"later_vs_earlier": "more_water"},
        "p2": {"later_vs_earlier": "about_same"},
    }
    assert saved["blind_to_machine_results"] is True and saved["blind_to_gauge"] is True
    assert saved["judged_at_utc"] == "2026-10-08T11:00:00+00:00"
    assert result["not_labelled_by_reviewer"] == [] and result["warning"] is None
    # the pilot's own loader accepts it as a valid blind judgment made before the measurement
    valid, rejected = _load_judgments(directory, datetime(2026, 10, 9, tzinfo=UTC))
    assert rejected == [] and valid["reviewer-a"] == {"p1": "more_water", "p2": "about_same"}


def test_labels_against_the_later_image_are_flipped_and_unjudged_answers_become_cannot_judge(
    tmp_path: Path, fx: Fixture
) -> None:
    label(fx, 0, 1, "reviewer-a", "water_level_falling")  # earlier vs later: falling = more later
    label(fx, 2, 1, "reviewer-a", "camera_video_problem")
    result = export_reviewer_judgments(pilot(tmp_path, fx), fx.sites_dir, "reviewer-a")
    saved = json.loads(Path(result["path"]).read_text())
    assert saved["judgments"]["p1"] == {"later_vs_earlier": "more_water"}
    assert saved["judgments"]["p2"] == {"later_vs_earlier": "cannot_judge"}


def test_only_blind_labels_are_exported_and_the_rest_is_reported(
    tmp_path: Path, fx: Fixture
) -> None:
    label(fx, 1, 0, "reviewer-a", "water_level_rising")
    label(fx, 1, 0, "reviewer-a", "no_water_level_change", stage="informed", revision=2)
    label(fx, 2, 1, "reviewer-a", "water_level_rising", stage=None)  # an older save, no stage
    label(fx, 2, 1, "reviewer-b", "water_level_rising")
    result = export_reviewer_judgments(pilot(tmp_path, fx), fx.sites_dir, "reviewer-a")
    saved = json.loads(Path(result["path"]).read_text())
    assert saved["judgments"] == {"p1": {"later_vs_earlier": "more_water"}}
    assert result["not_labelled_by_reviewer"] == ["p2"] and result["labels_set_aside"] >= 2


def test_it_refuses_when_there_is_nothing_to_export_or_the_file_exists(
    tmp_path: Path, fx: Fixture
) -> None:
    directory = pilot(tmp_path, fx)
    with pytest.raises(PilotError, match="No blind labels"):
        export_reviewer_judgments(directory, fx.sites_dir, "reviewer-a")
    with pytest.raises(PilotError, match="reviewer code"):
        export_reviewer_judgments(directory, fx.sites_dir, "  ")
    label(fx, 1, 0, "reviewer-a", "water_level_rising")
    export_reviewer_judgments(directory, fx.sites_dir, "reviewer-a")
    with pytest.raises(PilotError, match="already exists"):
        export_reviewer_judgments(directory, fx.sites_dir, "reviewer-a")


def test_a_measurement_that_already_exists_produces_a_warning(tmp_path: Path, fx: Fixture) -> None:
    label(fx, 1, 0, "reviewer-a", "water_level_rising")
    directory = pilot(tmp_path, fx)
    (directory / "measurements").mkdir()
    (directory / "measurements" / "20261009T000000Z.json").write_text("{}", encoding="utf-8")
    result = export_reviewer_judgments(directory, fx.sites_dir, "reviewer-a")
    assert (
        result["measurements_already_exist"] is True and "set this file aside" in result["warning"]
    )


def test_a_label_made_with_the_evidence_in_view_is_never_exported_as_blind(
    tmp_path: Path, fx: Fixture
) -> None:
    # Visible-change datasets count informed labels (Assisted review), but the pilot attests that
    # judgments were made blind to machine results, so an informed-only reviewer exports nothing.
    label(fx, 1, 0, "reviewer-a", "water_level_rising", stage="informed")
    label(fx, 2, 1, "reviewer-a", "water_level_rising", stage="informed")
    directory = pilot(tmp_path, fx)
    with pytest.raises(PilotError, match="No blind labels"):
        export_reviewer_judgments(directory, fx.sites_dir, "reviewer-a")
    assert not (directory / "judgments" / "reviewer-a.json").exists()
    # a blind label for one pair exports that pair only; the informed one is set aside
    label(fx, 1, 0, "reviewer-a", "water_level_rising", stage="blind", revision=2)
    result = export_reviewer_judgments(directory, fx.sites_dir, "reviewer-a")
    saved = json.loads(Path(result["path"]).read_text())
    assert saved["judgments"] == {"p1": {"later_vs_earlier": "more_water"}}
    assert result["not_labelled_by_reviewer"] == ["p2"] and result["labels_set_aside"] >= 1

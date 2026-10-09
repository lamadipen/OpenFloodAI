"""The pre-registered pilot protocol: criteria first, blind judgments, honest unavailable counts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from curation_fixtures import Img, make_run
from water_helpers import Fixture, add_water_mask, water

from openfloodai.water_change.pilot import (
    PilotError,
    build_report,
    load_criteria,
    load_pairs,
    machine_direction,
    record_decision,
    run_measurements,
)
from openfloodai.water_change.pilot_sheets import (
    inventory_accepted_masks,
    render_blind_sheet,
    render_measured_sheet,
)

CRITERIA: dict[str, Any] = {
    "written_by": "Hydrologist",
    "written_at_utc": "2026-01-01T00:00:00+00:00",
    "stable_tolerance_pp": 2.0,
    "min_pairs": 4,
    "max_unavailable_rate": 0.34,
    "min_consensus_pairs": 3,
    "min_machine_agreement": 0.8,
    "machine_vs_human_margin": 0.1,
    "gauge_stable_tolerance": 0.2,
    "stop_conditions": ["Stop if the machine returns unknown for most pairs."],
}


def _run_id(n: int) -> str:
    return f"20261002T10000{n}Z-{n:08x}"


def build_site(root: Path) -> Fixture:
    """Six images: rising, falling, stable, equal-area/different-shape and one with no mask."""

    images = [
        Img(day=d, human=None, level=lvl)
        for d, lvl in zip(range(1, 7), (3, 5, 3, 3, 3, 3), strict=True)
    ]
    fx = make_run(root, images, run_id="20261001T100000Z-aaaaaaaa")
    shapes = {
        0: water(8),  # 5 cols
        1: water(14),  # 11 cols (rising vs 0)
        2: water(8),  # falling vs 1
        3: water(8),  # stable vs 2
        4: water(18, x0=13),  # same 5 cols, other place (equal area, different shape vs 3)
    }
    for index, mask in shapes.items():
        add_water_mask(fx, index, mask, run_id=_run_id(index + 1))
    return fx  # image 5 has no mask


def pair(
    pair_id: str, a: int, b: int, case: str, fx: Fixture, held_out: bool = False
) -> dict[str, Any]:
    return {
        "pair_id": pair_id,
        "case_type": case,
        "held_out": held_out,
        "framing_confirmed_by": "Dipen",
        "earlier": {"run_id": fx.run_id, "filename": fx.filenames[a]},
        "later": {"run_id": fx.run_id, "filename": fx.filenames[b]},
    }


def setup_pilot(tmp_path: Path, fx: Fixture, *, with_hard: bool = True) -> Path:
    pilot = tmp_path / "pilot"
    (pilot / "judgments").mkdir(parents=True)
    pairs = [
        pair("p1", 0, 1, "rising", fx),
        pair("p2", 1, 2, "falling", fx),
        pair("p3", 2, 3, "stable_high", fx),
        pair("p4", 3, 4, "equal_area_different_shape", fx),
    ]
    if with_hard:
        pairs.append(pair("p5", 4, 5, "difficult", fx))
    pairs.append(pair("h1", 0, 2, "rising", fx, held_out=True))
    (pilot / "pairs.json").write_text(
        json.dumps({"site_folder": fx.folder_name, "pairs": pairs}), encoding="utf-8"
    )
    (pilot / "criteria.json").write_text(json.dumps(CRITERIA), encoding="utf-8")
    return pilot


TRUTH = {"p1": "more_water", "p2": "less_water", "p3": "about_same", "p4": "about_same"}


def judge(
    pilot: Path,
    name: str,
    labels: dict[str, str],
    *,
    at: str = "2026-01-02T00:00:00+00:00",
    blind: bool = True,
) -> None:
    (pilot / "judgments" / f"{name}.json").write_text(
        json.dumps(
            {
                "reviewer": name,
                "judged_at_utc": at,
                "blind_to_machine_results": blind,
                "blind_to_gauge": blind,
                "judgments": {k: {"later_vs_earlier": v} for k, v in labels.items()},
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    return build_site(tmp_path)


def test_criteria_must_be_complete_and_sensible(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    assert load_criteria(pilot).stable_tolerance_pp == 2.0
    changes: list[dict[str, Any]] = [
        {"written_by": ""},
        {"stop_conditions": []},
        {"max_unavailable_rate": 1.5},
        {"written_at_utc": "2026-01-01T00:00:00"},
        {"min_pairs": "many"},
    ]
    for change in changes:
        (pilot / "criteria.json").write_text(json.dumps({**CRITERIA, **change}), encoding="utf-8")
        with pytest.raises(PilotError):
            load_criteria(pilot)
    (pilot / "criteria.json").unlink()
    with pytest.raises(PilotError):
        load_criteria(pilot)


def test_pairs_need_unique_ids_and_known_case_types(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    folder, pairs = load_pairs(pilot)
    assert folder == fx.folder_name and len(pairs) == 6
    bad = {
        "site_folder": folder,
        "pairs": [pair("x", 0, 1, "rising", fx), pair("x", 1, 2, "rising", fx)],
    }
    (pilot / "pairs.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(PilotError):
        load_pairs(pilot)
    bad["pairs"] = [pair("y", 0, 1, "sideways", fx)]
    (pilot / "pairs.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(PilotError):
        load_pairs(pilot)


def test_machine_direction_uses_the_written_tolerance() -> None:
    assert machine_direction(2.0, 2.0) == "about_same"
    assert machine_direction(2.1, 2.0) == "more_water"
    assert machine_direction(-2.1, 2.0) == "less_water"


def test_held_out_pairs_are_skipped_unless_requested_and_the_request_is_logged(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    first = run_measurements(pilot, fx.sites_dir)
    assert {r["pair_id"] for r in first["results"]} == {"p1", "p2", "p3", "p4", "p5"}
    assert first["criteria_sha256"] == load_criteria(pilot).sha256
    assert not (pilot / "held-out-evaluations.jsonl").exists()
    both = run_measurements(pilot, fx.sites_dir, include_held_out=True)
    assert "h1" in {r["pair_id"] for r in both["results"]}
    assert (pilot / "held-out-evaluations.jsonl").read_text().count("\n") == 1


def test_a_clean_pilot_reports_agreement_and_counts_the_unavailable_pair(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    judge(pilot, "Hydrologist", {**TRUTH, "p5": "cannot_judge"})
    judge(pilot, "Second", {**TRUTH, "p5": "cannot_judge"})
    run_measurements(pilot, fx.sites_dir)
    report = build_report(pilot)
    dev = report["development"]
    assert dev["pairs"] == 5 and dev["available"] == 4 and dev["unavailable"] == 1
    assert dev["unavailable_rate"] == pytest.approx(0.2)
    assert dev["unavailable_reasons"]["LATER_MASK_MISSING"] == 1
    assert dev["machine_agreement_with_consensus"] == 1.0 and dev["machine_errors"] == 0
    assert dev["human_human_agreement"] == 1.0
    assert dev["criteria_met"] is True and report["protocol_problems"] == []
    assert report["mechanical_status"] == "criteria_met_held_out_not_checked"
    assert report["held_out"]["status"] == "not evaluated"
    assert (pilot / "report.md").read_text().startswith("# Water-change pilot report")
    assert "decision_required" in report


def test_machine_errors_and_disagreements_are_listed(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    wrong = {**TRUTH, "p1": "less_water"}
    judge(pilot, "A", wrong)
    judge(pilot, "B", wrong)
    run_measurements(pilot, fx.sites_dir)
    dev = build_report(pilot)["development"]
    assert dev["machine_errors"] == 1
    assert dev["machine_disagreements"][0]["pair_id"] == "p1"
    assert dev["criteria_met"] is False


def test_returning_unknown_for_everything_cannot_pass(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    judge(pilot, "A", TRUTH)
    judge(pilot, "B", TRUTH)
    pairs = json.loads((pilot / "pairs.json").read_text())
    for row in pairs["pairs"]:  # point every pair at the image that has no mask
        row["later"]["filename"] = fx.filenames[5]
    (pilot / "pairs.json").write_text(json.dumps(pairs), encoding="utf-8")
    run_measurements(pilot, fx.sites_dir)
    dev = build_report(pilot)["development"]
    assert dev["available"] == 0 and dev["unavailable_rate"] == 1.0
    assert dev["criteria_met"] is False
    assert not next(c for c in dev["checks"] if c["check"] == "unavailable_rate_within_limit")[
        "passed"
    ]


def test_judgments_made_after_the_machine_result_do_not_count(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    judge(pilot, "A", TRUTH)
    judge(pilot, "Late", TRUTH, at="2999-01-01T00:00:00+00:00")
    judge(pilot, "NotBlind", TRUTH, blind=False)
    run_measurements(pilot, fx.sites_dir)
    report = build_report(pilot)
    assert report["reviewers_counted"] == ["A"]
    reasons = " ".join(item["reason"] for item in report["judgment_files_set_aside"])
    assert "after the first machine measurement" in reasons and "blind" in reasons
    assert "fewer than two valid blind reviewers" in report["protocol_problems"]
    assert report["mechanical_status"] == "protocol_not_followed"


def test_changing_the_criteria_after_measuring_is_a_protocol_problem(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    judge(pilot, "A", TRUTH)
    judge(pilot, "B", TRUTH)
    run_measurements(pilot, fx.sites_dir)
    (pilot / "criteria.json").write_text(
        json.dumps({**CRITERIA, "min_machine_agreement": 0.1}), encoding="utf-8"
    )
    assert (
        "criteria changed after a measurement was made" in build_report(pilot)["protocol_problems"]
    )


def test_criteria_written_after_measuring_is_flagged(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    (pilot / "criteria.json").write_text(
        json.dumps({**CRITERIA, "written_at_utc": "2999-01-01T00:00:00+00:00"}), encoding="utf-8"
    )
    judge(pilot, "A", TRUTH)
    judge(pilot, "B", TRUTH)
    run_measurements(pilot, fx.sites_dir)
    problems = build_report(pilot)["protocol_problems"]
    assert "criteria were written after the first machine measurement" in problems


def test_held_out_is_scored_only_on_request_and_every_evaluation_is_logged(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    labels = {**TRUTH, "p5": "cannot_judge", "h1": "less_water"}
    judge(pilot, "A", labels)
    judge(pilot, "B", labels)
    run_measurements(pilot, fx.sites_dir, include_held_out=True)
    assert build_report(pilot)["held_out"]["status"] == "not evaluated"
    report = build_report(pilot, evaluate_held_out=True)
    held = report["held_out"]
    assert held["status"] == "evaluated" and held["pairs"] == 1
    assert held["evaluations_so_far"] == 2  # the measure request plus this report
    assert report["mechanical_status"] in {
        "criteria_not_met_on_held_out",
        "criteria_met_on_held_out",
    }


def test_gauge_context_is_shown_after_and_disagreements_are_flagged(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    judge(pilot, "A", TRUTH)
    judge(pilot, "B", TRUTH)
    run_measurements(pilot, fx.sites_dir)
    gauge = {g["pair_id"]: g for g in build_report(pilot)["gauge_context_after_machine_results"]}
    assert gauge["p1"]["gauge_direction"] == "higher" and gauge["p1"]["investigate"] is False
    assert gauge["p2"]["gauge_direction"] == "lower" and gauge["p2"]["investigate"] is False
    assert gauge["p4"]["gauge_direction"] == "about_same"


def test_a_decision_needs_a_report_and_is_recorded_once(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    with pytest.raises(PilotError):
        record_decision(pilot, "proceed", "Dipen", "why", "limits")
    judge(pilot, "A", TRUTH)
    judge(pilot, "B", TRUTH)
    run_measurements(pilot, fx.sites_dir)
    build_report(pilot)
    with pytest.raises(PilotError):
        record_decision(pilot, "maybe", "Dipen", "why", "limits")
    with pytest.raises(PilotError):
        record_decision(pilot, "revise", "Dipen", "", "limits")
    entry = record_decision(pilot, "revise", "Dipen", "needs more pairs", "one camera")
    assert "No production accuracy claim" in entry["claim"]
    with pytest.raises(FileExistsError):
        record_decision(pilot, "stop", "Dipen", "again", "limits")


def test_blind_sheet_shows_images_only(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    index = render_blind_sheet(pilot, fx.sites_dir)
    text = index.read_text()
    assert "No machine result and no gauge value" in text
    assert "pp" not in text and "gauge" not in text.replace("no gauge value", "")
    assert (pilot / "blind-sheet" / "p1.png").is_file()
    template = json.loads((pilot / "blind-sheet" / "judgment-template.json").read_text())
    assert set(template["judgments"]) == {"p1", "p2", "p3", "p4", "p5", "h1"}
    assert template["blind_to_machine_results"] is False


def test_measured_sheet_shows_numbers_overlay_and_unavailable_reasons(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    measurement = run_measurements(pilot, fx.sites_dir)
    text = render_measured_sheet(pilot, fx.sites_dir, measurement).read_text()
    assert "UNAVAILABLE" in text and "LATER_MASK_MISSING" in text
    assert "newly wet" in text and "water arrived" in text
    assert (pilot / "contact-sheet" / "p1.png").is_file()


def test_inventory_lists_only_accepted_completed_water_masks(tmp_path: Path, fx: Fixture) -> None:
    add_water_mask(fx, 5, water(10), run_id=_run_id(6), review="rejected")
    add_water_mask(fx, 5, water(10), run_id=_run_id(7), prompt="riverbank")
    inventory = inventory_accepted_masks(fx.sites_dir)
    assert inventory["accepted_water_masks"] == 5
    group = inventory["by_camera_and_watched_area"][0]
    assert group["distinct_images_with_accepted_mask"] == 5
    assert group["camera_id"] == "CAM_A" and group["crop_px"] == [3, 4, 23, 15]
    assert fx.run_id in inventory["masks"][0]["image_runs"]

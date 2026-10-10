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
    _gauge_direction,
    build_report,
    frozen_pairs,
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
        for d, lvl in zip(range(1, 9), (3, 5, 3, 3, 3, 3, 3, 5), strict=True)
    ]
    fx = make_run(root, images, run_id="20261001T100000Z-aaaaaaaa")
    shapes = {
        0: water(8),  # 5 cols
        1: water(14),  # 11 cols (rising vs 0)
        2: water(8),  # falling vs 1
        3: water(8),  # stable vs 2
        4: water(18, x0=13),  # same 5 cols, other place (equal area, different shape vs 3)
        6: water(8),  # the held-out pair uses images no development pair uses
        7: water(14),
    }
    for index, mask in shapes.items():
        add_water_mask(fx, index, mask, run_id=_run_id(index + 1))
    return fx  # image 5 has no mask; images 6 and 7 are only for the held-out pair


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
    pairs.append(pair("h1", 6, 7, "rising", fx, held_out=True))
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
    for row in pairs["pairs"]:  # point every development pair at the image that has no mask
        if not row["held_out"]:
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
    add_water_mask(fx, 5, water(10), run_id=_run_id(9), prompt="riverbank")
    inventory = inventory_accepted_masks(fx.sites_dir)
    assert inventory["accepted_water_masks"] == 7
    group = inventory["by_camera_and_watched_area"][0]
    assert group["distinct_images_with_accepted_mask"] == 7
    assert group["camera_id"] == "CAM_A" and group["crop_px"] == [3, 4, 23, 15]
    assert fx.run_id in inventory["masks"][0]["image_runs"]


def _edit_pairs(pilot: Path, change: Any) -> None:
    path = pilot / "pairs.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def _expose_held_out(data: dict[str, Any]) -> None:
    # after measuring, quietly move the reserved pair into the development group
    for row in data["pairs"]:
        if row["pair_id"] == "h1":
            row["held_out"] = False


def test_the_pairs_are_frozen_with_a_hash_before_the_first_measurement(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    assert not (pilot / "pairs.frozen.json").exists()
    measured = run_measurements(pilot, fx.sites_dir)
    frozen = json.loads((pilot / "pairs.frozen.json").read_text(encoding="utf-8"))
    assert frozen["pairs_sha256"] == measured["pairs_sha256"]
    assert frozen["criteria_sha256"] == load_criteria(pilot).sha256
    assert {p["pair_id"] for p in frozen["pairs"]} == {"p1", "p2", "p3", "p4", "p5", "h1"}
    assert [p["held_out"] for p in frozen["pairs"] if p["pair_id"] == "h1"] == [True]
    assert frozen["frozen_at_utc"] < measured["measured_at_utc"]


def test_the_blind_sheet_freezes_the_pairs_before_anyone_judges(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    render_blind_sheet(pilot, fx.sites_dir)
    assert (pilot / "pairs.frozen.json").is_file()
    _edit_pairs(pilot, _expose_held_out)
    with pytest.raises(PilotError, match="no longer matches pairs.frozen.json"):
        run_measurements(pilot, fx.sites_dir)


def test_pairs_cannot_be_edited_after_they_are_frozen(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    run_measurements(pilot, fx.sites_dir)
    _edit_pairs(pilot, _expose_held_out)
    with pytest.raises(PilotError, match="frozen before measurement"):
        run_measurements(pilot, fx.sites_dir)
    with pytest.raises(PilotError, match="no longer matches"):
        frozen_pairs(pilot, fx.sites_dir)


def test_editing_pairs_json_cannot_change_which_old_results_count_as_held_out(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    judge(pilot, "A", TRUTH)
    judge(pilot, "B", TRUTH)
    run_measurements(pilot, fx.sites_dir, include_held_out=True)
    honest = build_report(pilot)
    assert honest["protocol_problems"] == []
    assert honest["development"]["pairs"] == 5 and honest["held_out"]["pairs_reserved"] == 1

    _edit_pairs(pilot, _expose_held_out)  # try to move the measured held-out pair into development
    report = build_report(pilot)
    assert "pairs.json was edited after the pairs were frozen" in report["protocol_problems"]
    assert report["mechanical_status"] == "protocol_not_followed"
    # the split still comes from the frozen file, not from the edited pairs.json
    assert report["development"]["pairs"] == 5
    assert report["held_out"]["pairs_reserved"] == 1


def test_a_measurement_made_under_other_pairs_is_a_protocol_problem(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    run_measurements(pilot, fx.sites_dir)
    path = next((pilot / "measurements").glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["pairs_sha256"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    problems = build_report(pilot)["protocol_problems"]
    assert "a measurement was made under different pairs than the frozen ones" in problems


def test_a_pilot_measured_without_frozen_pairs_is_flagged(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    run_measurements(pilot, fx.sites_dir)
    (pilot / "pairs.frozen.json").unlink()
    problems = build_report(pilot)["protocol_problems"]
    assert "the pairs and held-out marks were not frozen before measurement" in problems


def _gauge(**overrides: Any) -> dict[str, Any]:
    base = {
        "usable": True,
        "value": 3.0,
        "unit": "ft",
        "station_nwis_id": "09034250",
        "parameter_code": "00065",
        "used_fallback_discharge": False,
    }
    return {**base, **overrides}


def test_a_gauge_comparison_needs_the_same_station_and_measurement() -> None:
    def compare(earlier: dict[str, Any], later: dict[str, Any]) -> tuple[Any, Any, str]:
        return _gauge_direction({"earlier_gauge": earlier, "later_gauge": later}, 0.2)

    assert compare(_gauge(), _gauge(value=4.0)) == ("higher", 1.0, "")
    direction, change, why = compare(_gauge(), _gauge(value=4.0, station_nwis_id="09999999"))
    assert (
        direction is None and change is None and why == "gauge station differs between the two ends"
    )
    assert compare(_gauge(), _gauge(parameter_code="00060"))[2] == (
        "gauge measurement type differs between the two ends"
    )
    assert compare(_gauge(), _gauge(unit="m"))[2] == "gauge unit differs between the two ends"
    assert compare(_gauge(station_nwis_id=None), _gauge())[2] == (
        "gauge station is not recorded at both ends"
    )
    assert compare(_gauge(parameter_code=None), _gauge(parameter_code=None))[2] == (
        "gauge measurement type is not recorded at both ends"
    )
    assert compare(_gauge(), _gauge(used_fallback_discharge=True))[2] == (
        "gauge readings were taken from different measurements"
    )
    assert compare(_gauge(usable=False), _gauge())[0] is None


def _write_pairs(pilot: Path, fx: Fixture, extra: list[dict[str, Any]]) -> None:
    pairs = [
        pair("p1", 0, 1, "rising", fx),
        pair("p2", 1, 2, "falling", fx),
        pair("p3", 2, 3, "stable_high", fx),
        pair("p4", 3, 4, "equal_area_different_shape", fx),
        pair("h1", 6, 7, "rising", fx, held_out=True),
        *extra,
    ]
    (pilot / "pairs.json").write_text(
        json.dumps({"site_folder": fx.folder_name, "pairs": pairs}), encoding="utf-8"
    )


def test_the_same_two_images_cannot_be_both_development_and_held_out(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    # the held-out pair h1 uses images 6 and 7; another name for the same two images is a duplicate
    _write_pairs(pilot, fx, [pair("again", 6, 7, "difficult", fx)])
    with pytest.raises(PilotError, match="use the same two images"):
        frozen_pairs(pilot, fx.sites_dir)
    _write_pairs(pilot, fx, [pair("again", 7, 6, "difficult", fx, held_out=True)])  # reversed
    with pytest.raises(PilotError, match="use the same two images"):
        run_measurements(pilot, fx.sites_dir)
    assert not (pilot / "pairs.frozen.json").exists()  # nothing was frozen from invalid pairs


def test_a_development_pair_cannot_borrow_a_held_out_image(tmp_path: Path, fx: Fixture) -> None:
    pilot = setup_pilot(tmp_path, fx)
    _write_pairs(pilot, fx, [pair("leak", 5, 7, "difficult", fx)])  # image 7 is held-out h1's
    with pytest.raises(PilotError, match="share images") as error:
        frozen_pairs(pilot, fx.sites_dir)
    assert fx.filenames[7] in str(error.value)
    with pytest.raises(PilotError, match="independent"):
        render_blind_sheet(pilot, fx.sites_dir)


def test_images_may_be_shared_inside_development_and_inside_held_out(
    tmp_path: Path, fx: Fixture
) -> None:
    pilot = setup_pilot(tmp_path, fx)
    # p1 and p2 already share image 1 (development); two held-out pairs may share one image too
    _write_pairs(pilot, fx, [pair("h2", 7, 5, "difficult", fx, held_out=True)])
    _, pairs, _ = frozen_pairs(pilot, fx.sites_dir)
    assert {p.pair_id for p in pairs if p.held_out} == {"h1", "h2"}


RUN_X = "20261001T100000Z-aaaaaaaa"
RUN_Y = "20261005T100000Z-bbbbbbbb"


def two_runs(tmp_path: Path, *, same_bytes: bool) -> tuple[Fixture, Fixture]:
    """Two runs of one site, each holding images with the same file names.

    With ``same_bytes`` the images are the very same pictures reused by both runs; without it they
    are different pictures that only share a name (two sequences both holding the same frame names).
    """

    def images() -> list[Img]:
        return [Img(day=d, human=None, seed=900 + d if same_bytes else None) for d in (1, 2, 3, 4)]

    return (
        make_run(tmp_path, images(), run_id=RUN_X),
        make_run(tmp_path, images(), run_id=RUN_Y),
    )


def _cross_run_pairs(
    pilot: Path,
    x: Fixture,
    y: Fixture,
    rows: list[tuple[str, tuple[Fixture, int], tuple[Fixture, int], bool]],
) -> None:
    pairs = [
        {
            "pair_id": pair_id,
            "case_type": "rising",
            "held_out": held_out,
            "framing_confirmed_by": "Dipen",
            "earlier": {"run_id": a.run_id, "filename": a.filenames[i]},
            "later": {"run_id": b.run_id, "filename": b.filenames[j]},
        }
        for pair_id, (a, i), (b, j), held_out in rows
    ]
    pilot.mkdir(exist_ok=True)
    (pilot / "pairs.json").write_text(
        json.dumps({"site_folder": x.folder_name, "pairs": pairs}), encoding="utf-8"
    )


def test_different_images_that_share_file_names_across_sequences_are_not_duplicates(
    tmp_path: Path,
) -> None:
    x, y = two_runs(tmp_path, same_bytes=False)
    assert x.filenames == y.filenames and x.shas != y.shas  # same names, different pictures
    pilot = tmp_path / "pilot"
    _cross_run_pairs(
        pilot,
        x,
        y,
        [
            ("dev", (x, 0), (x, 1), False),
            # the same two names in the other sequence: different images, so a valid held-out pair
            ("held", (y, 0), (y, 1), True),
            # and a pair whose two ends come from the two sequences
            ("mixed", (x, 2), (y, 3), False),
        ],
    )
    folder, pairs, _ = frozen_pairs(pilot, x.sites_dir)
    assert folder == x.folder_name and {p.pair_id for p in pairs} == {"dev", "held", "mixed"}
    frozen = json.loads((pilot / "pairs.frozen.json").read_text(encoding="utf-8"))
    ends = {
        p["pair_id"]: (p["earlier_image_identity"], p["later_image_identity"])
        for p in frozen["pairs"]
    }
    assert ends["dev"][0] != ends["held"][0] and ends["dev"][1] != ends["held"][1]
    assert ends["dev"][0] == f"sha256:{x.shas[x.filenames[0]]}"


def test_the_same_image_reused_across_runs_is_one_image(tmp_path: Path) -> None:
    x, y = two_runs(tmp_path, same_bytes=True)
    assert x.filenames == y.filenames and x.shas == y.shas  # the very same pictures
    pilot = tmp_path / "pilot"

    # the same two images through another run, in the other order, is a duplicate pair
    _cross_run_pairs(pilot, x, y, [("a", (x, 0), (x, 1), False), ("b", (y, 1), (y, 0), False)])
    with pytest.raises(PilotError, match="use the same two images"):
        frozen_pairs(pilot, x.sites_dir)

    # one image reused in a development pair (run X) and a held-out pair (run Y) leaks
    _cross_run_pairs(pilot, x, y, [("dev", (x, 0), (x, 1), False), ("held", (y, 0), (y, 2), True)])
    with pytest.raises(PilotError, match="share images") as error:
        frozen_pairs(pilot, x.sites_dir)
    assert x.filenames[0] in str(error.value)
    assert not (pilot / "pairs.frozen.json").exists()

    # distinct images in each group stay valid even though both runs hold all four
    _cross_run_pairs(pilot, x, y, [("dev", (x, 0), (x, 1), False), ("held", (y, 2), (y, 3), True)])
    assert {p.pair_id for p in frozen_pairs(pilot, x.sites_dir)[1]} == {"dev", "held"}


def test_an_image_that_cannot_be_identified_is_never_equal_to_another(tmp_path: Path) -> None:
    from openfloodai.water_change.identity import ImageIdentities

    x, _ = two_runs(tmp_path, same_bytes=False)
    identities = ImageIdentities(x.site_dir, x.folder_name)
    known = identities.of(RUN_X, x.filenames[0])
    assert known == f"sha256:{x.shas[x.filenames[0]]}"
    missing = identities.of(RUN_X, "no-such-frame.jpg")
    assert missing.startswith("unresolved:") and missing != known
    assert identities.of("no-such-run", x.filenames[0]).startswith("unresolved:")
    assert identities.of("../escape", x.filenames[0]).startswith("unresolved:")
    assert missing != identities.of("no-such-run", "no-such-frame.jpg")

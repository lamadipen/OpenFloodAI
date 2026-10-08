"""Task eligibility for dataset curation: what each task needs and how a gap is explained."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from curation_fixtures import Fixture, Img, add_mask_result, make_run

from openfloodai.curation import (
    CurationConflict,
    CurationError,
    add_observation,
    add_pair,
    create_dataset,
    pin_label_definition,
    read_draft,
    reject_observation,
    remove_member,
)
from openfloodai.curation import labels as label_defs
from openfloodai.curation.common import (
    TASK_GAUGE_HEIGHT,
    TASK_LEVEL_CHANGE,
    TASK_LEVEL_CLASSIFICATION,
    TASK_WATER_SEGMENTATION,
)

BANDS = [
    {"name": "low", "lower": None, "upper": 3.0},
    {"name": "middle", "lower": 3.0, "upper": 6.0},
    {"name": "high", "lower": 6.0, "upper": None},
]


def codes(result: dict[str, Any]) -> set[str]:
    return {r["code"] for r in result["reasons"]}


def datasets(tmp_path: Path) -> Path:
    return tmp_path / "datasets"


def definition(tmp_path: Path, site_id: str = "site-a_sid", **overrides: object) -> dict[str, Any]:
    payload = {
        "site_id": site_id,
        "unit": "ft",
        "station_nwis_id": "09034250",
        "boundary": "upper_inclusive",
        "bands": BANDS,
        "rationale": "Site operator's local bank-full marks.",
        "author": "Reviewer A",
        "approved_by": "Lead B",
        **overrides,
    }
    return label_defs.create_definition(datasets(tmp_path), payload)


def add(
    tmp_path: Path, ds: dict[str, Any], fx: Fixture, index: int, **kwargs: Any
) -> dict[str, Any]:
    return add_observation(
        datasets(tmp_path),
        fx.sites_dir,
        ds["dataset_id"],
        folder_name=fx.folder_name,
        run_id=fx.run_id,
        filename=fx.filenames[index],
        **kwargs,
    )


# ---- gauge-height estimation ----------------------------------------------------------------


def test_a_valid_matched_gauge_reading_makes_a_gauge_height_example(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=4.2)])
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)

    result = add(tmp_path, ds, fx, 0)

    assert result["status"] == "added"
    annotation = result["annotation"]
    assert annotation["value"] == 4.2 and annotation["unit"] == "ft"
    assert annotation["station_nwis_id"] == "09034250"
    assert "not manually observed truth" in annotation["note"]


@pytest.mark.parametrize(
    ("img", "code"),
    [
        (Img(day=2, level=None, match="missing"), "gauge_not_matched"),
        (Img(day=2, quality="rejected"), "gauge_quality_unusable"),
        (Img(day=2, gap_seconds=3600), "gauge_gap_too_large"),
        (Img(day=2, human="cannot_judge_water_level"), "unassessable_image"),
        (Img(day=2, human="camera_video_problem"), "unassessable_image"),
        (Img(day=2, dataset_group="excluded"), "excluded_group"),
    ],
)
def test_gauge_height_explains_why_an_image_is_not_eligible(
    tmp_path: Path, img: Img, code: str
) -> None:
    fx = make_run(tmp_path, [img])
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)

    result = add(tmp_path, ds, fx, 0)

    assert result["status"] == "ineligible"
    assert code in codes(result)
    assert read_draft(datasets(tmp_path), ds["dataset_id"]) == {}


def test_a_discharge_fallback_is_not_a_gauge_height(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2)], parameter_code="00060", unit="cfs")
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)

    assert "gauge_not_height" in codes(add(tmp_path, ds, fx, 0))


def test_provisional_nearby_and_unreviewed_are_warnings_not_blocks(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, quality="provisional", human=None)], relationship="nearby")
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)

    result = add(tmp_path, ds, fx, 0)

    assert result["status"] == "added"
    assert {"gauge_provisional", "gauge_station_nearby", "image_quality_unreviewed"} <= codes(
        result
    )


def test_a_missing_or_changed_original_image_blocks_the_example(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2), Img(day=3)])
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)
    seq = fx.site_dir / "inputs" / "image-sequences" / fx.sequence_id / "images"
    (seq / fx.filenames[0]).unlink()
    (seq / fx.filenames[1]).write_bytes(b"different bytes")

    assert "source_missing" in codes(add(tmp_path, ds, fx, 0))
    assert "source_changed" in codes(add(tmp_path, ds, fx, 1))


# ---- classification -------------------------------------------------------------------------


def test_classification_needs_an_approved_versioned_definition(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=4.0)])
    ds = create_dataset(datasets(tmp_path), name="Classes", task=TASK_LEVEL_CLASSIFICATION)

    assert "definition_missing" in codes(add(tmp_path, ds, fx, 0))


def test_category_is_derived_from_the_gauge_value_not_the_sampling_group(tmp_path: Path) -> None:
    # The sampling group says "high", but the gauge value is in the middle band.
    fx = make_run(tmp_path, [Img(day=2, level=4.0, group="high")])
    definition(tmp_path)
    ds = create_dataset(datasets(tmp_path), name="Classes", task=TASK_LEVEL_CLASSIFICATION)
    pin_label_definition(datasets(tmp_path), ds["dataset_id"], fx.site_id, 1)

    annotation = add(tmp_path, ds, fx, 0)["annotation"]

    assert annotation["category"] == "middle"
    assert annotation["gauge_value"] == 4.0 and annotation["unit"] == "ft"
    assert annotation["definition"] == {"site_id": fx.site_id, "version": 1}
    member = next(iter(read_draft(datasets(tmp_path), ds["dataset_id"]).values()))
    assert member["snapshot"]["collection"]["group"] == "high"  # kept, but separate


@pytest.mark.parametrize(
    ("level", "inclusive", "expected"),
    [
        (3.0, "upper_inclusive", "low"),
        (3.0, "lower_inclusive", "middle"),
        (6.0, "upper_inclusive", "middle"),
        (6.0, "lower_inclusive", "high"),
    ],
)
def test_boundary_inclusivity_decides_which_band_a_boundary_value_is_in(
    tmp_path: Path, level: float, inclusive: str, expected: str
) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=level)])
    definition(tmp_path, boundary=inclusive)
    ds = create_dataset(datasets(tmp_path), name="Classes", task=TASK_LEVEL_CLASSIFICATION)
    pin_label_definition(datasets(tmp_path), ds["dataset_id"], fx.site_id, 1)

    assert add(tmp_path, ds, fx, 0)["annotation"]["category"] == expected


def test_classification_requires_a_human_review_and_an_assessable_image(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, human=None), Img(day=3, human="cannot_judge_water_level")])
    definition(tmp_path)
    ds = create_dataset(datasets(tmp_path), name="Classes", task=TASK_LEVEL_CLASSIFICATION)
    pin_label_definition(datasets(tmp_path), ds["dataset_id"], fx.site_id, 1)

    assert "needs_human_review" in codes(add(tmp_path, ds, fx, 0))
    assert "unassessable_image" in codes(add(tmp_path, ds, fx, 1))


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"station_nwis_id": "99999999"}, "definition_station_mismatch"),
        ({"unit": "m"}, "definition_unit_mismatch"),
        ({"bands": [{"name": "low", "lower": None, "upper": 1.0}]}, "value_outside_bands"),
    ],
)
def test_a_definition_must_match_the_reading_station_unit_and_range(
    tmp_path: Path, overrides: dict[str, Any], code: str
) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=4.0)])
    definition(tmp_path, **overrides)
    ds = create_dataset(datasets(tmp_path), name="Classes", task=TASK_LEVEL_CLASSIFICATION)
    pin_label_definition(datasets(tmp_path), ds["dataset_id"], fx.site_id, 1)

    assert code in codes(add(tmp_path, ds, fx, 0))


def test_definitions_are_versioned_and_never_edited(tmp_path: Path) -> None:
    first = definition(tmp_path)
    second = definition(
        tmp_path,
        bands=[
            {"name": "low", "lower": None, "upper": 2.0},
            {"name": "high", "lower": 2.0, "upper": None},
        ],
    )

    assert (first["version"], second["version"]) == (1, 2)
    assert label_defs.get_definition(datasets(tmp_path), "site-a_sid", 1)["bands"] == BANDS


@pytest.mark.parametrize(
    "payload",
    [
        {"rationale": ""},
        {"approved_by": ""},
        {
            "bands": [
                {"name": "low", "lower": None, "upper": 3.0},
                {"name": "high", "lower": 4.0, "upper": None},
            ]
        },
        {
            "bands": [
                {"name": "low", "lower": None, "upper": 5.0},
                {"name": "high", "lower": 3.0, "upper": None},
            ]
        },
        {"bands": [{"name": "weird", "lower": None, "upper": 5.0}]},
        {"boundary": "sometimes"},
    ],
)
def test_an_invalid_definition_is_refused(tmp_path: Path, payload: dict[str, Any]) -> None:
    with pytest.raises(CurationError):
        definition(tmp_path, **payload)


def test_changing_the_pinned_definition_makes_old_categories_stale(tmp_path: Path) -> None:
    from openfloodai.curation import dataset_view

    fx = make_run(tmp_path, [Img(day=2, level=4.0)])
    definition(tmp_path)
    definition(
        tmp_path,
        bands=[
            {"name": "low", "lower": None, "upper": 5.0},
            {"name": "high", "lower": 5.0, "upper": None},
        ],
    )
    ds = create_dataset(datasets(tmp_path), name="Classes", task=TASK_LEVEL_CLASSIFICATION)
    pin_label_definition(datasets(tmp_path), ds["dataset_id"], fx.site_id, 1)
    add(tmp_path, ds, fx, 0)

    pin_label_definition(datasets(tmp_path), ds["dataset_id"], fx.site_id, 2)
    view = dataset_view(datasets(tmp_path), ds["dataset_id"])

    assert any(p["code"] == "annotation_stale" for p in view["blocking"])
    # Re-adding under the new definition is a different annotation: an explicit decision.
    with pytest.raises(CurationConflict):
        add(tmp_path, ds, fx, 0)
    assert add(tmp_path, ds, fx, 0, decision="replace")["annotation"]["category"] == "low"


# ---- segmentation ---------------------------------------------------------------------------


def test_segmentation_needs_a_human_accepted_mask_for_the_same_image_bytes(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, human=None)])
    ds = create_dataset(datasets(tmp_path), name="Masks", task=TASK_WATER_SEGMENTATION)

    assert "mask_missing" in codes(add(tmp_path, ds, fx, 0))

    add_mask_result(fx, fx.filenames[0], review="accepted")
    result = add(tmp_path, ds, fx, 0)

    assert result["status"] == "added"
    annotation = result["annotation"]
    assert annotation["source"] == "machine_mask_human_accepted"
    assert annotation["prompt"] == "river water" and len(annotation["masks"]) == 1


@pytest.mark.parametrize(
    ("review", "code"),
    [
        (None, "mask_unreviewed"),
        ("rejected", "mask_rejected"),
        ("needs_correction", "mask_needs_correction"),
    ],
)
def test_a_mask_that_no_person_accepted_is_not_a_verified_annotation(
    tmp_path: Path, review: str | None, code: str
) -> None:
    fx = make_run(tmp_path, [Img(day=2)])
    add_mask_result(fx, fx.filenames[0], review=review)
    ds = create_dataset(datasets(tmp_path), name="Masks", task=TASK_WATER_SEGMENTATION)

    result = add(tmp_path, ds, fx, 0)

    assert result["status"] == "ineligible" and code in codes(result)


def test_needs_correction_does_not_pretend_a_mask_editor_exists(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2)])
    add_mask_result(fx, fx.filenames[0], review="needs_correction")
    ds = create_dataset(datasets(tmp_path), name="Masks", task=TASK_WATER_SEGMENTATION)

    message = next(
        r["message"]
        for r in add(tmp_path, ds, fx, 0)["reasons"]
        if r["code"] == "mask_needs_correction"
    )

    assert "established workflow" in message and "no mask editor" in message


def test_a_mask_made_from_different_bytes_is_not_used(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2)])
    result_id = add_mask_result(fx, fx.filenames[0])
    path = (
        fx.site_dir
        / "outputs"
        / "hosted-sam-runs"
        / "20261002T100000Z-bbbbbbbb"
        / "results"
        / f"{result_id}.json"
    )
    path.write_text(path.read_text().replace(fx.shas[fx.filenames[0]], "0" * 64), encoding="utf-8")
    ds = create_dataset(datasets(tmp_path), name="Masks", task=TASK_WATER_SEGMENTATION)

    assert "mask_missing" in codes(add(tmp_path, ds, fx, 0))


def test_two_different_accepted_masks_need_an_explicit_choice(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2)])
    first = add_mask_result(fx, fx.filenames[0], run_id="20261002T100000Z-bbbbbbbb", mask_seed=1)
    second = add_mask_result(fx, fx.filenames[0], run_id="20261003T100000Z-cccccccc", mask_seed=2)
    ds = create_dataset(datasets(tmp_path), name="Masks", task=TASK_WATER_SEGMENTATION)

    assert "mask_ambiguous" in codes(add(tmp_path, ds, fx, 0))
    chosen = add(tmp_path, ds, fx, 0, mask_result_id=second)
    assert chosen["annotation"]["result_id"] == second != first


def test_a_mask_example_needs_no_low_image_or_gauge(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=None, match="missing", human=None, group="high")])
    add_mask_result(fx, fx.filenames[0])
    ds = create_dataset(datasets(tmp_path), name="Masks", task=TASK_WATER_SEGMENTATION)

    assert add(tmp_path, ds, fx, 0)["status"] == "added"


# ---- rising / falling pairs -----------------------------------------------------------------


def pair_refs(fx: Fixture, i: int, j: int) -> dict[str, Any]:
    return {
        "earlier": {
            "folder_name": fx.folder_name,
            "run_id": fx.run_id,
            "filename": fx.filenames[i],
        },
        "later": {"folder_name": fx.folder_name, "run_id": fx.run_id, "filename": fx.filenames[j]},
    }


def test_an_explicit_earlier_later_pair_gets_a_derived_target(tmp_path: Path) -> None:
    fx = make_run(
        tmp_path, [Img(day=2, level=6.5), Img(day=9, level=4.0)]
    )  # earlier may already be high
    ds = create_dataset(
        datasets(tmp_path), name="Change", task=TASK_LEVEL_CHANGE, change_tolerance=0.1
    )

    result = add_pair(
        datasets(tmp_path),
        fx.sites_dir,
        ds["dataset_id"],
        earlier=pair_refs(fx, 0, 1)["earlier"],
        later=pair_refs(fx, 0, 1)["later"],
    )

    annotation = result["annotation"]
    assert result["status"] == "added"
    assert annotation["delta"] == -2.5 and annotation["direction"] == "falling"
    assert annotation["elapsed_seconds"] == 7 * 86400


def test_without_an_explicit_tolerance_a_pair_has_a_delta_but_no_direction(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=4.0), Img(day=9, level=4.01)])
    ds = create_dataset(datasets(tmp_path), name="Change", task=TASK_LEVEL_CHANGE)

    annotation = add_pair(
        datasets(tmp_path), fx.sites_dir, ds["dataset_id"], **pair_refs(fx, 0, 1)
    )["annotation"]

    assert annotation["delta"] == pytest.approx(0.01) and annotation["direction"] is None


@pytest.mark.parametrize(
    ("first", "second", "code"),
    [
        (Img(day=9), Img(day=2), "pair_not_ordered"),
        (Img(day=2, level=None, match="missing"), Img(day=9), "gauge_not_matched"),
        (Img(day=2, camera_stable="no"), Img(day=9), "camera_unstable"),
    ],
)
def test_pairs_must_be_ordered_measured_and_from_a_stable_view(
    tmp_path: Path, first: Img, second: Img, code: str
) -> None:
    fx = make_run(tmp_path, [first, second])
    ds = create_dataset(datasets(tmp_path), name="Change", task=TASK_LEVEL_CHANGE)

    result = add_pair(
        datasets(tmp_path),
        fx.sites_dir,
        ds["dataset_id"],
        earlier=pair_refs(fx, 0, 1)["earlier"],
        later=pair_refs(fx, 0, 1)["later"],
    )

    assert result["status"] == "ineligible" and code in codes(result)


def test_a_pair_cannot_span_two_cameras_or_one_image(tmp_path: Path) -> None:
    a = make_run(tmp_path, [Img(day=2)], folder="site-a", camera="CAM_A")
    b = make_run(
        tmp_path, [Img(day=9)], folder="site-b", camera="CAM_B", run_id="20261005T100000Z-bbbbbbbb"
    )
    ds = create_dataset(datasets(tmp_path), name="Change", task=TASK_LEVEL_CHANGE)
    cross = {
        "earlier": {"folder_name": a.folder_name, "run_id": a.run_id, "filename": a.filenames[0]},
        "later": {"folder_name": b.folder_name, "run_id": b.run_id, "filename": b.filenames[0]},
    }
    same = pair_refs(a, 0, 0)

    assert "pair_different_camera" in codes(
        add_pair(
            datasets(tmp_path),
            a.sites_dir,
            ds["dataset_id"],
            earlier=cross["earlier"],
            later=cross["later"],
        )
    )
    assert "pair_same_image" in codes(
        add_pair(
            datasets(tmp_path),
            a.sites_dir,
            ds["dataset_id"],
            earlier=same["earlier"],
            later=same["later"],
        )
    )


def test_single_observations_cannot_be_added_to_a_pair_dataset(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2)])
    ds = create_dataset(datasets(tmp_path), name="Change", task=TASK_LEVEL_CHANGE)

    with pytest.raises(CurationError, match="pair"):
        add(tmp_path, ds, fx, 0)


# ---- draft membership -----------------------------------------------------------------------


def test_repeating_a_selection_is_idempotent_and_across_runs_resolves_to_one_observation(
    tmp_path: Path,
) -> None:
    first = make_run(tmp_path, [Img(day=2, seed=11)], run_id="20261001T100000Z-aaaaaaaa")
    # A second saved run of the same sequence sees the same source image.
    second = make_run(tmp_path, [Img(day=2, seed=11)], run_id="20261004T100000Z-dddddddd")
    # Share the sequence so both runs describe the same downloaded image.
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)

    one = add(tmp_path, ds, first, 0)
    again = add(tmp_path, ds, first, 0)
    other_run = add(tmp_path, ds, second, 0)

    assert (one["status"], again["status"], other_run["status"]) == (
        "added",
        "unchanged",
        "unchanged",
    )
    members = read_draft(datasets(tmp_path), ds["dataset_id"])
    assert len(members) == 1
    assert sorted(next(iter(members.values()))["runs"]) == sorted([first.run_id, second.run_id])


def test_a_different_annotation_for_the_same_observation_needs_an_explicit_decision(
    tmp_path: Path,
) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=4.0)])
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)
    add(tmp_path, ds, fx, 0)
    path = (
        fx.site_dir
        / "outputs"
        / "image-sequence-runs"
        / fx.run_id
        / "inputs-used"
        / "gauge-matches.snapshot.json"
    )
    path.write_text(path.read_text().replace('"value": 4.0', '"value": 4.5'), encoding="utf-8")

    with pytest.raises(CurationConflict) as raised:
        add(tmp_path, ds, fx, 0)
    assert (
        raised.value.details["existing"]["value"] == 4.0
        and raised.value.details["new"]["value"] == 4.5
    )

    assert add(tmp_path, ds, fx, 0, decision="keep")["status"] == "kept"
    assert (
        next(iter(read_draft(datasets(tmp_path), ds["dataset_id"]).values()))["annotation"]["value"]
        == 4.0
    )
    assert add(tmp_path, ds, fx, 0, decision="replace")["status"] == "replaced"
    assert (
        next(iter(read_draft(datasets(tmp_path), ds["dataset_id"]).values()))["annotation"]["value"]
        == 4.5
    )


def test_removing_a_draft_member_keeps_source_imagery_and_run_evidence(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2)])
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)
    member_id = add(tmp_path, ds, fx, 0)["member_id"]
    run = fx.site_dir / "outputs" / "image-sequence-runs" / fx.run_id
    before = sorted(p.name for p in run.rglob("*"))

    remove_member(datasets(tmp_path), ds["dataset_id"], member_id)

    assert read_draft(datasets(tmp_path), ds["dataset_id"]) == {}
    assert (
        fx.site_dir / "inputs" / "image-sequences" / fx.sequence_id / "images" / fx.filenames[0]
    ).is_file()
    assert sorted(p.name for p in run.rglob("*")) == before


def test_a_reviewer_can_reject_an_annotation_and_it_stays_visible(tmp_path: Path) -> None:
    from openfloodai.curation import dataset_view

    fx = make_run(tmp_path, [Img(day=2)])
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)

    reject_observation(
        datasets(tmp_path),
        fx.sites_dir,
        ds["dataset_id"],
        folder_name=fx.folder_name,
        run_id=fx.run_id,
        filename=fx.filenames[0],
        note="Glare hides the waterline.",
    )
    view = dataset_view(datasets(tmp_path), ds["dataset_id"])

    row = view["members"][0]
    assert row["status"] == "rejected" and row["rejection_note"] == "Glare hides the waterline."
    assert view["label_counts"]["examples"] == 0


def test_adding_never_changes_the_source_run_or_its_review_history(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2)])
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)
    watched = [fx.site_dir / "outputs", fx.site_dir / "inputs"]
    before = {p: p.read_bytes() for root in watched for p in root.rglob("*") if p.is_file()}

    add(tmp_path, ds, fx, 0)

    after = {p: p.read_bytes() for root in watched for p in root.rglob("*") if p.is_file()}
    assert before == after

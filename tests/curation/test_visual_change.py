"""The visual-change task: independent blind human judgments of a pair, never a vote or a gauge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from curation_fixtures import Fixture, Img, make_run

from openfloodai.curation import (
    CurationError,
    add_observation,
    add_pair,
    check_observation,
    check_pair,
    create_dataset,
    freeze_version,
    memberships,
    read_draft,
    verify_version,
)
from openfloodai.curation.common import TASK_GAUGE_HEIGHT, TASK_VISUAL_CHANGE
from openfloodai.curation.store import PAIR_TASKS, recheck_member
from openfloodai.curation.visual_change import (
    MIN_JUDGMENTS,
    Judgment,
    agreement_summary,
    collect_judgments,
)
from openfloodai.release.builder import _public_annotation

HOURS = {"earlier": "2026-01-01T18:00:00+00:00", "later": "2026-01-02T18:00:00+00:00"}


def datasets(tmp_path: Path) -> Path:
    return tmp_path / "datasets"


def build(tmp_path: Path) -> Fixture:
    return make_run(tmp_path, [Img(day=1, human=None), Img(day=2, human=None)], baseline=0)


def review(
    fx: Fixture,
    current: int,
    reference: int,
    reviewer: str,
    label: str = "water_level_rising",
    *,
    stage: str | None = "blind",
    revision: int = 1,
    stable: str | None = "yes",
    at: str = "2026-10-08T10:00:00+00:00",
) -> None:
    """One saved human review row, as the focused review page writes it."""

    path = fx.site_dir / "outputs" / "image-sequence-runs" / fx.run_id / "human-review"
    path.mkdir(parents=True, exist_ok=True)
    label_data: dict[str, Any] = {
        "human_label": label,
        "reviewer_id": reviewer,
        "confidence": "high",
    }
    if stable is not None:
        label_data["camera_stable"] = stable
    row: dict[str, Any] = {
        "kind": "image",
        "filename": fx.filenames[current],
        "media_id": fx.sequence_id,
        "observation_id": f"obs-{current}-{reference}",
        "label": label_data,
        "label_revision": revision,
        "reviewed_at_utc": at,
        "change_presence": "change",
        "event_validity": "not_reviewed",
        "dataset_group": "development_candidate",
        "config_sha256": "c" * 64,
        "baseline_filename": fx.filenames[0],
        "reference": {
            "sequence_id": fx.sequence_id,
            "run_id": fx.run_id,
            "filename": fx.filenames[reference],
        },
    }
    if stage is not None:
        row["review_stage"] = stage
    with (path / "observations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def ref(fx: Fixture, index: int) -> dict[str, str]:
    return {"folder_name": fx.folder_name, "run_id": fx.run_id, "filename": fx.filenames[index]}


def dataset(tmp_path: Path, task: str = TASK_VISUAL_CHANGE) -> dict[str, Any]:
    return create_dataset(datasets(tmp_path), name="Visible change", task=task)


def check(tmp_path: Path, fx: Fixture, ds: dict[str, Any]) -> dict[str, Any]:
    return check_pair(
        datasets(tmp_path), fx.sites_dir, ds["dataset_id"], earlier=ref(fx, 0), later=ref(fx, 1)
    )


def codes(result: dict[str, Any]) -> set[str]:
    return {r["code"] for r in result["reasons"]}


def test_the_task_is_a_pair_task_with_its_own_title_and_a_release_card_category() -> None:
    from openfloodai.curation.common import TASK_TITLES, TASKS
    from openfloodai.release.card import HF_TASK_CATEGORIES

    assert TASK_VISUAL_CHANGE in PAIR_TASKS and MIN_JUDGMENTS == 1
    assert TASK_VISUAL_CHANGE in TASKS and "human-judged" in TASK_TITLES[TASK_VISUAL_CHANGE]
    assert HF_TASK_CATEGORIES[TASK_VISUAL_CHANGE] == ["image-classification"]


def test_nobody_having_judged_the_pair_blocks_it(tmp_path: Path) -> None:
    fx = build(tmp_path)
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "ineligible" and "needs_a_judgment" in codes(out)
    assert out["agreement"]["reviewers"] == 0 and out["agreement"]["needed"] == 1


def test_one_judgment_is_enough_and_the_pair_awaits_dataset_review(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a")
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "eligible", out["reasons"]
    annotation = out["annotation"]
    assert annotation["reviewer_count"] == 1 and annotation["direction"] == "more_water"
    assert annotation["dataset_review"] == "pending"
    assert annotation["source"] == "human_judgments_awaiting_dataset_review"
    assert "awaiting review inside the dataset" in annotation["note"]
    assert "independent" not in annotation["source"]


def test_two_independent_blind_reviewers_who_agree_make_an_eligible_pair(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a")
    review(fx, 1, 0, "reviewer-b")
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "eligible", out["reasons"]
    annotation = out["annotation"]
    assert annotation["direction"] == "more_water" and annotation["reviewer_count"] == 2
    assert annotation["blind_judgments_only"] is True
    assert annotation["source"] == "independent_blind_human_judgments_in_agreement"
    assert annotation["reviewers"] == ["reviewer-a", "reviewer-b"]
    assert annotation["elapsed_seconds"] == 24 * 3600
    assert "gauge" in annotation["note"].lower() and out["annotation_version"]


def test_reviewers_who_disagree_are_never_resolved_by_a_vote(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a", "water_level_rising")
    review(fx, 1, 0, "reviewer-b", "water_level_rising")
    review(fx, 1, 0, "reviewer-c", "no_water_level_change")  # two against one is still a conflict
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "ineligible" and "reviewers_disagree" in codes(out)
    assert "no majority vote" in json.dumps(out["reasons"])
    assert out["annotation"] is None and out["agreement"]["agree"] is False


@pytest.mark.parametrize("label", ["cannot_judge_water_level", "camera_video_problem"])
def test_a_cannot_judge_or_camera_problem_answer_blocks_the_pair(
    tmp_path: Path, label: str
) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a")
    review(fx, 1, 0, "reviewer-b", label)
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "ineligible" and "reviewer_cannot_judge" in codes(out)


def test_unstaged_and_unattributed_saves_are_never_counted(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-c", stage=None)  # saved by the older form
    review(fx, 1, 0, "", stage="blind")  # no reviewer code
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "ineligible" and "needs_a_judgment" in codes(out)
    assert "reviews_set_aside" in codes(out)
    assert out["agreement"]["reviewers"] == 0
    review(fx, 1, 0, "reviewer-a")
    again = check(tmp_path, fx, dataset(tmp_path))
    assert again["status"] == "eligible" and again["agreement"]["reviewers"] == 1
    assert "reviews_set_aside" in codes(again)


def test_an_informed_judgment_counts_but_is_marked_and_the_pair_is_not_blind_only(
    tmp_path: Path,
) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a")
    review(fx, 1, 0, "reviewer-b", stage="informed")  # seen the machine evidence first
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "eligible", out["reasons"]
    assert "informed_judgments_counted" in codes(out)
    warning = next(r for r in out["reasons"] if r["code"] == "informed_judgments_counted")
    assert warning["severity"] == "warning" and "reviewer-b" in warning["message"]
    annotation = out["annotation"]
    assert annotation["reviewer_count"] == 2 and annotation["informed_count"] == 1
    assert annotation["blind_judgments_only"] is False
    assert annotation["source"] == "human_judgments_awaiting_dataset_review"
    assert [(j["reviewer"], j["stage"]) for j in annotation["judgments"]] == [
        ("reviewer-a", "blind"),
        ("reviewer-b", "informed"),
    ]
    assert out["agreement"]["informed"] == ["reviewer-b"]


def test_informed_judgments_alone_can_make_an_eligible_pair(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a", stage="informed")
    review(fx, 1, 0, "reviewer-b", stage="informed")
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "eligible" and out["annotation"]["informed_count"] == 2


def test_a_single_informed_judgment_is_enough_but_several_must_still_agree(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a", "water_level_rising", stage="informed")
    alone = check(tmp_path, fx, dataset(tmp_path))
    assert alone["status"] == "eligible" and alone["annotation"]["informed_count"] == 1
    review(fx, 1, 0, "reviewer-b", "no_water_level_change", stage="informed")
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "ineligible" and "reviewers_disagree" in codes(out)


def test_an_informed_revision_does_not_replace_the_blind_label(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a", "water_level_rising", revision=1)
    review(fx, 1, 0, "reviewer-a", "no_water_level_change", stage="informed", revision=2)
    review(fx, 1, 0, "reviewer-b", "water_level_rising")
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "eligible" and out["annotation"]["direction"] == "more_water"
    assert "reviews_set_aside" in codes(out)  # the replaced informed label is reported, not hidden
    assert out["annotation"]["blind_judgments_only"] is True


def test_a_later_blind_revision_replaces_an_earlier_one_and_codes_ignore_case(
    tmp_path: Path,
) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "Reviewer-A", "no_water_level_change", revision=1)
    review(fx, 1, 0, "reviewer-a", "water_level_rising", revision=2)
    review(fx, 1, 0, "reviewer-b", "water_level_rising")
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "eligible" and out["annotation"]["reviewer_count"] == 2


def test_a_label_made_with_the_later_image_as_reference_is_flipped(tmp_path: Path) -> None:
    fx = build(tmp_path)
    # a: judged the later image against the earlier one -> rising means more water later
    review(fx, 1, 0, "reviewer-a", "water_level_rising")
    # b: judged the EARLIER image against the later one -> "rising" there means less water later
    review(fx, 0, 1, "reviewer-b", "water_level_falling")  # falling vs later = more water later
    out = check(tmp_path, fx, dataset(tmp_path))
    assert out["status"] == "eligible", out["reasons"]
    assert out["annotation"]["direction"] == "more_water"
    wrong = build_flipped_disagreement(tmp_path / "again")
    assert wrong["status"] == "ineligible" and "reviewers_disagree" in codes(wrong)


def build_flipped_disagreement(root: Path) -> dict[str, Any]:
    fx = build(root)
    review(fx, 1, 0, "reviewer-a", "water_level_rising")
    review(fx, 0, 1, "reviewer-b", "water_level_rising")  # rising vs later = LESS water later
    return check(root, fx, dataset(root))


def test_a_reported_camera_move_blocks_and_an_unconfirmed_view_only_warns(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a", stable="no")
    review(fx, 1, 0, "reviewer-b")
    blocked = check(tmp_path, fx, dataset(tmp_path))
    assert blocked["status"] == "ineligible" and "camera_moved_reported" in codes(blocked)

    other = build(tmp_path / "other")
    review(other, 1, 0, "reviewer-a", stable=None)
    review(other, 1, 0, "reviewer-b", stable="unsure")
    warned = check(tmp_path / "other", other, dataset(tmp_path / "other"))
    assert warned["status"] == "eligible" and "camera_stability_unconfirmed" in codes(warned)


def test_a_pair_must_be_two_ordered_images_of_one_camera(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a")
    review(fx, 1, 0, "reviewer-b")
    ds = dataset(tmp_path)
    reversed_ = check_pair(
        datasets(tmp_path), fx.sites_dir, ds["dataset_id"], earlier=ref(fx, 1), later=ref(fx, 0)
    )
    assert "pair_not_ordered" in codes(reversed_)
    same = check_pair(
        datasets(tmp_path), fx.sites_dir, ds["dataset_id"], earlier=ref(fx, 0), later=ref(fx, 0)
    )
    assert "pair_same_image" in codes(same)


def test_adding_freezing_and_verifying_a_visual_pair(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a")
    review(fx, 1, 0, "reviewer-b")
    ds = dataset(tmp_path)
    before = list(read_draft(datasets(tmp_path), ds["dataset_id"]))
    assert check(tmp_path, fx, ds)["status"] == "eligible"
    assert (
        list(read_draft(datasets(tmp_path), ds["dataset_id"])) == before
    )  # a check writes nothing

    added = add_pair(
        datasets(tmp_path), fx.sites_dir, ds["dataset_id"], earlier=ref(fx, 0), later=ref(fx, 1)
    )
    assert added["status"] == "added" and added["annotation"]["direction"] == "more_water"
    assert check(tmp_path, fx, ds)["status"] == "already_included"
    again = add_pair(
        datasets(tmp_path), fx.sites_dir, ds["dataset_id"], earlier=ref(fx, 0), later=ref(fx, 1)
    )
    assert again["status"] == "unchanged"

    member = read_draft(datasets(tmp_path), ds["dataset_id"])[added["member_id"]]
    assert member["task"] == TASK_VISUAL_CHANGE and member["kind"] == "pair"
    assert (
        recheck_member(
            datasets(tmp_path),
            ds | {"task": TASK_VISUAL_CHANGE},
            datasets(tmp_path) / ds["dataset_id"],
            member,
            fx.sites_dir,
        )
        == []
    )


def test_an_ineligible_pair_is_not_added(tmp_path: Path) -> None:
    fx = build(tmp_path)  # nobody has judged the pair
    ds = dataset(tmp_path)
    out = add_pair(
        datasets(tmp_path), fx.sites_dir, ds["dataset_id"], earlier=ref(fx, 0), later=ref(fx, 1)
    )
    assert out["status"] == "ineligible" and not read_draft(datasets(tmp_path), ds["dataset_id"])


def test_a_single_image_cannot_be_added_to_a_pair_dataset_and_pairs_need_a_pair_task(
    tmp_path: Path,
) -> None:
    fx = build(tmp_path)
    ds = dataset(tmp_path)
    with pytest.raises(CurationError, match="pair"):
        add_observation(datasets(tmp_path), fx.sites_dir, ds["dataset_id"], **ref(fx, 1))
    with pytest.raises(CurationError, match="pair"):
        check_observation(datasets(tmp_path), fx.sites_dir, ds["dataset_id"], **ref(fx, 1))
    gauge = dataset(tmp_path, TASK_GAUGE_HEIGHT)
    with pytest.raises(CurationError, match="pair"):
        check_pair(
            datasets(tmp_path),
            fx.sites_dir,
            gauge["dataset_id"],
            earlier=ref(fx, 0),
            later=ref(fx, 1),
        )


def test_check_observation_is_read_only_for_a_single_image_task(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=1, level=3.0), Img(day=2, level=4.0)], baseline=0)
    ds = dataset(tmp_path, TASK_GAUGE_HEIGHT)
    out = check_observation(datasets(tmp_path), fx.sites_dir, ds["dataset_id"], **ref(fx, 1))
    assert out["status"] == "eligible" and out["annotation"]["value"] == 4.0
    assert not read_draft(datasets(tmp_path), ds["dataset_id"])
    add_observation(datasets(tmp_path), fx.sites_dir, ds["dataset_id"], **ref(fx, 1))
    assert (
        check_observation(datasets(tmp_path), fx.sites_dir, ds["dataset_id"], **ref(fx, 1))[
            "status"
        ]
        == "already_included"
    )


def test_a_frozen_visual_dataset_verifies_and_a_release_hides_reviewer_codes(
    tmp_path: Path,
) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a")
    review(fx, 1, 0, "reviewer-b")
    ds = create_dataset(
        datasets(tmp_path),
        name="Visible change",
        task=TASK_VISUAL_CHANGE,
        split_policy={
            "kind": "single_site_time_block",
            "site_id": fx.site_id,
            "blocks": [{"split": "train", "start_date": "2026-01-01", "end_date": "2026-01-31"}],
        },
    )
    added = add_pair(
        datasets(tmp_path), fx.sites_dir, ds["dataset_id"], earlier=ref(fx, 0), later=ref(fx, 1)
    )
    manifest = freeze_version(
        datasets(tmp_path),
        ds["dataset_id"],
        note="first cut",
        approved_by="Dipen",
        sites_dir=fx.sites_dir,
    )
    assert manifest["task"] == TASK_VISUAL_CHANGE and manifest["counts"]["examples"] == 1
    assert verify_version(datasets(tmp_path), ds["dataset_id"], 1)["ok"] is True

    member = read_draft(datasets(tmp_path), ds["dataset_id"])[added["member_id"]]
    keys = [
        s["observation_key"] for s in (member["snapshots"]["earlier"], member["snapshots"]["later"])
    ]
    public = _public_annotation(
        {"annotation": member["annotation"]}, {k: f"id-{i}" for i, k in enumerate(keys)}
    )
    assert public["direction"] == "more_water" and public["reviewer_count"] == 2
    assert public["earlier_observation"] == "id-0" and public["later_observation"] == "id-1"
    assert public["blind_judgments_only"] is True and public["informed_judgment_count"] == 0
    assert "reviewer-a" not in json.dumps(public) and "reviewers" not in public
    assert "judgments" not in public


def test_collect_judgments_reads_both_runs_and_reports_what_was_set_aside(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a")
    review(fx, 1, 0, "reviewer-b", stage=None)
    run = fx.site_dir / "outputs" / "image-sequence-runs" / fx.run_id
    judgments, set_aside = collect_judgments(run, fx.filenames[0], run, fx.filenames[1])
    assert [j.reviewer for j in judgments] == ["reviewer-a"] and set_aside == 1
    summary = agreement_summary(
        [
            Judgment("a", "water_level_rising", "more_water", "yes", ""),
            Judgment("b", "water_level_rising", "more_water", "yes", ""),
        ]
    )
    assert summary == {
        "reviewers": 2,
        "needed": 1,
        "informed": [],
        "by_direction": {"more_water": ["a", "b"]},
        "agree": True,
    }


def test_a_pair_with_one_judgment_can_be_added_and_is_stored_as_awaiting_dataset_review(
    tmp_path: Path,
) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a")
    ds = dataset(tmp_path)
    added = add_pair(
        datasets(tmp_path), fx.sites_dir, ds["dataset_id"], earlier=ref(fx, 0), later=ref(fx, 1)
    )
    assert added["status"] == "added", added
    member = read_draft(datasets(tmp_path), ds["dataset_id"])[added["member_id"]]
    assert member["annotation"]["dataset_review"] == "pending"
    assert member["annotation"]["reviewer_count"] == 1
    keys = [
        s["observation_key"] for s in (member["snapshots"]["earlier"], member["snapshots"]["later"])
    ]
    public = _public_annotation(
        {"annotation": member["annotation"]}, {k: f"id-{i}" for i, k in enumerate(keys)}
    )
    assert public["dataset_review"] == "pending" and public["reviewer_count"] == 1


def test_memberships_list_both_images_of_a_pair_with_their_role(tmp_path: Path) -> None:
    fx = build(tmp_path)
    review(fx, 1, 0, "reviewer-a")
    ds = dataset(tmp_path)
    assert memberships(datasets(tmp_path), fx.folder_name) == {}
    add_pair(
        datasets(tmp_path), fx.sites_dir, ds["dataset_id"], earlier=ref(fx, 0), later=ref(fx, 1)
    )
    found = memberships(datasets(tmp_path), fx.folder_name)
    first, second = found[fx.filenames[0]], found[fx.filenames[1]]
    assert [(m["task"], m["role"], m["status"], m["with_filename"]) for m in first] == [
        (TASK_VISUAL_CHANGE, "earlier", "included", fx.filenames[1])
    ]
    assert [(m["role"], m["with_filename"]) for m in second] == [("later", fx.filenames[0])]
    assert first[0]["dataset_id"] == ds["dataset_id"] and first[0]["name"] == "Visible change"
    assert memberships(datasets(tmp_path), "another-site") == {}
    assert memberships(tmp_path / "missing", fx.folder_name) == {}

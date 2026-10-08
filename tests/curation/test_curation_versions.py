"""Freezing, splits, leakage checks, immutability and the handoff contract for curated datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from curation_fixtures import Fixture, Img, add_mask_result, make_run

from openfloodai.curation import (
    CONTRACT_NAME,
    CONTRACT_VERSION,
    CurationConflict,
    CurationError,
    add_observation,
    add_pair,
    create_dataset,
    dataset_view,
    freeze_version,
    list_versions,
    remove_member,
    set_split_policy,
    verify_version,
)
from openfloodai.curation.common import (
    TASK_GAUGE_HEIGHT,
    TASK_LEVEL_CHANGE,
    TASK_WATER_SEGMENTATION,
)

SAMPLE_KEYS = {
    "sample_id",
    "kind",
    "task",
    "split",
    "annotation",
    "annotation_version",
    "observations",
    "files",
    "warnings",
    "runs",
}
OBSERVATION_KEYS = {
    "observation_key",
    "site",
    "source",
    "image",
    "baseline",
    "collection",
    "dataset_group",
    "gauge",
    "configuration",
    "review",
    "machine",
}


def datasets(tmp_path: Path) -> Path:
    return tmp_path / "datasets"


def freeze(tmp_path: Path, ds: dict[str, Any], note: str = "first pilot cut") -> dict[str, Any]:
    return freeze_version(datasets(tmp_path), ds["dataset_id"], note=note, approved_by="Lead B")


def add(
    tmp_path: Path, ds: dict[str, Any], fx: Fixture, index: int = 0, **kw: Any
) -> dict[str, Any]:
    return add_observation(
        datasets(tmp_path),
        fx.sites_dir,
        ds["dataset_id"],
        folder_name=fx.folder_name,
        run_id=fx.run_id,
        filename=fx.filenames[index],
        **kw,
    )


def blocking_codes(tmp_path: Path, ds: dict[str, Any]) -> set[str]:
    return {p["code"] for p in dataset_view(datasets(tmp_path), ds["dataset_id"])["blocking"]}


def two_camera_dataset(tmp_path: Path) -> tuple[Fixture, Fixture, dict[str, Any]]:
    """Two saved runs from two different cameras, curated into one dataset (cross-run)."""

    a = make_run(
        tmp_path, [Img(day=2, level=3.5), Img(day=3, level=4.5)], folder="site-a", camera="CAM_A"
    )
    b = make_run(
        tmp_path,
        [Img(day=2, level=5.5)],
        folder="site-b",
        camera="CAM_B",
        run_id="20261005T100000Z-bbbbbbbb",
    )
    ds = create_dataset(
        datasets(tmp_path),
        name="Heights",
        task=TASK_GAUGE_HEIGHT,
        split_policy={"kind": "site_camera", "assignments": {"CAM_A": "train", "CAM_B": "test"}},
    )
    add(tmp_path, ds, a, 0)
    add(tmp_path, ds, a, 1)
    add(tmp_path, ds, b, 0)
    return a, b, ds


# ---- freezing -------------------------------------------------------------------------------


def test_examples_from_two_saved_runs_freeze_into_one_verified_version(tmp_path: Path) -> None:
    a, b, ds = two_camera_dataset(tmp_path)

    manifest = freeze(tmp_path, ds)

    root = datasets(tmp_path) / ds["dataset_id"] / "versions" / "v0001"
    assert manifest["version"] == 1 and manifest["counts"]["examples"] == 3
    for name in (
        "samples.jsonl",
        "label-definitions.json",
        "splits.json",
        "manifest.json",
        "checksums.sha256",
    ):
        assert (root / name).is_file()
    assert len(list((root / "images").glob("*.jpg"))) == 3
    assert verify_version(datasets(tmp_path), ds["dataset_id"], 1) == {"ok": True, "problems": []}
    rows = [json.loads(line) for line in (root / "samples.jsonl").read_text().splitlines()]
    assert {r["split"] for r in rows} == {"train", "test"}
    assert {tuple(r["runs"]) for r in rows} == {(a.run_id,), (b.run_id,)}


def test_the_handoff_contract_for_a_later_export_is_named_and_stable(tmp_path: Path) -> None:
    _, _, ds = two_camera_dataset(tmp_path)

    manifest = freeze(tmp_path, ds)

    assert manifest["contract"] == {"name": CONTRACT_NAME, "version": CONTRACT_VERSION}
    root = datasets(tmp_path) / ds["dataset_id"] / "versions" / "v0001"
    row = json.loads((root / "samples.jsonl").read_text().splitlines()[0])
    assert set(row) == SAMPLE_KEYS
    assert set(row["observations"][0]) == OBSERVATION_KEYS
    observation = row["observations"][0]
    # Collection group, gauge target, human label and review status are separate fields.
    assert {"group", "note"} <= set(observation["collection"])
    assert "reading" in observation["gauge"]
    assert "human_label" in observation["review"]
    assert observation["machine"]["note"] == "Machine output. It is not a label."
    # The original image bytes are kept, not an annotated screenshot.
    assert (root / row["files"]["image"]).read_bytes().startswith(b"\xff\xd8")


def test_the_same_frozen_inputs_rebuild_to_identical_content(tmp_path: Path) -> None:
    _, _, ds = two_camera_dataset(tmp_path)

    first = freeze(tmp_path, ds, "one")
    second = freeze(tmp_path, ds, "two")

    root = datasets(tmp_path) / ds["dataset_id"] / "versions"
    assert first["content_digest"] == second["content_digest"]
    for name in ("samples.jsonl", "splits.json", "label-definitions.json"):
        assert (root / "v0001" / name).read_bytes() == (root / "v0002" / name).read_bytes()


def test_a_frozen_version_is_immutable_and_tampering_is_detected(tmp_path: Path) -> None:
    a, _, ds = two_camera_dataset(tmp_path)
    freeze(tmp_path, ds)
    root = datasets(tmp_path) / ds["dataset_id"] / "versions" / "v0001"
    samples_before = (root / "samples.jsonl").read_bytes()

    # A later gauge download, run edit or source change cannot reach the frozen version.
    matches = (
        a.site_dir
        / "outputs"
        / "image-sequence-runs"
        / a.run_id
        / "inputs-used"
        / "gauge-matches.snapshot.json"
    )
    matches.write_text(
        matches.read_text().replace('"value": 3.5', '"value": 9.9'), encoding="utf-8"
    )
    (
        a.site_dir / "inputs" / "image-sequences" / a.sequence_id / "images" / a.filenames[0]
    ).write_bytes(b"x")
    assert (root / "samples.jsonl").read_bytes() == samples_before
    assert verify_version(datasets(tmp_path), ds["dataset_id"], 1)["ok"] is True

    (root / "samples.jsonl").write_bytes(samples_before + b"\n")
    result = verify_version(datasets(tmp_path), ds["dataset_id"], 1)
    assert result["ok"] is False and any(
        "samples.jsonl has changed" in p for p in result["problems"]
    )


def test_edits_after_freezing_make_a_new_version_not_a_silent_change(tmp_path: Path) -> None:
    a, _, ds = two_camera_dataset(tmp_path)
    freeze(tmp_path, ds)
    from openfloodai.curation import read_draft

    first_member = sorted(read_draft(datasets(tmp_path), ds["dataset_id"]))[0]
    remove_member(datasets(tmp_path), ds["dataset_id"], first_member)

    second = freeze(tmp_path, ds, "after removal")

    assert second["version"] == 2 and second["counts"]["examples"] == 2
    assert list_versions(datasets(tmp_path), ds["dataset_id"])[0]["examples"] == 3
    assert verify_version(datasets(tmp_path), ds["dataset_id"], 1)["ok"]


def test_an_empty_dataset_cannot_be_frozen(tmp_path: Path) -> None:
    ds = create_dataset(datasets(tmp_path), name="Empty", task=TASK_GAUGE_HEIGHT)

    with pytest.raises(CurationConflict) as raised:
        freeze(tmp_path, ds)

    assert any(p["code"] == "empty" for p in raised.value.details["blocking"])
    assert list_versions(datasets(tmp_path), ds["dataset_id"]) == []


def test_a_failed_freeze_leaves_no_partial_version(tmp_path: Path) -> None:
    a, _, ds = two_camera_dataset(tmp_path)
    blob = next((datasets(tmp_path) / ds["dataset_id"] / "blobs" / "images").glob("*.jpg"))
    blob.write_bytes(b"corrupted")

    with pytest.raises(CurationConflict):
        freeze(tmp_path, ds)

    versions = datasets(tmp_path) / ds["dataset_id"] / "versions"
    assert not versions.exists() or list(versions.iterdir()) == []


def test_segmentation_versions_keep_the_original_image_and_the_accepted_mask(
    tmp_path: Path,
) -> None:
    fx = make_run(tmp_path, [Img(day=2, human=None)])
    add_mask_result(fx, fx.filenames[0])
    ds = create_dataset(
        datasets(tmp_path),
        name="Masks",
        task=TASK_WATER_SEGMENTATION,
        split_policy={"kind": "site_camera", "assignments": {"CAM_A": "train"}},
    )
    add(tmp_path, ds, fx)

    manifest = freeze(tmp_path, ds)

    root = datasets(tmp_path) / ds["dataset_id"] / "versions" / "v0001"
    row = json.loads((root / "samples.jsonl").read_text().splitlines()[0])
    assert manifest["counts"]["masks"] == 1
    assert (root / row["files"]["masks"][0]).read_bytes().startswith(b"\x89PNG")
    assert row["annotation"]["source"] == "machine_mask_human_accepted"


def test_pair_versions_keep_both_images(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=6.5), Img(day=9, level=4.0)])
    ds = create_dataset(
        datasets(tmp_path),
        name="Change",
        task=TASK_LEVEL_CHANGE,
        change_tolerance=0.1,
        split_policy={"kind": "site_camera", "assignments": {"CAM_A": "train"}},
    )
    refs = {
        "earlier": {
            "folder_name": fx.folder_name,
            "run_id": fx.run_id,
            "filename": fx.filenames[0],
        },
        "later": {"folder_name": fx.folder_name, "run_id": fx.run_id, "filename": fx.filenames[1]},
    }
    add_pair(
        datasets(tmp_path),
        fx.sites_dir,
        ds["dataset_id"],
        earlier=refs["earlier"],
        later=refs["later"],
    )

    manifest = freeze(tmp_path, ds)

    root = datasets(tmp_path) / ds["dataset_id"] / "versions" / "v0001"
    row = json.loads((root / "samples.jsonl").read_text().splitlines()[0])
    assert manifest["counts"]["images"] == 2 and row["kind"] == "pair"
    assert set(row["files"]) == {"earlier_image", "later_image"}
    assert verify_version(datasets(tmp_path), ds["dataset_id"], 1)["ok"]


# ---- splits and leakage ---------------------------------------------------------------------


def test_every_example_needs_a_split_and_nothing_is_split_at_random(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2), Img(day=3)])
    ds = create_dataset(datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT)
    add(tmp_path, ds, fx, 0)
    add(tmp_path, ds, fx, 1)

    assert "split_unassigned" in blocking_codes(tmp_path, ds)

    set_split_policy(
        datasets(tmp_path),
        ds["dataset_id"],
        {"kind": "site_camera", "assignments": {"CAM_A": "train"}},
    )
    view = dataset_view(datasets(tmp_path), ds["dataset_id"])
    # Neighbouring frames of one camera always share a split.
    assert {m["split"] for m in view["members"]} == {"train"}


def test_too_few_independent_cameras_is_reported_as_a_gap_not_hidden(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2)])
    ds = create_dataset(
        datasets(tmp_path),
        name="Heights",
        task=TASK_GAUGE_HEIGHT,
        split_policy={"kind": "site_camera", "assignments": {"CAM_A": "train"}},
    )
    add(tmp_path, ds, fx)

    view = dataset_view(datasets(tmp_path), ds["dataset_id"])

    gap = next(g for g in view["readiness_gaps"] if g["code"] == "insufficient_independent_cameras")
    assert "validation" in gap["message"] and "test" in gap["message"]
    assert view["ready_to_freeze"] is True  # a gap is reported; it does not fabricate a split
    manifest = freeze(tmp_path, ds)
    assert manifest["readiness_gaps"]
    splits = json.loads(
        (datasets(tmp_path) / ds["dataset_id"] / "versions" / "v0001" / "splits.json").read_text()
    )
    assert splits["meets_207_publication_rule"] is False


def test_locked_validation_data_can_only_be_in_the_test_split(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, dataset_group="locked_validation")])
    ds = create_dataset(
        datasets(tmp_path),
        name="Heights",
        task=TASK_GAUGE_HEIGHT,
        split_policy={"kind": "site_camera", "assignments": {"CAM_A": "train"}},
    )
    add(tmp_path, ds, fx)

    assert "locked_not_test" in blocking_codes(tmp_path, ds)
    set_split_policy(
        datasets(tmp_path),
        ds["dataset_id"],
        {"kind": "site_camera", "assignments": {"CAM_A": "test"}},
    )
    assert blocking_codes(tmp_path, ds) == set()


def test_a_camera_with_locked_data_cannot_leak_its_other_data_into_training(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, dataset_group="locked_validation"), Img(day=3)])
    ds = create_dataset(
        datasets(tmp_path),
        name="Heights",
        task=TASK_GAUGE_HEIGHT,
        split_policy={"kind": "site_camera", "assignments": {"CAM_A": "test"}},
    )
    add(tmp_path, ds, fx, 0)
    add(tmp_path, ds, fx, 1)
    assert blocking_codes(tmp_path, ds) == set()  # all test: fine
    # Moving the camera to training would leak the locked frames.
    set_split_policy(
        datasets(tmp_path),
        ds["dataset_id"],
        {"kind": "site_camera", "assignments": {"CAM_A": "train"}},
    )
    assert {"locked_not_test", "locked_camera_leak"} <= blocking_codes(tmp_path, ds)


def test_identical_image_bytes_in_two_splits_block_the_freeze(tmp_path: Path) -> None:
    a = make_run(tmp_path, [Img(day=2, seed=5)], folder="site-a", camera="CAM_A")
    b = make_run(
        tmp_path,
        [Img(day=3, seed=5)],
        folder="site-b",
        camera="CAM_B",
        run_id="20261005T100000Z-bbbbbbbb",
    )
    ds = create_dataset(
        datasets(tmp_path),
        name="Heights",
        task=TASK_GAUGE_HEIGHT,
        split_policy={"kind": "site_camera", "assignments": {"CAM_A": "train", "CAM_B": "test"}},
    )
    add(tmp_path, ds, a)
    add(tmp_path, ds, b)

    view = dataset_view(datasets(tmp_path), ds["dataset_id"])

    assert view["duplicates"] and len(view["duplicates"][0]["members"]) == 2
    assert "duplicate_content_across_splits" in {p["code"] for p in view["blocking"]}
    with pytest.raises(CurationConflict):
        freeze(tmp_path, ds)


def test_identical_content_with_conflicting_annotations_blocks_the_freeze(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, seed=5, level=3.0), Img(day=3, seed=5, level=4.0)])
    ds = create_dataset(
        datasets(tmp_path),
        name="Heights",
        task=TASK_GAUGE_HEIGHT,
        split_policy={"kind": "site_camera", "assignments": {"CAM_A": "train"}},
    )
    add(tmp_path, ds, fx, 0)
    add(tmp_path, ds, fx, 1)

    assert "conflicting_annotations" in blocking_codes(tmp_path, ds)


def test_a_pair_dataset_keeps_its_two_images_in_one_split(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=6.5), Img(day=20, level=4.0)])
    blocks = {
        "kind": "single_site_time_block",
        "site_id": fx.site_id,
        "blocks": [
            {"split": "train", "start_date": "2026-01-01", "end_date": "2026-01-10"},
            {"split": "test", "start_date": "2026-01-11", "end_date": "2026-01-31"},
        ],
    }
    ds = create_dataset(
        datasets(tmp_path), name="Change", task=TASK_LEVEL_CHANGE, split_policy=blocks
    )
    refs = {
        "earlier": {
            "folder_name": fx.folder_name,
            "run_id": fx.run_id,
            "filename": fx.filenames[0],
        },
        "later": {"folder_name": fx.folder_name, "run_id": fx.run_id, "filename": fx.filenames[1]},
    }
    add_pair(
        datasets(tmp_path),
        fx.sites_dir,
        ds["dataset_id"],
        earlier=refs["earlier"],
        later=refs["later"],
    )

    assert "pair_crosses_split" in blocking_codes(tmp_path, ds)


def test_a_single_site_time_block_split_is_labelled_site_specific_only(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2), Img(day=20)])
    blocks = {
        "kind": "single_site_time_block",
        "site_id": fx.site_id,
        "blocks": [
            {"split": "train", "start_date": "2026-01-01", "end_date": "2026-01-10"},
            {"split": "test", "start_date": "2026-01-11", "end_date": "2026-01-31"},
        ],
    }
    ds = create_dataset(
        datasets(tmp_path), name="Heights", task=TASK_GAUGE_HEIGHT, split_policy=blocks
    )
    add(tmp_path, ds, fx, 0)
    add(tmp_path, ds, fx, 1)

    manifest = freeze(tmp_path, ds)

    splits = json.loads(
        (datasets(tmp_path) / ds["dataset_id"] / "versions" / "v0001" / "splits.json").read_text()
    )
    assert splits["generalization_scope"] == "single_site_time_block_evaluation_only"
    assert splits["meets_207_publication_rule"] is False
    assert any(g["code"] == "site_specific_evaluation_only" for g in manifest["readiness_gaps"])


@pytest.mark.parametrize(
    "policy",
    [
        {"kind": "random"},
        {"kind": "site_camera", "assignments": {"CAM_A": "holdout"}},
        {
            "kind": "single_site_time_block",
            "site_id": "s",
            "blocks": [
                {"split": "train", "start_date": "2026-01-01", "end_date": "2026-01-15"},
                {"split": "test", "start_date": "2026-01-10", "end_date": "2026-01-20"},
            ],
        },
        {"kind": "single_site_time_block", "site_id": "s", "blocks": []},
    ],
)
def test_invalid_split_policies_are_refused(tmp_path: Path, policy: dict[str, Any]) -> None:
    with pytest.raises(CurationError):
        create_dataset(datasets(tmp_path), name="Bad", task=TASK_GAUGE_HEIGHT, split_policy=policy)

"""Building a clean, deterministic, leakage-safe release from a frozen curated dataset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from release_helpers import (
    RUN_IDS,
    Img,
    add_mask_result,
    approvals,
    data_dir,
    frozen_dataset,
)

from openfloodai.release import ReleaseError, build_release, verify_release
from openfloodai.release.builder import channel_for


def build(
    tmp_path: Path,
    dataset_id: str,
    *,
    version: str = "v0.1",
    out: str = "out",
    policy: Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    root = data_dir(tmp_path)
    return build_release(
        datasets_dir=root / "datasets",
        dataset_id=dataset_id,
        dataset_version=1,
        output_dir=tmp_path / out,
        release_version=version,
        notes="First small reviewed sample.",
        policy_path=policy or root / "release-policy.json",
        reference_dir=root / "reference",
        **kwargs,
    )


def rows(tmp_path: Path, version: str = "v0.1", out: str = "out") -> list[dict[str, Any]]:
    path = tmp_path / out / f"openfloodai-dataset-{version}" / "metadata.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def release_dir(tmp_path: Path, version: str = "v0.1", out: str = "out") -> Path:
    return tmp_path / out / f"openfloodai-dataset-{version}"


# ---- a clean release ------------------------------------------------------------------------


def test_a_frozen_dataset_builds_a_clean_verified_release(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))

    manifest = build(tmp_path, dataset_id)

    root = release_dir(tmp_path)
    for name in (
        "README.md",
        "LICENSE-DATA.md",
        "CHANGELOG.md",
        "metadata.jsonl",
        "sites.json",
        "checksums.sha256",
        "release-manifest.json",
        "REJECTIONS.md",
        "RELEASE-CHECKLIST.md",
        "splits/train.jsonl",
        "splits/validation.jsonl",
        "splits/test.jsonl",
    ):
        assert (root / name).is_file(), name
    assert manifest["channel"] == "draft" and manifest["counts"]["released"] == 6
    assert verify_release(root) == {"ok": True, "problems": []}
    assert not (tmp_path / "out" / ".building-v0.1").exists()


def test_each_split_holds_different_cameras_and_every_example_is_in_exactly_one(
    tmp_path: Path,
) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))
    build(tmp_path, dataset_id)

    by_split: dict[str, set[str]] = {}
    for row in rows(tmp_path):
        by_split.setdefault(row["split"], set()).add(row["camera_id"])

    assert by_split == {"train": {"CAM_A"}, "validation": {"CAM_B"}, "test": {"CAM_C"}}
    root = release_dir(tmp_path)
    in_files = [
        json.loads(line)["sample_id"]
        for name in ("train", "validation", "test")
        for line in (root / "splits" / f"{name}.jsonl").read_text().splitlines()
    ]
    assert sorted(in_files) == sorted(r["sample_id"] for r in rows(tmp_path))


def test_rows_keep_human_labels_apart_from_machine_output_and_the_collection_group(
    tmp_path: Path,
) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))
    build(tmp_path, dataset_id)

    row = rows(tmp_path)[0]

    assert (
        row["human_label"] == "no_water_level_change" and row["review_status"] == "human_reviewed"
    )
    assert row["machine_result"] == "no_water_level_change" and "machine_score" in row
    assert row["collection_group"] == "middle"  # kept, but not a label
    assert row["source_system"] == "usgs_nims" and "U.S. Geological Survey" in row["source_credit"]
    assert row["gauge_value"] in (3.5, 4.5) and row["gauge_unit"] == "ft"
    assert row["image_sha256"] and row["baseline_file_name"]
    assert json.loads(row["annotation"])["kind"] == "gauge_height"


def test_images_are_original_bytes_laid_out_by_site_and_camera(tmp_path: Path) -> None:
    _, dataset_id, runs = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))
    build(tmp_path, dataset_id)

    row = next(r for r in rows(tmp_path) if r["camera_id"] == "CAM_A")

    assert row["file_name"].startswith("images/site-a_sid/CAM_A/CAM_A-")
    kept = (release_dir(tmp_path) / row["file_name"]).read_bytes()
    original = (
        runs["CAM_A"].site_dir
        / "inputs"
        / "image-sequences"
        / runs["CAM_A"].sequence_id
        / "images"
        / next(n for n in runs["CAM_A"].filenames if runs["CAM_A"].shas[n] == row["image_sha256"])
    ).read_bytes()
    assert kept == original and kept.startswith(b"\xff\xd8")


def test_locations_are_generalized_and_internal_fields_never_appear(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(
        tmp_path, images={"CAM_A": [Img(day=2, note="PRIVATE NOTE about the landowner")]}
    )
    approvals(data_dir(tmp_path))
    build(tmp_path, dataset_id)

    root = release_dir(tmp_path)
    sites = json.loads((root / "sites.json").read_text())["sites"]
    first = next(s for s in sites if s["camera_id"] == "CAM_A")
    assert first["location"] == {
        "latitude": 40.1,
        "longitude": -106.0,
        "precision": "generalized_1_decimals",
    }
    everything = "".join(
        p.read_text()
        for p in root.rglob("*")
        if p.is_file() and p.suffix in {".json", ".jsonl", ".md"}
    )
    for forbidden in (
        "PRIVATE NOTE",
        "/Users/",
        "run_id",
        "folder_name",
        RUN_IDS["CAM_A"],
        "reviewer_id",
    ):
        assert forbidden not in everything, forbidden


def test_the_dataset_card_documents_sources_schema_limits_and_licensing(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))
    build(tmp_path, dataset_id)

    card = (release_dir(tmp_path) / "README.md").read_text()

    assert card.startswith("---\n") and "license: other" in card and "- split: train" in card
    for section in (
        "Sources and credit",
        "Fields",
        "Intended use and limits",
        "Privacy",
        "Licensing",
        "Citation",
    ):
        assert f"## {section}" in card
    plain = " ".join(card.replace("*", "").split())
    assert "does not imply endorsement" in plain and "not a flood detector" in plain
    notice = (release_dir(tmp_path) / "LICENSE-DATA.md").read_text()
    assert "CC-BY-4.0" in notice and "U.S. Geological Survey" in notice
    assert "endorsement" in " ".join(notice.split())


# ---- determinism and versioning -------------------------------------------------------------


def test_the_same_frozen_inputs_rebuild_the_identical_release(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))

    first = build(tmp_path, dataset_id, out="one")
    second = build(tmp_path, dataset_id, out="two")

    assert first["content_digest"] == second["content_digest"]
    assert (release_dir(tmp_path, out="one") / "checksums.sha256").read_bytes() == (
        release_dir(tmp_path, out="two") / "checksums.sha256"
    ).read_bytes()


def test_a_release_is_never_replaced(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))
    build(tmp_path, dataset_id)
    before = (release_dir(tmp_path) / "checksums.sha256").read_bytes()

    with pytest.raises(ReleaseError, match="never replaced"):
        build(tmp_path, dataset_id)

    assert (release_dir(tmp_path) / "checksums.sha256").read_bytes() == before


def test_release_versions_choose_a_channel_and_a_new_version_extends_the_changelog(
    tmp_path: Path,
) -> None:
    assert (channel_for("v0.1"), channel_for("v0.2"), channel_for("v1.0")) == (
        "draft",
        "draft",
        "public",
    )
    with pytest.raises(ReleaseError):
        channel_for("1.0")
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))
    build(tmp_path, dataset_id)

    build(tmp_path, dataset_id, version="v0.2", previous_release=release_dir(tmp_path))

    log = (release_dir(tmp_path, "v0.2") / "CHANGELOG.md").read_text()
    assert log.index("## v0.2") < log.index("## v0.1")


def test_a_v1_release_needs_cameras_in_all_three_splits(tmp_path: Path) -> None:
    two = (("site-a", "CAM_A", "train"), ("site-b", "CAM_B", "test"))
    _, dataset_id, _ = frozen_dataset(tmp_path, cameras=two)
    approvals(data_dir(tmp_path))

    draft = build(tmp_path, dataset_id)
    assert draft["publication_ready"] is False
    assert any(g["code"] == "split_has_no_camera" for g in draft["readiness_gaps"])
    with pytest.raises(ReleaseError, match="train, validation and test"):
        build(tmp_path, dataset_id, version="v1.0")


def test_a_v1_release_with_all_splits_is_publication_ready(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))

    manifest = build(tmp_path, dataset_id, version="v1.0")

    assert manifest["channel"] == "public" and manifest["publication_ready"] is True


# ---- the licensing and privacy gate ---------------------------------------------------------


def test_nothing_is_released_without_a_recorded_annotation_license(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)

    with pytest.raises(ReleaseError, match="annotation license"):
        build(tmp_path, dataset_id)
    assert not (tmp_path / "out").exists()


def test_an_unapproved_source_is_excluded_and_explained(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path, source_system="third_party_blog")
    approvals(data_dir(tmp_path))  # only usgs_nims is approved

    with pytest.raises(ReleaseError) as raised:
        build(tmp_path, dataset_id)

    assert "No example passed" in str(raised.value)
    assert {d["code"] for d in raised.value.details} == {"source_not_approved"}
    assert not (tmp_path / "out" / "openfloodai-dataset-v0.1").exists()


def test_a_site_without_a_privacy_review_is_excluded_while_others_are_released(
    tmp_path: Path,
) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path), sites=("site-a", "site-c"))

    manifest = build(tmp_path, dataset_id)

    assert {r["camera_id"] for r in rows(tmp_path)} == {"CAM_A", "CAM_C"}
    assert manifest["counts"]["rejected"] == 2
    report = (release_dir(tmp_path) / "REJECTIONS.md").read_text()
    assert "privacy_review_missing" in report and "site-b_sid" in report
    rejected = [
        json.loads(line)
        for line in (release_dir(tmp_path) / "rejected.jsonl").read_text().splitlines()
    ]
    assert {r["camera_id"] for r in rejected} == {"CAM_B"}


def test_identical_images_in_a_split_are_released_once_and_the_duplicate_is_reported() -> None:
    from openfloodai.release import policy as release_policy
    from openfloodai.release.builder import _select

    def sample(sample_id: str) -> dict[str, Any]:
        return {
            "sample_id": sample_id,
            "kind": "observation",
            "observations": [
                {
                    "observation_key": sample_id,
                    "site": {"site_id": "s_sid", "camera_id": "CAM"},
                    "source": {
                        "source_system": "usgs_nims",
                        "source_url": "https://example.test/x.jpg",
                        "captured_at_utc": "2026-01-02T18:00:00+00:00",
                    },
                    "image": {"sha256": "ab" * 32},
                }
            ],
        }

    pol: dict[str, Any] = {
        "sources": {"usgs_nims": {"status": "approved"}},
        "sites": {"s_sid": {"privacy_review": {"status": "approved"}}},
    }
    assert release_policy.source_approved(pol, "usgs_nims")

    accepted, rejected = _select([sample("b"), sample("a")], {"a": "train", "b": "train"}, pol)

    assert [s["sample_id"] for s, _ in accepted] == ["a"]  # the first by id is kept
    assert [r["sample_id"] for r in rejected] == ["b"]
    assert rejected[0]["reasons"][0]["code"] == "duplicate_image"


def test_a_time_block_dataset_cannot_be_released(tmp_path: Path) -> None:
    from openfloodai.curation import set_split_policy

    datasets_dir, dataset_id, runs = frozen_dataset(
        tmp_path, cameras=(("site-a", "CAM_A", "train"),)
    )
    approvals(data_dir(tmp_path))
    set_split_policy(
        datasets_dir,
        dataset_id,
        {
            "kind": "single_site_time_block",
            "site_id": "site-a_sid",
            "blocks": [{"split": "train", "start_date": "2026-01-01", "end_date": "2026-01-31"}],
        },
    )
    from openfloodai.curation import freeze_version

    freeze_version(
        datasets_dir, dataset_id, note="blocks", approved_by="me", sites_dir=runs["CAM_A"].sites_dir
    )

    root = data_dir(tmp_path)
    with pytest.raises(ReleaseError, match="time-block"):
        build_release(
            datasets_dir=datasets_dir,
            dataset_id=dataset_id,
            dataset_version=2,
            output_dir=tmp_path / "out",
            release_version="v0.1",
            notes="n",
            policy_path=root / "release-policy.json",
            reference_dir=root / "reference",
        )


def test_a_frozen_version_that_fails_its_checksums_is_not_released(tmp_path: Path) -> None:
    datasets_dir, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))
    samples = datasets_dir / dataset_id / "versions" / "v0001" / "samples.jsonl"
    samples.write_text(samples.read_text() + "\n")

    with pytest.raises(ReleaseError, match="checksum"):
        build(tmp_path, dataset_id)


# ---- other tasks ----------------------------------------------------------------------------


def test_a_segmentation_release_includes_the_accepted_masks(tmp_path: Path) -> None:
    root = data_dir(tmp_path)
    datasets_dir, dataset_id, _ = _segmentation_dataset(tmp_path)
    approvals(root)

    manifest = build(tmp_path, dataset_id)

    row = rows(tmp_path)[0]
    masks = json.loads(row["mask_files"])
    assert manifest["counts"]["masks"] == len(masks) == 1
    assert (release_dir(tmp_path) / masks[0]).read_bytes().startswith(b"\x89PNG")
    assert json.loads(row["annotation"])["source"] == "machine_mask_human_accepted"
    assert verify_release(release_dir(tmp_path))["ok"]
    del datasets_dir


def _segmentation_dataset(
    tmp_path: Path, human: str | None = None
) -> tuple[Path, str, dict[str, Any]]:
    from release_helpers import make_data, make_run

    from openfloodai.curation import add_observation, create_dataset, freeze_version

    root = make_data(tmp_path)
    fx = make_run(
        root, [Img(day=2, human=human)], folder="site-a", camera="CAM_A", run_id=RUN_IDS["CAM_A"]
    )
    add_mask_result(fx, fx.filenames[0])
    ds = create_dataset(
        root / "datasets",
        name="Masks",
        task="water_segmentation",
        split_policy={"kind": "site_camera", "assignments": {"CAM_A": "train"}},
    )
    add_observation(
        root / "datasets",
        fx.sites_dir,
        ds["dataset_id"],
        folder_name=fx.folder_name,
        run_id=fx.run_id,
        filename=fx.filenames[0],
    )
    freeze_version(
        root / "datasets", ds["dataset_id"], note="m", approved_by="me", sites_dir=fx.sites_dir
    )
    return root / "datasets", ds["dataset_id"], {}


def test_unjudgeable_images_stay_in_the_release_as_explicit_quality_classes(tmp_path: Path) -> None:
    _, dataset_id, _ = _segmentation_dataset(tmp_path, human="cannot_judge_water_level")
    approvals(data_dir(tmp_path))

    build(tmp_path, dataset_id)

    row = rows(tmp_path)[0]
    assert row["human_label"] == "cannot_judge_water_level"
    assert row["review_status"] == "human_reviewed"


def test_a_classification_release_publishes_definitions_without_private_names(
    tmp_path: Path,
) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path, task="level_classification")
    approvals(data_dir(tmp_path))
    build(tmp_path, dataset_id)

    definitions = json.loads((release_dir(tmp_path) / "label-definitions.json").read_text())[
        "definitions"
    ]
    text = json.dumps(definitions)

    assert set(definitions) == {"site-a_sid", "site-b_sid", "site-c_sid"}
    assert "Private Author" not in text and "Private Approver" not in text
    assert definitions["site-a_sid"]["rationale"] == "Local marks"
    assert {json.loads(r["annotation"])["category"] for r in rows(tmp_path)} <= {"low", "high"}


def test_a_rising_falling_release_keeps_both_images_of_each_pair(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path, task="level_change")
    approvals(data_dir(tmp_path))
    manifest = build(tmp_path, dataset_id)

    row = rows(tmp_path)[0]

    assert (
        row["kind"] == "pair"
        and row["later_file_name"]
        and row["later_file_name"] != row["file_name"]
    )
    assert (release_dir(tmp_path) / row["later_file_name"]).is_file()
    assert json.loads(row["annotation"])["kind"] == "level_change"
    assert manifest["counts"]["released"] == 3


# ---- parquet is optional --------------------------------------------------------------------


def test_parquet_is_optional_and_explains_how_to_get_it(tmp_path: Path) -> None:
    import importlib.util

    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))
    if importlib.util.find_spec("pyarrow") is None:
        with pytest.raises(ReleaseError, match=r"openfloodai\[export\]"):
            build(tmp_path, dataset_id, write_parquet=True)
        assert not (tmp_path / "out" / "openfloodai-dataset-v0.1").exists()
    else:
        build(tmp_path, dataset_id, write_parquet=True)
        assert (release_dir(tmp_path) / "metadata.parquet").is_file()
        assert verify_release(release_dir(tmp_path))["ok"]

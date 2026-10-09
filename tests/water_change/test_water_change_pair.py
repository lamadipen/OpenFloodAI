"""Resolving saved observations and masks into a frozen water-change measurement (Issue #222)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from water_helpers import (
    CROP,
    TRANSFORM,
    Fixture,
    add_water_mask,
    tree_fingerprint,
    two_image_run,
    water,
)

from openfloodai.curation.common import CurationError
from openfloodai.water_change import EndpointRef, measure_pair

RUN_A = "20261002T100000Z-aaaaaaaa"
RUN_B = "20261003T100000Z-bbbbbbbb"


def refs(fixture: Fixture) -> tuple[EndpointRef, EndpointRef]:
    return (
        EndpointRef(fixture.run_id, fixture.filenames[0]),
        EndpointRef(fixture.run_id, fixture.filenames[1]),
    )


def measure(fixture: Fixture, **kwargs: Any) -> dict[str, Any]:
    earlier, later = refs(fixture)
    kwargs.setdefault("framing_confirmed_by", "Dipen")
    return measure_pair(fixture.sites_dir, fixture.folder_name, earlier, later, **kwargs)


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    fx = two_image_run(tmp_path)
    add_water_mask(fx, 0, water(10), run_id=RUN_A)
    add_water_mask(fx, 1, water(18), run_id=RUN_B)
    return fx


def test_accepted_masks_give_a_measurement_with_frozen_provenance(fixture: Fixture) -> None:
    result = measure(fixture)
    evidence = result["evidence"]
    assert evidence["status"] == "available"
    # ROI is 20 x 11 = 220 px; earlier 7 columns x 11 rows = 77, later 15 x 11 = 165.
    measurement = evidence["quality"]["measurement"]
    assert measurement["roi_pixels"] == 220
    assert measurement["earlier_water_pixels"] == 77 and measurement["later_water_pixels"] == 165
    assert evidence["value"] == pytest.approx(40.0)
    assert evidence["quality"]["roi_px"] == CROP
    for side in ("earlier", "later"):
        frozen = result[side]
        assert len(frozen["image_sha256"]) == 64
        assert len(frozen["mask_sha256s"]) == 1
        assert frozen["review_decision"] == "accepted"
        assert frozen["segmentation_run_id"] in {RUN_A, RUN_B}
        assert frozen["transform"] == TRANSFORM
    assert evidence["window_start"] < evidence["window_end"]
    assert result["context"]["earlier_gauge"]["usable"] is True


def test_measurement_is_frozen_once_and_original_records_are_untouched(fixture: Fixture) -> None:
    before = tree_fingerprint(fixture.site_dir)
    first = measure(fixture)
    after = tree_fingerprint(fixture.site_dir)
    created = set(after) - set(before)
    assert len(created) == 1 and next(iter(created)).startswith("outputs/water-change-pairs/")
    assert {k: v for k, v in after.items() if k in before} == before
    again = measure(fixture)
    assert again["reused"] is True and again["pair_key"] == first["pair_key"]
    assert again["evidence"]["record_id"] == first["evidence"]["record_id"]
    assert tree_fingerprint(fixture.site_dir) == after


def test_dry_run_writes_nothing(fixture: Fixture) -> None:
    before = tree_fingerprint(fixture.site_dir)
    assert measure(fixture, freeze=False)["path"] is None
    assert tree_fingerprint(fixture.site_dir) == before


def test_a_new_review_decision_creates_a_new_frozen_measurement(fixture: Fixture) -> None:
    first = measure(fixture)
    reviews = fixture.site_dir / "outputs" / "hosted-sam-runs" / RUN_B / "reviews.jsonl"
    with reviews.open("a", encoding="utf-8") as handle:
        result_id = json.loads(reviews.read_text().splitlines()[0])["result_id"]
        handle.write(
            json.dumps(
                {
                    "result_id": result_id,
                    "decision": "rejected",
                    "reviewed_at_utc": "2026-10-08T00:00:00+00:00",
                }
            )
            + "\n"
        )
    second = measure(fixture)
    assert second["pair_key"] != first["pair_key"]
    assert second["evidence"]["status"] == "unavailable"
    assert "LATER_MASK_REJECTED" in second["evidence"]["reason_codes"]


@pytest.mark.parametrize(
    ("review", "code"),
    [
        (None, "LATER_MASK_UNREVIEWED"),
        ("rejected", "LATER_MASK_REJECTED"),
        ("needs_correction", "LATER_MASK_NEEDS_CORRECTION"),
    ],
)
def test_unaccepted_masks_are_unavailable_never_zero(
    tmp_path: Path, review: str | None, code: str
) -> None:
    fx = two_image_run(tmp_path)
    add_water_mask(fx, 0, water(10), run_id=RUN_A)
    add_water_mask(fx, 1, water(18), review=review, run_id=RUN_B)
    evidence = measure(fx)["evidence"]
    assert evidence["status"] == "unavailable"
    assert code in evidence["reason_codes"]
    assert evidence["value"] is None


def test_missing_mask_is_unavailable(tmp_path: Path) -> None:
    fx = two_image_run(tmp_path)
    add_water_mask(fx, 0, water(10), run_id=RUN_A)
    evidence = measure(fx)["evidence"]
    assert evidence["status"] == "unavailable"
    assert "LATER_MASK_MISSING" in evidence["reason_codes"] and evidence["value"] is None


def test_a_riverbank_mask_is_never_water(tmp_path: Path) -> None:
    fx = two_image_run(tmp_path)
    add_water_mask(fx, 0, water(10), run_id=RUN_A)
    add_water_mask(fx, 1, water(18), run_id=RUN_B, prompt="riverbank")
    evidence = measure(fx)["evidence"]
    assert evidence["status"] == "unavailable" and evidence["value"] is None


def test_accepted_no_match_is_not_a_verified_empty_mask(tmp_path: Path) -> None:
    fx = two_image_run(tmp_path)
    add_water_mask(fx, 0, water(10), run_id=RUN_A)
    add_water_mask(fx, 1, water(18), run_id=RUN_B, status="no_match", detections=False)
    evidence = measure(fx)["evidence"]
    assert evidence["status"] == "unavailable"
    assert "LATER_NO_MATCH_NOT_VERIFIED_EMPTY" in evidence["reason_codes"]


def test_several_detections_are_united_and_overlap_counts_once(tmp_path: Path) -> None:
    fx = two_image_run(tmp_path)
    add_water_mask(fx, 0, water(10), run_id=RUN_A)
    add_water_mask(fx, 1, water(10), run_id=RUN_B, masks=[water(10), water(10, x0=8)])
    measurement = measure(fx)["evidence"]["quality"]["measurement"]
    assert measurement["later_water_pixels"] == 77
    assert measurement["newly_wet_pixels"] == 0


def test_reversed_and_identical_order_are_refused(fixture: Fixture) -> None:
    earlier, later = refs(fixture)
    reversed_ = measure_pair(
        fixture.sites_dir, fixture.folder_name, later, earlier, framing_confirmed_by="Dipen"
    )
    assert reversed_["evidence"]["status"] == "invalid"
    assert "TIMESTAMPS_REVERSED" in reversed_["evidence"]["reason_codes"]
    same = measure_pair(
        fixture.sites_dir, fixture.folder_name, earlier, earlier, framing_confirmed_by="Dipen"
    )
    assert "TIMESTAMPS_EQUAL" in same["evidence"]["reason_codes"]
    assert same["evidence"]["value"] is None


def test_changed_watched_area_between_endpoints_is_invalid(tmp_path: Path) -> None:
    fx = two_image_run(tmp_path)
    add_water_mask(fx, 0, water(10), run_id=RUN_A)
    shifted = {"crop_px": [4, 4, 23, 15], "source_size": [32, 24]}
    add_water_mask(fx, 1, water(18), run_id=RUN_B, transform=shifted)
    evidence = measure(fx)["evidence"]
    assert evidence["status"] == "invalid" and "WATCHED_AREA_CHANGED" in evidence["reason_codes"]


def test_a_mask_with_the_wrong_image_size_is_invalid(tmp_path: Path) -> None:
    fx = two_image_run(tmp_path)
    add_water_mask(fx, 0, water(10), run_id=RUN_A)
    bad = {"crop_px": CROP, "source_size": [64, 48]}
    add_water_mask(fx, 1, water(18), run_id=RUN_B, transform=bad)
    evidence = measure(fx)["evidence"]
    assert evidence["status"] in {"invalid", "unavailable"} and evidence["value"] is None
    assert any("SIZE" in code for code in evidence["reason_codes"])


def test_framing_must_be_confirmed_by_a_person(fixture: Fixture) -> None:
    evidence = measure(fixture, framing_confirmed_by=None)["evidence"]
    assert evidence["status"] == "unavailable"
    assert "FRAMING_NOT_CONFIRMED" in evidence["reason_codes"]


def test_a_changed_source_image_blocks_the_measurement(fixture: Fixture) -> None:
    image = (
        fixture.site_dir / "inputs" / "image-sequences" / fixture.sequence_id / "images"
    ) / fixture.filenames[1]
    image.write_bytes(image.read_bytes() + b"tamper")
    evidence = measure(fixture)["evidence"]
    assert evidence["status"] == "unavailable"
    assert "LATER_SOURCE_CHANGED" in evidence["reason_codes"]


def test_lighting_change_with_identical_masks_measures_no_change(tmp_path: Path) -> None:
    fx = two_image_run(tmp_path)  # the two images have unrelated pixel content by construction
    add_water_mask(fx, 0, water(12), run_id=RUN_A)
    add_water_mask(fx, 1, water(12), run_id=RUN_B)
    evidence = measure(fx)["evidence"]
    assert evidence["status"] == "available" and evidence["value"] == 0.0
    assert evidence["quality"]["measurement"]["changed_fraction"] == 0.0


def test_different_cameras_are_not_compared(tmp_path: Path) -> None:
    first = two_image_run(tmp_path, camera="CAM_A", run_id="20261001T100000Z-aaaaaaaa")
    second = two_image_run(tmp_path, camera="CAM_B", run_id="20261001T110000Z-cccccccc")
    add_water_mask(first, 0, water(10), run_id=RUN_A)
    add_water_mask(second, 1, water(18), run_id=RUN_B)
    result = measure_pair(
        first.sites_dir,
        first.folder_name,
        EndpointRef(first.run_id, first.filenames[0]),
        EndpointRef(second.run_id, second.filenames[1]),
        framing_confirmed_by="Dipen",
    )
    assert "DIFFERENT_CAMERA" in result["evidence"]["reason_codes"]
    assert result["evidence"]["status"] == "invalid"


def test_unknown_site_or_image_is_a_clear_error_or_unavailable(fixture: Fixture) -> None:
    earlier, later = refs(fixture)
    with pytest.raises(CurationError):
        measure_pair(fixture.sites_dir, "no-such-site", earlier, later, framing_confirmed_by="x")
    with pytest.raises(CurationError):
        measure_pair(fixture.sites_dir, "../x", earlier, later, framing_confirmed_by="x")
    missing = EndpointRef(fixture.run_id, "CAM_A___2026-01-09T10-00-00Z.jpg")
    result = measure_pair(
        fixture.sites_dir, fixture.folder_name, earlier, missing, framing_confirmed_by="Dipen"
    )
    assert result["evidence"]["status"] in {"unavailable", "invalid"}
    assert "LATER_IMAGE_NOT_AVAILABLE" in result["evidence"]["reason_codes"]

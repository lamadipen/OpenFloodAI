"""Comparing any two saved images of one camera: ordering, unavailable reasons and no writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from water_helpers import (
    CROP,
    Fixture,
    add_water_mask,
    tree_fingerprint,
    two_image_run,
    water,
)

from openfloodai.curation.common import CurationError
from openfloodai.water_change import EndpointRef, compare

RUN_A = "20261002T100000Z-aaaaaaaa"
RUN_B = "20261003T100000Z-bbbbbbbb"
RUN_C = "20261004T100000Z-cccccccc"
SECOND_RUN = "20261001T120000Z-dddddddd"


def write_summary(fx: Fixture) -> None:
    """The saved download summary the picker lists images from."""

    sequence = fx.site_dir / "inputs" / "image-sequences" / fx.sequence_id
    rows = [
        json.loads(line)
        for line in (sequence / "sequence-manifest.jsonl").read_text().splitlines()
        if line
    ]
    (sequence / "download-summary.json").write_text(
        json.dumps({"sequence_id": fx.sequence_id, "records": rows}), encoding="utf-8"
    )


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    fixture = two_image_run(tmp_path)
    write_summary(fixture)
    add_water_mask(fixture, 0, water(10), run_id=RUN_A)
    add_water_mask(fixture, 1, water(18), run_id=RUN_B)
    return fixture


def refs(fx: Fixture) -> tuple[EndpointRef, EndpointRef]:
    return (
        EndpointRef(fx.run_id, fx.filenames[0]),
        EndpointRef(fx.run_id, fx.filenames[1]),
    )


def go(fx: Fixture, a: EndpointRef, b: EndpointRef, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("framing_confirmed", True)
    return compare.compare_pair(fx.sites_dir, fx.folder_name, a, b, **kwargs)


def test_the_pair_is_ordered_by_capture_time_whichever_order_it_was_chosen(fx: Fixture) -> None:
    early, late = refs(fx)
    forward = go(fx, early, late)
    backward = go(fx, late, early)
    for result in (forward, backward):
        assert result["earlier"]["filename"] == fx.filenames[0]
        assert result["later"]["filename"] == fx.filenames[1]
        assert result["available"] is True and result["evidence"]["value"] == pytest.approx(40.0)
        assert result["elapsed_seconds"] == 24 * 3600
    assert forward["evidence"]["window_start"] < forward["evidence"]["window_end"]
    assert "not water level" in forward["note"].lower() or "Not water level" in forward["note"]


def test_viewing_a_comparison_writes_nothing_and_never_calls_segmentation(fx: Fixture) -> None:
    before = tree_fingerprint(fx.site_dir)
    early, late = refs(fx)
    go(fx, early, late)
    go(fx, late, early, framing_confirmed=False)
    compare.overlay_png(fx.sites_dir, fx.folder_name, early, late)
    compare.candidates(fx.sites_dir, fx.folder_name, fx.run_id)
    assert tree_fingerprint(fx.site_dir) == before
    assert not (fx.site_dir / "outputs" / "water-change-pairs").exists()


def test_saving_is_explicit_versioned_and_never_overwrites(fx: Fixture) -> None:
    early, late = refs(fx)
    first = go(fx, early, late, save=True)
    assert first["saved"]["reused"] is False and Path(first["saved"]["path"]).is_file()
    again = go(fx, late, early, save=True)  # chosen the other way round: the same pair
    assert again["saved"]["reused"] is True
    assert again["saved"]["pair_key"] == first["saved"]["pair_key"]
    saved = json.loads(Path(first["saved"]["path"]).read_text())
    assert saved["earlier"]["image_sha256"] and saved["earlier"]["mask_sha256s"]
    assert saved["calculation_version"].startswith("water_change_mask_v1")


def test_without_a_framing_confirmation_the_numbers_are_unavailable_with_the_reason(
    fx: Fixture,
) -> None:
    early, late = refs(fx)
    result = go(fx, early, late, framing_confirmed=False)
    assert result["available"] is False and result["evidence"]["value"] is None
    assert "FRAMING_NOT_CONFIRMED" in result["evidence"]["reason_codes"]


@pytest.mark.parametrize(
    ("review", "code"),
    [
        (None, "LATER_MASK_UNREVIEWED"),
        ("rejected", "LATER_MASK_REJECTED"),
        ("needs_correction", "LATER_MASK_NEEDS_CORRECTION"),
    ],
)
def test_unaccepted_masks_leave_the_images_viewable_but_the_numbers_unavailable(
    tmp_path: Path, review: str | None, code: str
) -> None:
    fixture = two_image_run(tmp_path)
    write_summary(fixture)
    add_water_mask(fixture, 0, water(10), run_id=RUN_A)
    add_water_mask(fixture, 1, water(18), review=review, run_id=RUN_B)
    early, late = refs(fixture)
    result = go(fixture, early, late)
    assert result["available"] is False and code in result["evidence"]["reason_codes"]
    with pytest.raises(compare.CompareUnavailable, match="accepted water mask"):
        compare.overlay_png(fixture.sites_dir, fixture.folder_name, early, late)


def test_a_missing_mask_is_unavailable(tmp_path: Path) -> None:
    fixture = two_image_run(tmp_path)
    write_summary(fixture)
    add_water_mask(fixture, 0, water(10), run_id=RUN_A)
    early, late = refs(fixture)
    assert "LATER_MASK_MISSING" in go(fixture, early, late)["evidence"]["reason_codes"]


def test_a_different_watched_area_means_the_camera_view_is_not_comparable(tmp_path: Path) -> None:
    fixture = two_image_run(tmp_path)
    write_summary(fixture)
    add_water_mask(fixture, 0, water(10), run_id=RUN_A)
    moved = {"crop_px": [4, 4, 23, 15], "source_size": [32, 24]}
    add_water_mask(fixture, 1, water(18), run_id=RUN_B, transform=moved)
    early, late = refs(fixture)
    result = go(fixture, early, late)
    assert result["evidence"]["status"] == "invalid"
    assert "LATER_MASK_WATCHED_AREA_DIFFERS_FROM_RUN" in result["evidence"]["reason_codes"]
    with pytest.raises(compare.CompareUnavailable, match="accepted water mask"):
        compare.overlay_png(fixture.sites_dir, fixture.folder_name, early, late)


def test_two_images_with_the_same_capture_time_have_no_direction(fx: Fixture) -> None:
    early, _ = refs(fx)
    result = go(fx, early, early)
    assert "TIMESTAMPS_EQUAL" in result["evidence"]["reason_codes"]
    assert result["evidence"]["value"] is None


def test_the_overlay_is_a_png_of_the_same_size_as_the_image(fx: Fixture) -> None:
    import cv2
    import numpy as np

    early, late = refs(fx)
    body = compare.overlay_png(fx.sites_dir, fx.folder_name, early, late)
    assert body.startswith(b"\x89PNG")
    decoded = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape[:2] == (24, 32)
    x0, y0, _, _ = CROP
    assert tuple(decoded[y0, x0]) == (0, 255, 255)  # the watched area is outlined


def test_candidates_cover_every_sequence_of_the_camera_and_keep_duplicate_names_apart(
    tmp_path: Path,
) -> None:
    first = two_image_run(tmp_path, run_id="20261001T100000Z-aaaaaaaa")
    second = two_image_run(tmp_path, run_id=SECOND_RUN)  # same camera, same file names
    other_camera = two_image_run(tmp_path, camera="CAM_B", run_id="20261001T130000Z-eeeeeeee")
    for fixture in (first, second, other_camera):
        write_summary(fixture)
    add_water_mask(first, 0, water(10), run_id=RUN_A)
    add_water_mask(second, 0, water(12), review="rejected", run_id=RUN_B)

    listing = compare.candidates(first.sites_dir, first.folder_name, first.run_id)

    assert listing["camera_id"] == "CAM_A"  # taken from the run's own images
    rows = listing["images"]
    assert {r["sequence_id"] for r in rows} == {first.sequence_id, second.sequence_id}
    assert len(rows) == 4 and first.filenames[0] == second.filenames[0]
    keys = {(r["sequence_id"], r["filename"]) for r in rows}
    assert len(keys) == 4  # the same file name in two sequences stays two different images
    by = {(r["sequence_id"], r["filename"]): r for r in rows}
    assert by[(first.sequence_id, first.filenames[0])]["mask_state"] == "accepted"
    assert by[(second.sequence_id, second.filenames[0])]["mask_state"] == "rejected"
    assert by[(first.sequence_id, first.filenames[1])]["mask_state"] == "none"
    assert by[(first.sequence_id, first.filenames[0])]["run_id"] == first.run_id
    assert by[(second.sequence_id, second.filenames[0])]["run_id"] == second.run_id
    assert [r["captured_at_utc"] for r in rows] == sorted(r["captured_at_utc"] for r in rows)


def test_a_pair_across_two_sequences_is_measured_with_each_images_own_run(
    tmp_path: Path,
) -> None:
    first = two_image_run(tmp_path, run_id="20261001T100000Z-aaaaaaaa")
    second = two_image_run(tmp_path, run_id=SECOND_RUN)
    for fixture in (first, second):
        write_summary(fixture)
    add_water_mask(first, 0, water(10), run_id=RUN_A)
    add_water_mask(second, 1, water(18), run_id=RUN_B)
    result = compare.compare_pair(
        first.sites_dir,
        first.folder_name,
        EndpointRef(second.run_id, second.filenames[1]),
        EndpointRef(first.run_id, first.filenames[0]),
        framing_confirmed=True,
    )
    assert result["earlier"]["run_id"] == first.run_id  # the earlier capture, chosen second
    assert result["later"]["run_id"] == second.run_id
    assert result["available"] is True and result["evidence"]["value"] == pytest.approx(40.0)


def test_unknown_sites_and_runs_are_clear_errors(fx: Fixture) -> None:
    early, late = refs(fx)
    with pytest.raises(CurationError):
        compare.compare_pair(fx.sites_dir, "../x", early, late, framing_confirmed=True)
    with pytest.raises(CurationError):
        compare.candidates(fx.sites_dir, fx.folder_name, "20269999T000000Z-00000000")


def test_a_thumbnail_is_a_small_jpeg(fx: Fixture) -> None:
    body = compare.thumbnail(fx.site_dir, fx.sequence_id, fx.filenames[0])
    assert body.startswith(b"\xff\xd8")

"""The per-image water coverage series behind the Review chart: never zero, drafts flagged."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from water_helpers import (
    CROP,
    Fixture,
    Img,
    add_water_mask,
    make_run,
    tree_fingerprint,
    water,
)

from openfloodai.curation.common import CurationError
from openfloodai.water_change import series


def build(tmp_path: Path, days: int = 5) -> Fixture:
    return make_run(tmp_path, [Img(day=d, human=None) for d in range(1, days + 1)], baseline=0)


def run_id(n: int) -> str:
    return f"20261002T10000{n}Z-{n:08x}"


def rows(fx: Fixture) -> dict[str, dict[str, Any]]:
    result = series.run_series(fx.sites_dir, fx.folder_name, fx.run_id)
    return {r["filename"]: r for r in result["images"]}


def test_coverage_is_the_water_share_of_the_watched_area_per_image(tmp_path: Path) -> None:
    fx = build(tmp_path, 3)
    add_water_mask(fx, 0, water(6), run_id=run_id(1))  # 3 of 20 columns x 11 rows = 15%
    add_water_mask(fx, 1, water(10), run_id=run_id(2))  # 35%
    add_water_mask(fx, 2, water(18), run_id=run_id(3))  # 75%
    by = rows(fx)
    assert [by[n]["coverage"] for n in fx.filenames] == [
        pytest.approx(0.15),
        pytest.approx(0.35),
        pytest.approx(0.75),
    ]
    assert {r["basis"] for r in by.values()} == {"accepted"}
    # the series is in capture order, one entry per downloaded image
    ordered = series.run_series(fx.sites_dir, fx.folder_name, fx.run_id)["images"]
    assert [i["filename"] for i in ordered] == fx.filenames


def test_a_reviewer_accepted_mask_is_marked_accepted_and_an_unreviewed_draft_is_flagged(
    tmp_path: Path,
) -> None:
    fx = build(tmp_path, 3)
    add_water_mask(fx, 0, water(6), run_id=run_id(1))
    add_water_mask(fx, 1, water(10), review=None, run_id=run_id(2))  # unreviewed draft
    add_water_mask(fx, 2, water(14), review="rejected", run_id=run_id(3))
    by = rows(fx)
    assert by[fx.filenames[0]]["basis"] == "accepted"
    assert by[fx.filenames[1]]["basis"] == "draft"
    assert by[fx.filenames[1]]["coverage"] == pytest.approx(0.35)
    assert by[fx.filenames[1]]["mask_state"] == "unreviewed"
    assert by[fx.filenames[2]]["coverage"] is None and by[fx.filenames[2]]["basis"] == "none"
    counts = series.run_series(fx.sites_dir, fx.folder_name, fx.run_id)["counts"]
    assert counts == {"images": 3, "with_value": 2, "accepted": 1, "draft": 1}


def test_an_accepted_mask_wins_over_a_draft_of_the_same_image(tmp_path: Path) -> None:
    fx = build(tmp_path, 1)
    add_water_mask(fx, 0, water(14), review=None, run_id=run_id(1))
    add_water_mask(fx, 0, water(6), run_id=run_id(2))
    entry = rows(fx)[fx.filenames[0]]
    assert entry["basis"] == "accepted" and entry["coverage"] == pytest.approx(0.15)


def test_only_water_masks_that_found_something_and_were_not_rejected_are_used(
    tmp_path: Path,
) -> None:
    fx = build(tmp_path, 4)
    add_water_mask(fx, 0, water(6), run_id=run_id(1), prompt="riverbank")
    add_water_mask(fx, 1, water(6), run_id=run_id(2), status="no_match", detections=False)
    add_water_mask(fx, 2, water(6), review="needs_correction", run_id=run_id(3))
    by = rows(fx)
    for name in fx.filenames:
        assert by[name]["coverage"] is None and by[name]["basis"] == "none"
    assert by[fx.filenames[1]]["mask_state"] == "no_match"
    assert by[fx.filenames[2]]["mask_state"] == "needs_correction"


def test_without_masks_nothing_is_invented(tmp_path: Path) -> None:
    fx = build(tmp_path, 3)
    result = series.run_series(fx.sites_dir, fx.folder_name, fx.run_id)
    assert result["watched_area"] is None
    assert result["counts"] == {"images": 3, "with_value": 0, "accepted": 0, "draft": 0}
    for image in result["images"]:
        assert image["coverage"] is None and image["reason"] == "no_usable_water_mask"


def test_the_runs_frozen_watched_area_is_reported_and_a_different_one_is_excluded(
    tmp_path: Path,
) -> None:
    fx = build(tmp_path, 3)
    add_water_mask(fx, 0, water(6), run_id=run_id(1))
    add_water_mask(fx, 1, water(8), run_id=run_id(2))
    moved = {"crop_px": [4, 4, 23, 15], "source_size": [32, 24]}
    add_water_mask(fx, 2, water(10), run_id=run_id(3), transform=moved)
    result = series.run_series(fx.sites_dir, fx.folder_name, fx.run_id)
    assert result["watched_area"]["crop_px"] == CROP
    odd = {i["filename"]: i for i in result["images"]}[fx.filenames[2]]
    assert odd["coverage"] is None and odd["reason"] == "mask_watched_area_differs_from_run"
    assert "draft" in result["note"].lower() and "not water depth" in result["note"]


def test_masks_are_matched_by_the_runs_frozen_image_checksum(tmp_path: Path) -> None:
    fx = build(tmp_path, 1)
    add_water_mask(fx, 0, water(6), run_id=run_id(1))
    image = fx.site_dir / "inputs" / "image-sequences" / fx.sequence_id / "images" / fx.filenames[0]
    image.write_bytes(image.read_bytes() + b"x")
    assert rows(fx)[fx.filenames[0]]["coverage"] == pytest.approx(0.15)


def test_reading_the_series_writes_nothing_and_unknown_runs_are_errors(tmp_path: Path) -> None:
    fx = build(tmp_path, 2)
    add_water_mask(fx, 0, water(6), run_id=run_id(1))
    before = tree_fingerprint(fx.site_dir)
    series.run_series(fx.sites_dir, fx.folder_name, fx.run_id)
    assert tree_fingerprint(fx.site_dir) == before
    with pytest.raises(CurationError):
        series.run_series(fx.sites_dir, fx.folder_name, "20269999T000000Z-00000000")
    with pytest.raises(CurationError):
        series.run_series(fx.sites_dir, "../x", fx.run_id)


def test_masks_that_all_share_a_stale_region_are_not_trusted_just_for_agreeing(
    tmp_path: Path,
) -> None:
    # The old rule took the most common crop among the masks as "the" watched area, so a whole set
    # cut from a smaller, stale region passed. Now each mask is checked against the run's own area.
    fx = build(tmp_path, 3)
    stale = {"crop_px": [4, 4, 12, 10], "source_size": [32, 24]}
    for index in range(3):
        add_water_mask(
            fx, index, water(8, x0=4, y0=4, y1=10), run_id=run_id(index + 1), transform=stale
        )
    result = series.run_series(fx.sites_dir, fx.folder_name, fx.run_id)
    assert result["watched_area"] is None
    assert result["counts"]["with_value"] == 0
    for image in result["images"]:
        assert image["coverage"] is None and image["basis"] == "none"
        assert image["reason"] == "mask_watched_area_differs_from_run"


def test_a_run_with_no_recorded_watched_area_gives_no_coverage(tmp_path: Path) -> None:
    fx = build(tmp_path, 2)
    add_water_mask(fx, 0, water(6), run_id=run_id(1))
    path = fx.site_dir / "outputs" / "image-sequence-runs" / fx.run_id / "inputs-used"
    config = path / "site-config.snapshot.json"
    config.write_text('{"normal_waterline_guides": []}', encoding="utf-8")
    first = rows(fx)[fx.filenames[0]]
    assert first["coverage"] is None and first["reason"] == "run_watched_area_not_recorded"

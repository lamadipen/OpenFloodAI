from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from openfloodai.config import NormalWaterlineGuide, ReferenceRegion, WaterlinePoint
from openfloodai.review import (
    ReviewImageError,
    encode_png,
    generate_biggest_change_review_images,
    render_pair_comparison_overlay,
)

REFERENCE_REGION = {"x": 0, "y": 50, "width": 100, "height": 50}
NORMAL_WATERLINE_GUIDES = [
    {
        "status": "confirmed",
        "normal_condition": True,
        "points": [{"x": 60, "y": 60}, {"x": 80, "y": 80}],
    }
]


def load_image(path: str) -> np.ndarray:
    image = cv2.imread(path)
    assert image is not None
    return image


def test_generates_before_after_and_comparison_images_from_synthetic_frames(
    tmp_path: Path,
) -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    small_change_frame = np.full((10, 10), 30, dtype=np.uint8)
    biggest_change_frame = np.full((10, 10), 200, dtype=np.uint8)

    result = generate_biggest_change_review_images(
        [baseline_frame, small_change_frame, biggest_change_frame],
        tmp_path,
        prefix="demo",
    )

    assert result.baseline_frame_index == 0
    assert result.changed_frame_index == 2
    assert result.change_score > 0.7
    assert result.reference_region_used is False
    assert result.overlay_image_paths == ()
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "demo-baseline.png",
        "demo-changed.png",
        "demo-comparison.png",
    ]
    assert load_image(result.baseline_image_path).shape == (10, 10, 3)
    assert load_image(result.changed_image_path).shape == (10, 10, 3)
    assert load_image(result.comparison_image_path).shape == (10, 20, 3)


def test_saves_reference_region_overlay_images_when_region_is_provided(
    tmp_path: Path,
) -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    changed_frame = np.full((10, 10), 180, dtype=np.uint8)
    reference_region = {
        "x": 0,
        "y": 50,
        "width": 100,
        "height": 50,
    }

    result = generate_biggest_change_review_images(
        [baseline_frame, changed_frame],
        tmp_path,
        reference_region=reference_region,
    )

    baseline_image = load_image(result.baseline_image_path)
    baseline_overlay_image = load_image(result.overlay_image_paths[0])
    comparison_overlay_image = load_image(result.overlay_image_paths[2])

    assert result.reference_region_used is True
    assert len(result.overlay_image_paths) == 3
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "review-baseline-overlay.png",
        "review-baseline.png",
        "review-changed-overlay.png",
        "review-changed.png",
        "review-comparison-overlay.png",
        "review-comparison.png",
    ]
    assert baseline_image[5, 0].tolist() == [0, 0, 0]
    assert baseline_overlay_image[5, 0].tolist() == [0, 255, 255]
    assert baseline_overlay_image[9, 9].tolist() == [0, 255, 255]
    assert comparison_overlay_image.shape == (10, 20, 3)


def test_reference_region_overlay_handles_edge_region(tmp_path: Path) -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    changed_frame = np.full((10, 10), 180, dtype=np.uint8)

    result = generate_biggest_change_review_images(
        [baseline_frame, changed_frame],
        tmp_path,
        reference_region={"x": 90, "y": 90, "width": 10, "height": 10},
    )

    overlay_image = load_image(result.overlay_image_paths[0])

    assert overlay_image.shape == (10, 10, 3)
    assert overlay_image[9, 9].tolist() == [0, 255, 255]


def test_normal_waterline_guide_overlay_is_burned_when_truly_confirmed(tmp_path: Path) -> None:
    baseline_frame = np.zeros((100, 100), dtype=np.uint8)
    changed_frame = np.full((100, 100), 180, dtype=np.uint8)

    result = generate_biggest_change_review_images(
        [baseline_frame, changed_frame],
        tmp_path,
        reference_region=REFERENCE_REGION,
        normal_waterline_guides=NORMAL_WATERLINE_GUIDES,
    )

    overlay_image = load_image(result.overlay_image_paths[0])

    assert overlay_image[60, 60].tolist() == [216, 64, 29]
    assert overlay_image[80, 80].tolist() == [216, 64, 29]


def test_normal_waterline_guide_overlay_accepts_dataclass_input(tmp_path: Path) -> None:
    baseline_frame = np.zeros((100, 100), dtype=np.uint8)
    changed_frame = np.full((100, 100), 180, dtype=np.uint8)
    guide = NormalWaterlineGuide(
        id="left_bank_normal_waterline",
        label="left bank normal waterline",
        points=(WaterlinePoint(x=60, y=60), WaterlinePoint(x=80, y=80)),
        video_id="river-002",
        video_time_seconds=3,
        site_id="site-1",
        camera_id="camera-1",
        status="confirmed",
        normal_condition=True,
        notes="",
        confirmed_at="2026-01-01T00:00:00Z",
        invalidated_at=None,
        invalidation_reason=None,
    )

    result = generate_biggest_change_review_images(
        [baseline_frame, changed_frame],
        tmp_path,
        reference_region=REFERENCE_REGION,
        normal_waterline_guides=[guide],
    )

    overlay_image = load_image(result.overlay_image_paths[0])

    assert overlay_image[60, 60].tolist() == [216, 64, 29]
    assert overlay_image[80, 80].tolist() == [216, 64, 29]


@pytest.mark.parametrize(
    "not_confirmed_guide",
    [
        {**NORMAL_WATERLINE_GUIDES[0], "status": "draft"},
        {**NORMAL_WATERLINE_GUIDES[0], "status": "invalid"},
        {**NORMAL_WATERLINE_GUIDES[0], "normal_condition": False},
        {**NORMAL_WATERLINE_GUIDES[0], "normal_condition": None},
    ],
)
def test_not_confirmed_guide_draws_nothing_extra(
    tmp_path: Path, not_confirmed_guide: dict[str, object]
) -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    changed_frame = np.full((10, 10), 180, dtype=np.uint8)

    without = generate_biggest_change_review_images(
        [baseline_frame, changed_frame],
        tmp_path / "without",
        reference_region=REFERENCE_REGION,
    )
    with_guide = generate_biggest_change_review_images(
        [baseline_frame, changed_frame],
        tmp_path / "with",
        reference_region=REFERENCE_REGION,
        normal_waterline_guides=[not_confirmed_guide],
    )

    assert np.array_equal(
        load_image(without.overlay_image_paths[0]),
        load_image(with_guide.overlay_image_paths[0]),
    )
    assert np.array_equal(
        load_image(without.overlay_image_paths[1]),
        load_image(with_guide.overlay_image_paths[1]),
    )


def test_evidence_usability_note_adds_a_taller_caption_band(tmp_path: Path) -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    changed_frame = np.full((10, 10), 180, dtype=np.uint8)

    without_note = generate_biggest_change_review_images(
        [baseline_frame, changed_frame],
        tmp_path / "without",
        reference_region=REFERENCE_REGION,
        normal_waterline_guides=NORMAL_WATERLINE_GUIDES,
        frame_times=(0.0, 10.0),
    )
    with_note = generate_biggest_change_review_images(
        [baseline_frame, changed_frame],
        tmp_path / "with",
        reference_region=REFERENCE_REGION,
        normal_waterline_guides=NORMAL_WATERLINE_GUIDES,
        evidence_usability_note="Reference evidence not usable: camera moved.",
        frame_times=(0.0, 10.0),
    )

    without_overlay = load_image(without_note.overlay_image_paths[0])
    with_overlay = load_image(with_note.overlay_image_paths[0])
    without_plain = load_image(without_note.baseline_image_path)
    with_plain = load_image(with_note.baseline_image_path)

    assert with_overlay.shape[0] > without_overlay.shape[0]
    assert with_plain.shape == without_plain.shape


def test_biggest_change_uses_reference_region_when_provided(tmp_path: Path) -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    outside_region_change_frame = np.zeros((10, 10), dtype=np.uint8)
    inside_region_change_frame = np.zeros((10, 10), dtype=np.uint8)
    outside_region_change_frame[:5, :] = 255
    inside_region_change_frame[5:, :] = 120
    reference_region = {
        "x": 0,
        "y": 50,
        "width": 100,
        "height": 50,
    }

    result = generate_biggest_change_review_images(
        [baseline_frame, outside_region_change_frame, inside_region_change_frame],
        tmp_path,
        reference_region=reference_region,
    )

    assert result.changed_frame_index == 2
    assert result.change_score == pytest.approx(120 / 255)


def test_accepts_config_reference_region_object(tmp_path: Path) -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    changed_frame = np.full((10, 10), 180, dtype=np.uint8)
    reference_region = ReferenceRegion(x=0, y=50, width=100, height=50)

    result = generate_biggest_change_review_images(
        [baseline_frame, changed_frame],
        tmp_path,
        reference_region=reference_region,
    )

    assert result.reference_region_used is True
    assert len(result.overlay_image_paths) == 3


def test_requires_at_least_two_frames(tmp_path: Path) -> None:
    frame = np.zeros((10, 10), dtype=np.uint8)

    with pytest.raises(ReviewImageError, match="At least two frames"):
        generate_biggest_change_review_images([frame], tmp_path)


def test_mismatched_frame_shapes_fail_clearly(tmp_path: Path) -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    changed_frame = np.zeros((12, 10), dtype=np.uint8)

    with pytest.raises(ReviewImageError, match="same shape"):
        generate_biggest_change_review_images([baseline_frame, changed_frame], tmp_path)


def test_invalid_reference_region_fails_clearly(tmp_path: Path) -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    changed_frame = np.full((10, 10), 180, dtype=np.uint8)
    reference_region = {
        "x": 80,
        "y": 0,
        "width": 30,
        "height": 50,
    }

    with pytest.raises(ReviewImageError, match="0-100 image area"):
        generate_biggest_change_review_images(
            [baseline_frame, changed_frame],
            tmp_path,
            reference_region=reference_region,
        )


def test_output_path_must_be_directory(tmp_path: Path) -> None:
    output_path = tmp_path / "not-a-folder"
    output_path.write_text("not a directory", encoding="utf-8")
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    changed_frame = np.full((10, 10), 180, dtype=np.uint8)

    with pytest.raises(ReviewImageError, match="not a directory"):
        generate_biggest_change_review_images([baseline_frame, changed_frame], output_path)


def test_render_pair_comparison_overlay_stitches_two_arbitrary_frames() -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    other_frame = np.full((10, 10), 200, dtype=np.uint8)

    overlay = render_pair_comparison_overlay(baseline_frame, other_frame)

    assert overlay.shape == (10, 20, 3)


def test_render_pair_comparison_overlay_draws_the_watched_area_on_both_sides() -> None:
    baseline_frame = np.zeros((20, 20), dtype=np.uint8)
    other_frame = np.full((20, 20), 200, dtype=np.uint8)

    plain = render_pair_comparison_overlay(baseline_frame, other_frame)
    boxed = render_pair_comparison_overlay(
        baseline_frame, other_frame, reference_region=REFERENCE_REGION
    )

    assert not np.array_equal(plain, boxed), "a reference region must change the rendered pixels"


def test_render_pair_comparison_overlay_rejects_mismatched_heights() -> None:
    baseline_frame = np.zeros((10, 10), dtype=np.uint8)
    other_frame = np.zeros((20, 10), dtype=np.uint8)

    with pytest.raises(ReviewImageError, match="matching height"):
        render_pair_comparison_overlay(baseline_frame, other_frame)


def test_encode_png_round_trips_through_cv2() -> None:
    frame = np.full((10, 10, 3), 128, dtype=np.uint8)

    body = encode_png(frame)

    assert isinstance(body, bytes)
    assert body[:8] == b"\x89PNG\r\n\x1a\n"

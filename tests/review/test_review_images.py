from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from openfloodai.config import ReferenceRegion
from openfloodai.review import ReviewImageError, generate_biggest_change_review_images


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
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "demo-baseline.png",
        "demo-changed.png",
        "demo-comparison.png",
    ]
    assert load_image(result.baseline_image_path).shape == (10, 10, 3)
    assert load_image(result.changed_image_path).shape == (10, 10, 3)
    assert load_image(result.comparison_image_path).shape == (10, 20, 3)


def test_draws_reference_region_box_when_region_is_provided(tmp_path: Path) -> None:
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

    assert result.reference_region_used is True
    assert baseline_image[5, 0].tolist() == [0, 255, 0]
    assert baseline_image[9, 9].tolist() == [0, 255, 0]


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

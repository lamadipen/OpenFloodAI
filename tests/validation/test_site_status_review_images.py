"""Regression test: image-sequence-run review images must never leak into the video flow.

Issue #182 adds a second, unrelated kind of run under a site's outputs/ folder
(outputs/image-sequence-runs/<run_id>/review-images/). site_status.py's
_find_review_images_paths used to glob for any directory named
"review-images" anywhere under outputs/, which would have picked these up
and could have fed them into the video flow's review_images_path / report
history. This test proves that never happens.
"""

from __future__ import annotations

import time
from pathlib import Path

from openfloodai.validation.site_status import read_validation_site_status


def test_image_sequence_run_review_images_are_never_used_as_the_site_review_images_path(
    tmp_path: Path,
) -> None:
    site_dir = tmp_path / "site"

    video_review_images = site_dir / "outputs" / "runs" / "video-run-1" / "review-images"
    video_review_images.mkdir(parents=True)
    (video_review_images / "review-baseline.png").write_bytes(b"fake png")

    # Written after the video run's folder, so a naive "most recently
    # modified" pick would prefer this one if it were considered at all.
    time.sleep(0.01)
    image_sequence_review_images = (
        site_dir / "outputs" / "image-sequence-runs" / "img-run-1" / "review-images"
    )
    image_sequence_review_images.mkdir(parents=True)
    (image_sequence_review_images / "image-sequence-baseline.png").write_bytes(b"fake png")

    status = read_validation_site_status(site_dir)

    assert status.review_images_path == str(video_review_images)


def test_review_images_path_is_none_when_only_an_image_sequence_run_exists(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    image_sequence_review_images = (
        site_dir / "outputs" / "image-sequence-runs" / "img-run-1" / "review-images"
    )
    image_sequence_review_images.mkdir(parents=True)
    (image_sequence_review_images / "image-sequence-baseline.png").write_bytes(b"fake png")

    status = read_validation_site_status(site_dir)

    assert status.review_images_path is None

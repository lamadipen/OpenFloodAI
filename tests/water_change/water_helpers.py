"""Shared builders for the water-change tests: a saved run with accepted full-size water masks."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "curation"))

from curation_fixtures import Fixture, Img, add_mask_result, make_run  # noqa: E402

# Fixture images are 32 x 24; the watched area (10%, 20%, 60% x 40%) crops to [3, 4, 23, 15].
WIDTH, HEIGHT = 32, 24
CROP = [3, 4, 23, 15]
TRANSFORM = {"crop_px": CROP, "source_size": [WIDTH, HEIGHT]}


def water(x1: int, *, y0: int = 4, y1: int = 15, x0: int = 3) -> np.ndarray:
    """A rectangle of water inside the watched area, in full-image coordinates."""

    out = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    out[y0:y1, x0:x1] = 255
    return out


def two_image_run(
    root: Path, *, folder: str = "site-a", camera: str = "CAM_A", run_id: str | None = None
) -> Fixture:
    return make_run(
        root,
        [Img(day=1, human=None), Img(day=2, human=None)],
        folder=folder,
        camera=camera,
        run_id=run_id or "20261001T100000Z-aaaaaaaa",
    )


def add_water_mask(
    fixture: Fixture,
    index: int,
    mask: np.ndarray,
    *,
    review: str | None = "accepted",
    run_id: str,
    transform: dict[str, Any] | None = None,
    **kwargs: object,
) -> str:
    return add_mask_result(
        fixture,
        fixture.filenames[index],
        review=review,
        run_id=run_id,
        mask=mask,
        transform=transform or TRANSFORM,
        prompt=str(kwargs.pop("prompt", "river water")),
        **kwargs,  # type: ignore[arg-type]
    )


def tree_fingerprint(root: Path) -> dict[str, str]:
    """Every file under a folder with its hash, to prove nothing was edited."""

    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


__all__ = [
    "CROP",
    "TRANSFORM",
    "Fixture",
    "add_water_mask",
    "tree_fingerprint",
    "two_image_run",
    "water",
]

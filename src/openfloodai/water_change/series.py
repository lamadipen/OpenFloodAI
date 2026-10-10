"""Water coverage of every image in one saved run, for the Review chart.

For each downloaded image of a run this reads the water mask that segmentation produced for those
exact image bytes and reports the share of the watched area that is water. The mask is the
reviewer-ACCEPTED one when there is one; otherwise the newest unreviewed hosted-SAM draft is used
and flagged as a draft so the chart can draw it differently. Rejected, needs-correction, riverbank
and no-match results are never used, and an image with no usable mask has no value (never zero).

It only reads. Nothing is segmented, uploaded or written. The view assumes one fixed camera: it
checks that every mask shares one image size and watched area, but it cannot detect a camera that
moved, so it is a screening chart. The Compare screen is where a pair gets a person-confirmed
measurement.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from openfloodai.contracts import read_jsonl_records
from openfloodai.curation.common import CurationError
from openfloodai.curation.snapshot import MaskCandidate, mask_candidates_from_results
from openfloodai.curation.tasks import WATER_MASK_PROMPTS, select_water_mask
from openfloodai.validation import hosted_sam_runner
from openfloodai.vision.water_change import WaterChangeInputError, roi_from_crop, water_fraction
from openfloodai.water_change.compare import _run_summary, _site_dir
from openfloodai.water_change.identity import frozen_image_shas
from openfloodai.water_change.region import expected_crop_px

_STATE_RANK = {"accepted": 0, "needs_correction": 1, "unreviewed": 2, "rejected": 3}
SERIES_NOTE = (
    "Water coverage is the share of the watched area that the segmentation marks as water in "
    "each image. Filled points use a mask a reviewer accepted; hollow points use an unreviewed "
    "draft. It measures the picture, not water depth or flow, and it cannot detect a moved "
    "camera. Images with no usable mask have no value."
)


def _mask_state(candidates: list[MaskCandidate]) -> str:
    states = [
        "no_match" if c.status == "no_match" else c.review_status
        for c in candidates
        if c.prompt in WATER_MASK_PROMPTS and c.status in {"completed", "no_match"}
    ]
    if not states:
        return "none"
    return min(states, key=lambda s: _STATE_RANK.get(s, 4))


def _union(paths: tuple[Path, ...]) -> np.ndarray | None:
    union: np.ndarray | None = None
    for path in paths:
        raster = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if raster is None:
            return None
        wet = raster > 0
        if union is None:
            union = wet
        elif union.shape != wet.shape:
            return None
        else:
            union = union | wet
    return union


def _pick_mask(candidates: list[MaskCandidate]) -> tuple[MaskCandidate | None, str]:
    """The mask to measure and whether it is `accepted` or an unreviewed `draft`."""

    chosen, _ = select_water_mask(candidates)
    if chosen is not None:
        return chosen, "accepted"
    drafts = [
        c
        for c in candidates  # newest first
        if c.prompt in WATER_MASK_PROMPTS
        and c.status == "completed"
        and c.review_status == "unreviewed"
    ]
    return (drafts[0], "draft") if drafts else (None, "none")


def _frozen_region(run_dir: Path) -> Any:
    """The watched area this run was made with, as recorded when the run started."""

    try:
        snapshot = json.loads(
            (run_dir / "inputs-used" / "site-config.snapshot.json").read_text("utf-8")
        )
    except (OSError, ValueError):
        return None
    return snapshot.get("reference_region") if isinstance(snapshot, dict) else None


def run_series(sites_dir: Path, folder: str, run_id: str) -> dict[str, Any]:
    """Water coverage for every downloaded image of the run, in capture order."""

    site_dir = _site_dir(sites_dir, folder)
    summary = _run_summary(site_dir, run_id)
    run_dir = site_dir / "outputs" / "image-sequence-runs" / run_id
    sequence_id = str(summary.get("sequence_id", ""))
    try:
        records = [
            dict(r)
            for r in read_jsonl_records(run_dir / "image-sequence-records.jsonl")
            if r.get("download_status") == "downloaded" and r.get("filename")
        ]
    except (OSError, ValueError) as error:
        raise CurationError("Run not found.") from error
    records.sort(key=lambda r: (str(r.get("captured_at_utc", "")), str(r["filename"])))
    shas = frozen_image_shas(run_dir)
    region = _frozen_region(run_dir)
    results = hosted_sam_runner.list_sam_results(site_dir, sequence_id) if sequence_id else []

    rows: list[dict[str, Any]] = []
    for record in records:
        filename = str(record["filename"])
        sha = shas.get(filename, "")
        candidates = mask_candidates_from_results(site_dir, results, filename, sha) if sha else []
        chosen, basis = _pick_mask(candidates)
        row: dict[str, Any] = {
            "filename": filename,
            "captured_at_utc": record.get("captured_at_utc"),
            "mask_state": _mask_state(candidates),
            "basis": basis,
            "coverage": None,
            "reason": "no_usable_water_mask" if chosen is None else None,
        }
        if chosen is not None:
            transform = chosen.record.get("transform") or {}
            size = transform.get("source_size")
            union = _union(chosen.mask_paths)
            if union is None or not isinstance(size, list) or len(size) != 2:
                row["reason"] = "mask_unreadable"
            else:
                frame = (int(size[0]), int(size[1]))
                expected = expected_crop_px(region, frame)
                if expected is None:
                    row["reason"] = "run_watched_area_not_recorded"
                elif list(transform.get("crop_px") or ()) != expected:
                    # cut from another watched area than this run's frozen one: never measured
                    row["reason"] = "mask_watched_area_differs_from_run"
                else:
                    row["_frame"] = (frame, tuple(expected))
                    row["_mask"], row["_size"], row["_crop"] = union, frame, expected
        rows.append(row)

    # Every mask now matches the run's frozen watched area. One image size for the whole chart: the
    # most common among them.
    common = Counter(r["_frame"] for r in rows if "_frame" in r).most_common(1)
    reference = common[0][0] if common else None
    for row in rows:
        if "_frame" not in row:
            continue
        if row["_frame"] != reference:
            row["reason"] = "different_image_size"
            continue
        try:
            roi = roi_from_crop(row["_crop"], row["_size"])
            row["coverage"] = water_fraction(row["_mask"], roi, row["_size"])
        except (WaterChangeInputError, ValueError) as error:
            row["reason"] = getattr(error, "code", "invalid_mask").lower()

    images = [
        {k: v for k, v in row.items() if not k.startswith("_")}
        | {"basis": row["basis"] if row["coverage"] is not None else "none"}
        for row in rows
    ]
    return {
        "run_id": run_id,
        "sequence_id": sequence_id,
        "watched_area": (
            {"image_size": list(reference[0]), "crop_px": list(reference[1])} if reference else None
        ),
        "images": images,
        "counts": {
            "images": len(images),
            "with_value": sum(1 for i in images if i["coverage"] is not None),
            "accepted": sum(1 for i in images if i["basis"] == "accepted"),
            "draft": sum(1 for i in images if i["basis"] == "draft"),
        },
        "note": SERIES_NOTE,
    }

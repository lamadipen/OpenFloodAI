"""Compare any two saved images of one camera, with a mask-based water-coverage change (#223).

This is the read-only backend of the Compare action in Review. It lists the saved images of the
same camera across sequences and runs, measures a chosen pair with the shared #222 measurement,
draws the spatial change, and, only when asked, keeps the result.

Nothing here segments an image, uploads anything, edits a label, a baseline, a dataset or a saved
run, or reads a pixel-appearance score. A pair is ordered by capture time whatever order it was
chosen in. Framing is confirmed by the person at the screen; the same camera name alone is not
treated as proof the view did not move.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import cv2

from openfloodai.curation.common import CurationError
from openfloodai.curation.snapshot import load_observation
from openfloodai.curation.tasks import WATER_MASK_PROMPTS
from openfloodai.ingestion.river_images import (
    RiverImageError,
    list_site_image_sequences,
    resolve_sequence_image,
)
from openfloodai.validation import hosted_sam_runner
from openfloodai.validation.image_sequence_runner import list_image_sequence_runs
from openfloodai.vision.water_change import change_overlay, roi_from_crop
from openfloodai.water_change.pair import EndpointRef, measure_pair, resolve_endpoint

FRAMING_CONFIRMED_BY = "reviewer (confirmed at the Compare screen)"
THUMBNAIL_WIDTH = 168
_RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
_MASK_RANK = {"accepted": 0, "needs_correction": 1, "unreviewed": 2, "rejected": 3}


class CompareUnavailable(ValueError):
    """The change picture cannot be drawn for this pair; the message says why."""


def _site_dir(sites_dir: Path, folder: str) -> Path:
    site_dir = (sites_dir / folder).resolve()
    if not folder or site_dir.parent != sites_dir.resolve() or not site_dir.is_dir():
        raise CurationError("Site not found.")
    return site_dir


def _run_summary(site_dir: Path, run_id: str) -> dict[str, Any]:
    if not _RUN_ID.fullmatch(run_id or ""):
        raise CurationError("Run not found.")
    path = site_dir / "outputs" / "image-sequence-runs" / run_id / "run-summary.json"
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CurationError("Run not found.") from error
    if not isinstance(summary, dict):
        raise CurationError("Run not found.")
    return summary


def _mask_states(site_dir: Path, sequence_id: str) -> dict[str, str]:
    """The best human-review state of any water mask saved for each file name of a sequence."""

    best: dict[str, str] = {}
    for result in hosted_sam_runner.list_sam_results(site_dir, sequence_id):
        name = str(result.get("filename", ""))
        if result.get("prompt") not in WATER_MASK_PROMPTS:
            continue
        if result.get("status") == "no_match":
            state = "no_match"
        elif result.get("status") != "completed":
            continue
        else:
            state = str(result.get("review_status", "unreviewed"))
        rank = _MASK_RANK.get(state, 4)
        if name not in best or rank < _MASK_RANK.get(best[name], 4):
            best[name] = state
    return best


def candidates(sites_dir: Path, folder: str, run_id: str) -> dict[str, Any]:
    """Every saved image of this run's camera, across sequences, with how to measure each.

    An image can be measured when its sequence has a saved validation run; the newest run of
    that sequence is used. Images are identified by sequence AND file name (file names repeat
    across sequences) plus the run that supplies their frozen inputs.
    """

    site_dir = _site_dir(sites_dir, folder)
    current = _run_summary(site_dir, run_id)
    camera = str(current.get("camera_id") or "")
    images: list[dict[str, Any]] = []
    sequences: list[dict[str, Any]] = []
    saved = list_site_image_sequences(site_dir)
    if not camera:  # older run summaries: take the camera of the run's own images
        camera = next(
            (
                str(r.get("camera_id"))
                for s in saved
                if s.get("sequence_id") == current.get("sequence_id")
                for r in s.get("records", [])
                if isinstance(r, dict) and r.get("camera_id")
            ),
            "",
        )
    for sequence in saved:
        sequence_id = str(sequence.get("sequence_id", ""))
        runs = list_image_sequence_runs(site_dir, sequence_id)
        measure_run = (
            run_id
            if sequence_id == current.get("sequence_id")
            else (runs[0]["run_id"] if runs else None)
        )
        states = _mask_states(site_dir, sequence_id)
        count = 0
        for record in sequence.get("records", []):
            if (
                not isinstance(record, dict)
                or record.get("download_status") != "downloaded"
                or str(record.get("camera_id") or "") != camera
            ):
                continue
            name = str(record.get("filename", ""))
            count += 1
            images.append(
                {
                    "sequence_id": sequence_id,
                    "filename": name,
                    "captured_at_utc": record.get("captured_at_utc"),
                    "local_time": record.get("local_time"),
                    "run_id": measure_run,
                    "mask_state": states.get(name, "none"),
                }
            )
        if count:
            sequences.append(
                {
                    "sequence_id": sequence_id,
                    "label": sequence.get("label") or sequence_id,
                    "image_count": count,
                    "run_id": measure_run,
                }
            )
    images.sort(key=lambda i: (str(i["captured_at_utc"]), i["sequence_id"], i["filename"]))
    return {
        "camera_id": camera,
        "current": {"run_id": run_id, "sequence_id": current.get("sequence_id")},
        "sequences": sequences,
        "images": images,
        "note": (
            "Same camera name does not prove the view did not move. Measuring needs a saved "
            "run and accepted water masks for both images; nothing is segmented here."
        ),
    }


def thumbnail(site_dir: Path, sequence_id: str, filename: str) -> bytes:
    path = resolve_sequence_image(site_dir, sequence_id, filename)
    image = cv2.imread(str(path))
    if image is None:
        raise RiverImageError("Image not found.")
    scale = THUMBNAIL_WIDTH / image.shape[1]
    small = cv2.resize(image, (THUMBNAIL_WIDTH, max(1, round(image.shape[0] * scale))))
    ok, encoded = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    if not ok:
        raise RiverImageError("Image not found.")
    return bytes(encoded)


def _captured(site_dir: Path, ref: EndpointRef) -> str:
    try:
        return str(
            load_observation(site_dir, ref.run_id, ref.filename).snapshot["source"][
                "captured_at_utc"
            ]
        )
    except (CurationError, OSError, ValueError, KeyError):
        return ""


def order_pair(site_dir: Path, a: EndpointRef, b: EndpointRef) -> tuple[EndpointRef, EndpointRef]:
    """Earlier first, whatever order they were chosen in; unreadable times keep the given order."""

    first, second = _captured(site_dir, a), _captured(site_dir, b)
    if first and second and second < first:
        return b, a
    return a, b


def compare_pair(
    sites_dir: Path,
    folder: str,
    a: EndpointRef,
    b: EndpointRef,
    *,
    framing_confirmed: bool,
    save: bool = False,
) -> dict[str, Any]:
    """Measure the pair for display. Only `save=True` writes, and only a new frozen record."""

    site_dir = _site_dir(sites_dir, folder)
    earlier, later = order_pair(site_dir, a, b)
    result = measure_pair(
        sites_dir,
        folder,
        earlier,
        later,
        framing_confirmed_by=FRAMING_CONFIRMED_BY if framing_confirmed else None,
        freeze=save,
    )
    evidence = result["evidence"]
    measurement = (evidence.get("quality") or {}).get("measurement") or {}
    return {
        "earlier": {
            **_ref_dict(earlier),
            "captured_at_utc": result["earlier"].get("captured_at_utc"),
        },
        "later": {**_ref_dict(later), "captured_at_utc": result["later"].get("captured_at_utc")},
        "elapsed_seconds": measurement.get("elapsed_seconds"),
        "evidence": evidence,
        "provenance": {
            "calculation_version": result["calculation_version"],
            "earlier": result["earlier"],
            "later": result["later"],
        },
        "saved": {
            "pair_key": result["pair_key"],
            "path": result["path"],
            "reused": result["reused"],
        }
        if save
        else None,
        "available": evidence["status"] == "available",
        "framing_confirmed": framing_confirmed,
        "note": (
            "Image-space coverage of the watched area from two accepted masks. Not water level, "
            "depth, flow speed, continuous rise or flood status."
        ),
    }


def _ref_dict(ref: EndpointRef) -> dict[str, str]:
    return {"run_id": ref.run_id, "filename": ref.filename}


def overlay_png(sites_dir: Path, folder: str, earlier: EndpointRef, later: EndpointRef) -> bytes:
    """The later image with water that arrived and water that left coloured. Read-only."""

    site_dir = _site_dir(sites_dir, folder)
    first = resolve_endpoint(site_dir, earlier, "EARLIER")
    second = resolve_endpoint(site_dir, later, "LATER")
    if first.mask is None or second.mask is None:
        raise CompareUnavailable("Both images need an accepted water mask to draw the change.")
    if first.image_size != second.image_size or first.crop_px != second.crop_px:
        raise CompareUnavailable("The two masks do not share one image size and watched area.")
    if second.loaded is None or second.loaded.image_path is None or first.crop_px is None:
        raise CompareUnavailable("The later image is not available.")
    image = cv2.imread(str(second.loaded.image_path))
    if image is None or first.image_size is None:
        raise CompareUnavailable("The later image is not readable.")
    try:
        roi = roi_from_crop(first.crop_px, first.image_size)
    except ValueError as error:
        raise CompareUnavailable(str(error)) from error
    drawn = change_overlay(image, first.mask, second.mask, roi)
    ok, encoded = cv2.imencode(".png", drawn)
    if not ok:
        raise CompareUnavailable("The change picture could not be drawn.")
    return bytes(encoded)

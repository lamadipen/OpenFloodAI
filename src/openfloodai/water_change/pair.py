"""Resolve two saved observations into one frozen water-change measurement (Issue #222).

Reads a saved image-sequence run (its frozen inputs and human review) and the saved hosted
segmentation results; it only ever READS those. The one thing it writes is a new, content-
addressed file under ``outputs/water-change-pairs/``, created exactly once, so a measurement is
reproducible later and no original run, review or mask is touched.

No segmentation is ever started from here. A mask counts only if a person accepted a completed
WATER result for the exact bytes of that image.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt

from openfloodai.curation.common import (
    SEVERITY_ERROR,
    CurationError,
    content_id,
    sha256_file,
    utc_now,
)
from openfloodai.curation.snapshot import (
    LoadedObservation,
    MaskCandidate,
    find_mask_candidates,
    load_observation,
)
from openfloodai.curation.tasks import WATER_MASK_PROMPTS, gauge_reasons, select_water_mask
from openfloodai.evidence.adapters.water_change import (
    PLUGIN_ID,
    PLUGIN_VERSION,
    WaterChangeEndpoint,
    WaterChangeInputs,
    WaterChangeObservationAdapter,
)
from openfloodai.vision.water_change import (
    CALCULATION_VERSION,
    Roi,
    WaterChangeInputError,
    roi_from_crop,
)
from openfloodai.water_change.region import expected_crop_px

PAIR_DIR = "water-change-pairs"
_FOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,200}$")


@dataclass(frozen=True)
class EndpointRef:
    """Which saved image (and optionally which mask) is one end of the pair."""

    run_id: str
    filename: str
    mask_run_id: str | None = None
    mask_result_id: str | None = None


@dataclass
class ResolvedEndpoint:
    ref: EndpointRef
    prefix: str = ""
    loaded: LoadedObservation | None = None
    mask: npt.NDArray[Any] | None = None
    image_size: tuple[int, int] | None = None  # (width, height) of the source image
    crop_px: list[int] | None = None
    reasons: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def captured_at_utc(self) -> str:
        if self.loaded is None:
            return ""
        return str(self.loaded.snapshot["source"]["captured_at_utc"])

    @property
    def snapshot(self) -> dict[str, Any]:
        return self.loaded.snapshot if self.loaded is not None else {}


def _site_dir(sites_dir: Path, folder: str) -> Path:
    if not _FOLDER.fullmatch(folder) or folder in {".", ".."}:
        raise CurationError("Choose a valid site folder.")
    site_dir = sites_dir / folder
    if not site_dir.is_dir():
        raise CurationError("Site folder not found.")
    return site_dir


def _union_mask(paths: tuple[Path, ...]) -> tuple[npt.NDArray[Any] | None, str | None]:
    union: npt.NDArray[Any] | None = None
    for path in paths:
        raster = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if raster is None:
            return None, "MASK_UNREADABLE"
        wet = raster > 0
        if union is None:
            union = wet
        elif union.shape != wet.shape:
            return None, "MASK_DETECTIONS_DIFFER_IN_SIZE"
        else:
            union = union | wet
    return union, None if union is not None else "MASK_HAS_NO_DETECTION"


def _gauge_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    gauge = snapshot.get("gauge") or {}
    reading = gauge.get("reading") if isinstance(gauge.get("reading"), dict) else None
    problems = [r["code"].upper() for r in gauge_reasons(snapshot) if r["severity"] == "error"]
    return {
        "match_status": gauge.get("match_status"),
        "value": reading.get("value") if reading else None,
        "unit": reading.get("unit") if reading else None,
        "datetime_utc": reading.get("datetime_utc") if reading else None,
        "time_difference_seconds": gauge.get("time_difference_seconds"),
        "station": gauge.get("station"),
        "station_nwis_id": (gauge.get("station") or {}).get("nwis_site_id"),
        "parameter_code": reading.get("parameter_code") if reading else None,
        "parameter_label": reading.get("parameter_label") if reading else None,
        "used_fallback_discharge": reading.get("used_fallback_discharge") if reading else None,
        "usable": reading is not None and not problems,
        "problems": problems,
        "note": "Instrument context at a possibly nearby station. Not a label and not an input.",
    }


def resolve_endpoint(site_dir: Path, ref: EndpointRef, prefix: str) -> ResolvedEndpoint:
    """Read one end of a pair. Anything that blocks it is recorded as a ``<PREFIX>_<CODE>``."""

    out = ResolvedEndpoint(ref=ref, prefix=prefix)

    def block(code: str) -> None:
        out.reasons.append(f"{prefix}_{code}")

    try:
        loaded = load_observation(site_dir, ref.run_id, ref.filename)
    except (CurationError, OSError, ValueError, KeyError) as error:
        block("IMAGE_NOT_AVAILABLE")
        out.details = {"run_id": ref.run_id, "filename": ref.filename, "error": str(error)[:200]}
        return out
    out.loaded = loaded
    snap = loaded.snapshot
    for problem in loaded.problems:
        if problem["severity"] == SEVERITY_ERROR:
            block(problem["code"].upper())
    review = snap.get("review")
    if review and review.get("visibility", {}).get("camera_stable") == "no":
        block("CAMERA_NOT_STABLE")

    candidates = find_mask_candidates(site_dir, snap)
    chosen, selection = select_water_mask(candidates, ref.mask_result_id, ref.mask_run_id)
    for item in selection:
        block(item["code"].upper())
    if any(
        c.prompt in WATER_MASK_PROMPTS and c.status == "no_match" and c.review_status == "accepted"
        for c in candidates
    ):
        # "No match" means the provider found nothing. It is not a verified empty water mask.
        block("NO_MATCH_NOT_VERIFIED_EMPTY")

    out.details = {
        "run_id": ref.run_id,
        "filename": ref.filename,
        "site_id": snap["site"]["site_id"],
        "camera_id": snap["site"]["camera_id"],
        "captured_at_utc": out.captured_at_utc,
        "image_sha256": snap["image"]["sha256"],
        "config_sha256": snap["configuration"]["config_sha256"],
        "reference_region": snap["configuration"]["reference_region"],
        "dataset_group": snap["dataset_group"],
        "review_state": _review_state(review),
    }
    if chosen is not None:
        _attach_mask(out, chosen)
    return out


def _review_state(review: dict[str, Any] | None) -> dict[str, Any] | None:
    """The human review of this image that can change a result: its revision, when it was made,
    and the camera and visibility answers. Part of the result's identity, so marking the camera as
    moved later makes a new result instead of reusing an old "available" one."""

    if not review:
        return None
    return {
        "label_revision": review.get("label_revision"),
        "reviewed_at_utc": review.get("reviewed_at_utc"),
        "visibility": review.get("visibility") or {},
    }


def _attach_mask(out: ResolvedEndpoint, chosen: MaskCandidate) -> None:
    record = chosen.record
    raw_transform = record.get("transform")
    transform: dict[str, Any] = raw_transform if isinstance(raw_transform, dict) else {}
    out.details.update(
        segmentation_run_id=chosen.run_id,
        result_id=chosen.result_id,
        prompt=chosen.prompt,
        model_requested=record.get("model_requested"),
        processed_at_utc=record.get("processed_at_utc"),
        review_decision=chosen.review_status,
        reviewed_at_utc=record.get("reviewed_at_utc"),
        transform=transform,
    )
    size = transform.get("source_size")
    if (
        isinstance(size, list)
        and len(size) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in size)
    ):
        out.image_size = (int(size[0]), int(size[1]))
    out.crop_px = transform.get("crop_px") if isinstance(transform.get("crop_px"), list) else None
    # The crop the mask was cut with must be the run's own frozen watched area. A mask from a
    # smaller or stale region would otherwise be measured against that wrong region.
    expected = expected_crop_px(out.details.get("reference_region"), out.image_size)
    out.details["mask_crop_px"] = out.crop_px
    out.details["expected_crop_px"] = expected
    if expected is None:
        out.reasons.append(f"{out.prefix}_WATCHED_AREA_NOT_VERIFIABLE")
        out.crop_px = None
        return
    if out.crop_px != expected:
        out.reasons.append(f"{out.prefix}_MASK_WATCHED_AREA_DIFFERS_FROM_RUN")
        out.crop_px = None
        return
    if any(not p.is_file() for p in chosen.mask_paths) or not chosen.mask_paths:
        out.reasons.append(f"{out.prefix}_MASK_FILE_MISSING")
        return
    out.details["mask_sha256s"] = [sha256_file(p) for p in chosen.mask_paths]
    union, problem = _union_mask(chosen.mask_paths)
    if problem:
        out.reasons.append(f"{out.prefix}_{problem}")
        return
    out.mask = np.asarray(union, dtype=np.uint8)
    if out.loaded is not None and out.loaded.image_path is not None:
        decoded = cv2.imread(str(out.loaded.image_path))
        if decoded is not None and out.image_size != (decoded.shape[1], decoded.shape[0]):
            out.reasons.append(f"{out.prefix}_IMAGE_SIZE_DIFFERS_FROM_SEGMENTATION")
            out.mask = None


def pair_key(earlier: ResolvedEndpoint, later: ResolvedEndpoint, framing_by: str | None) -> str:
    """Identifies exactly the evidence used. A new review or mask makes a new key."""

    keys = (
        "image_sha256",
        "mask_sha256s",
        "review_decision",
        "reviewed_at_utc",
        "config_sha256",
        "mask_crop_px",
        "review_state",
    )
    return content_id(
        {
            "calculation_version": CALCULATION_VERSION,
            "plugin_version": PLUGIN_VERSION,
            "framing_confirmed_by": framing_by,
            "earlier": {k: earlier.details.get(k) for k in keys},
            "later": {k: later.details.get(k) for k in keys},
            "earlier_ref": [earlier.ref.run_id, earlier.ref.filename],
            "later_ref": [later.ref.run_id, later.ref.filename],
        },
        24,
    )


def _same_framing(earlier: ResolvedEndpoint, later: ResolvedEndpoint) -> list[str]:
    reasons: list[str] = []
    a, b = earlier.details, later.details
    if a.get("site_id") != b.get("site_id") or a.get("camera_id") != b.get("camera_id"):
        reasons.append("DIFFERENT_CAMERA")
    if earlier.image_size and later.image_size and earlier.image_size != later.image_size:
        reasons.append("IMAGE_SIZE_CHANGED")
    if earlier.crop_px and later.crop_px and earlier.crop_px != later.crop_px:
        reasons.append("WATCHED_AREA_CHANGED")
    if a.get("reference_region") != b.get("reference_region"):
        reasons.append("WATCHED_AREA_CONFIG_CHANGED")
    return reasons


def measure_pair(
    sites_dir: Path,
    site_folder: str,
    earlier: EndpointRef,
    later: EndpointRef,
    *,
    framing_confirmed_by: str | None,
    freeze: bool = True,
) -> dict[str, Any]:
    """Measure the ordered pair (earlier, later) and keep the frozen result once.

    ``framing_confirmed_by`` is the person who confirmed both images show the same fixed view.
    The result is always returned, with an evidence record whose status is ``available`` only when
    every input was valid; otherwise it is unavailable/invalid with reason codes, never zero.
    """

    site_dir = _site_dir(sites_dir, site_folder)
    first = resolve_endpoint(site_dir, earlier, "EARLIER")
    second = resolve_endpoint(site_dir, later, "LATER")
    key = pair_key(first, second, framing_confirmed_by)
    target = site_dir / "outputs" / PAIR_DIR / f"{key}.json"
    if freeze and target.is_file():
        stored = json.loads(target.read_text(encoding="utf-8"))
        return {**stored, "reused": True, "path": str(target)}

    blocking = list(first.reasons) + list(second.reasons)
    framing = _same_framing(first, second)
    blocking.extend(framing)
    # A mask cut from a different watched area is invalid evidence for this run, not just missing.
    wrong_area = [r for r in blocking if r.endswith("_MASK_WATCHED_AREA_DIFFERS_FROM_RUN")]
    roi: Roi | None = None
    size = first.image_size or second.image_size
    crop = first.crop_px or second.crop_px
    if size is not None and crop is not None:
        try:
            roi = roi_from_crop(crop, size)
        except WaterChangeInputError as error:
            blocking.append(error.code)
    inputs = WaterChangeInputs(
        site_id=str(first.details.get("site_id") or second.details.get("site_id") or "unknown"),
        camera_id=str(first.details.get("camera_id") or second.details.get("camera_id") or ""),
        earlier=WaterChangeEndpoint(first.captured_at_utc, first.mask, first.details),
        later=WaterChangeEndpoint(second.captured_at_utc, second.mask, second.details),
        roi=roi,
        image_size=size,
        framing_confirmed_by=framing_confirmed_by,
        blocking_reasons=tuple(blocking),
        blocking_status="invalid" if framing or wrong_area else "unavailable",
        provenance={"site_folder": site_folder, "adapter": PLUGIN_ID},
    )
    record = WaterChangeObservationAdapter(inputs).collect()
    payload = {
        "pair_key": key,
        "calculation_version": CALCULATION_VERSION,
        "frozen_at_utc": utc_now(),
        "site_folder": site_folder,
        "earlier": first.details,
        "later": second.details,
        "evidence": record.to_dict(),
        "context": {
            "earlier_gauge": _gauge_context(first.snapshot) if first.loaded else None,
            "later_gauge": _gauge_context(second.snapshot) if second.loaded else None,
        },
    }
    if freeze:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")
        return {**payload, "reused": False, "path": str(target)}
    return {**payload, "reused": False, "path": None}

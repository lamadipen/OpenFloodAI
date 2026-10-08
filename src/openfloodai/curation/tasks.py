"""Task-specific evidence checks and annotations for dataset curation (Issue #215).

Each task needs different evidence, and each check explains what is missing instead of failing
silently:

- water segmentation: the image and a human-accepted water mask for those exact image bytes;
- low / middle / high classification: a human-reviewed, assessable image, the image's own matched
  gauge reading, and an approved versioned site category definition. The category is DERIVED from
  the gauge value with that definition; a sampling group is never read as a label;
- gauge-height estimation: the image and a valid own matched gauge reading with units, station,
  timestamps and quality flags;
- rising / falling: an explicitly chosen earlier and later observation from one stable camera view,
  each with a valid gauge reading. Pairs are never made automatically.

A gauge reading is instrument-derived supervision, not manually observed truth, and a nearby
station does not prove the same water elevation at the camera.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from openfloodai.curation.common import (
    SEVERITY_WARNING,
    TASK_GAUGE_HEIGHT,
    TASK_LEVEL_CHANGE,
    TASK_LEVEL_CLASSIFICATION,
    TASK_WATER_SEGMENTATION,
    content_id,
    errors_in,
    reason,
    sha256_file,
)
from openfloodai.curation.labels import categorize
from openfloodai.curation.snapshot import (
    UNASSESSABLE_LABELS,
    LoadedObservation,
    MaskCandidate,
)

MAX_GAUGE_GAP_SECONDS = 15 * 60
USABLE_QUALITY = {"approved", "provisional"}
WATER_MASK_PROMPTS = {"river water", "water"}


def _evaluation(reasons: list[dict[str, str]], annotation: dict[str, Any] | None) -> dict[str, Any]:
    eligible = not errors_in(reasons) and annotation is not None
    version = content_id(annotation, 16) if (annotation is not None and eligible) else None
    return {
        "eligible": eligible,
        "reasons": reasons,
        "annotation": annotation if eligible else None,
        "annotation_version": version,
    }


def _common_reasons(task: str, loaded: LoadedObservation) -> list[dict[str, str]]:
    snap = loaded.snapshot
    reasons = list(loaded.problems)
    if snap["dataset_group"] == "excluded":
        reasons.append(
            reason("excluded_group", "This image's date range is marked excluded for this site.")
        )
    review = snap.get("review")
    human = review.get("human_label") if review else None
    if task != TASK_WATER_SEGMENTATION and human in UNASSESSABLE_LABELS:
        reasons.append(
            reason(
                "unassessable_image",
                "A reviewer marked this image as one where the water level cannot be judged, so "
                "it cannot be an approved visual-height example. It may still support quality "
                "evaluation.",
            )
        )
    elif task == TASK_WATER_SEGMENTATION and human in UNASSESSABLE_LABELS:
        reasons.append(
            reason(
                "unassessable_image_note",
                "A reviewer could not judge the water level in this image. Use the mask only as "
                "visible water, not as height evidence.",
                SEVERITY_WARNING,
            )
        )
    if review and review.get("visibility", {}).get("camera_stable") == "no":
        severity = "error" if task == TASK_LEVEL_CHANGE else SEVERITY_WARNING
        reasons.append(
            reason(
                "camera_unstable",
                "A reviewer marked the camera as not stable in this image.",
                severity,
            )
        )
    if snap["dataset_group"] == "locked_validation":
        reasons.append(
            reason(
                "locked_validation",
                "This image is in a locked validation range. It can only go to the test split and "
                "must never be used for tuning.",
                SEVERITY_WARNING,
            )
        )
    return reasons


def gauge_reasons(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Why the image's OWN matched gauge reading can or cannot be supervision for this example."""

    gauge = snapshot["gauge"]
    reasons: list[dict[str, str]] = []
    reading = gauge.get("reading")
    if gauge.get("match_status") != "matched" or not isinstance(reading, dict):
        why = gauge.get("reason") or "no reading was matched to this image"
        reasons.append(
            reason("gauge_not_matched", f"This image has no valid own gauge reading: {why}.")
        )
        return reasons
    value = reading.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        reasons.append(
            reason("gauge_value_invalid", "The matched gauge reading has no valid number.")
        )
    if not reading.get("unit"):
        reasons.append(reason("gauge_unit_missing", "The matched gauge reading has no unit."))
    if not reading.get("datetime_utc"):
        reasons.append(reason("gauge_time_missing", "The matched gauge reading has no timestamp."))
    gap = gauge.get("time_difference_seconds")
    if not isinstance(gap, (int, float)) or abs(gap) > MAX_GAUGE_GAP_SECONDS:
        reasons.append(
            reason(
                "gauge_gap_too_large",
                "The gauge reading is not within 15 minutes of the image, or its time gap is "
                "unknown.",
            )
        )
    station = gauge.get("station") or {}
    if not station.get("nwis_site_id"):
        reasons.append(
            reason(
                "gauge_station_missing", "No gauge station association is recorded for this run."
            )
        )
    elif station.get("relationship") == "nearby":
        reasons.append(
            reason(
                "gauge_station_nearby",
                "The gauge station is nearby, not at the camera. It does not prove the same water "
                "elevation at the camera.",
                SEVERITY_WARNING,
            )
        )
    if reading.get("used_fallback_discharge") or reading.get("parameter_code") != "00065":
        reasons.append(
            reason(
                "gauge_not_height",
                "The matched reading is not a gauge height (it is a fallback such as discharge).",
            )
        )
    quality = reading.get("quality_status")
    if quality not in USABLE_QUALITY:
        reasons.append(
            reason(
                "gauge_quality_unusable", f"The reading's quality status ({quality}) is not usable."
            )
        )
    elif quality == "provisional":
        reasons.append(
            reason(
                "gauge_provisional",
                "The reading is provisional and may be revised.",
                SEVERITY_WARNING,
            )
        )
    if "e" in (reading.get("qualifiers") or []):
        reasons.append(
            reason("gauge_estimated", "USGS marked this reading as estimated.", SEVERITY_WARNING)
        )
    return reasons


def _review_reasons(task: str, snapshot: dict[str, Any]) -> list[dict[str, str]]:
    if snapshot.get("review"):
        return []
    if task == TASK_LEVEL_CLASSIFICATION:
        return [
            reason(
                "needs_human_review",
                "This image has no saved human review. Review it first so the category is "
                "supported by what a person can see.",
            )
        ]
    return [
        reason(
            "image_quality_unreviewed",
            "No person has reviewed this image's quality yet.",
            SEVERITY_WARNING,
        )
    ]


def evaluate_segmentation(
    loaded: LoadedObservation, masks: list[MaskCandidate], mask_result_id: str | None = None
) -> dict[str, Any]:
    reasons = _common_reasons(TASK_WATER_SEGMENTATION, loaded)
    pool = [m for m in masks if m.prompt in WATER_MASK_PROMPTS and m.status == "completed"]
    if mask_result_id:
        pool = [m for m in masks if m.result_id == mask_result_id]
        if not pool:
            reasons.append(
                reason("mask_missing", "That segmentation result is not for this image.")
            )
    chosen: MaskCandidate | None = None
    accepted = [m for m in pool if m.review_status == "accepted"]
    if not pool:
        if not mask_result_id:
            reasons.append(
                reason(
                    "mask_missing",
                    "This image has no saved water segmentation. Run segmentation from the review "
                    "page, or supply a human-verified mask.",
                )
            )
    elif not accepted:
        states = {m.review_status for m in pool}
        if "needs_correction" in states:
            reasons.append(
                reason(
                    "mask_needs_correction",
                    "The mask was marked as needing correction. A corrected mask must be supplied "
                    "through an established workflow; no mask editor is available here.",
                )
            )
        elif "rejected" in states:
            reasons.append(
                reason("mask_rejected", "The only saved mask was rejected by a reviewer.")
            )
        else:
            reasons.append(
                reason(
                    "mask_unreviewed",
                    "The saved mask has not been reviewed. A person must accept it before it "
                    "counts "
                    "as a verified annotation.",
                )
            )
    else:
        distinct = {tuple(_mask_hashes(m)) for m in accepted}
        if mask_result_id or len(distinct) == 1:
            chosen = accepted[0]
        else:
            ids = ", ".join(m.result_id for m in accepted)
            reasons.append(
                reason(
                    "mask_ambiguous",
                    f"More than one different accepted mask exists ({ids}). Choose which result "
                    "to use.",
                )
            )
    annotation = None
    if chosen is not None:
        hashes = _mask_hashes(chosen)
        if not chosen.mask_paths or not hashes:
            reasons.append(reason("mask_empty", "The accepted result has no mask file to keep."))
        elif any(not p.is_file() for p in chosen.mask_paths):
            reasons.append(
                reason("mask_file_missing", "A mask file of the accepted result is missing.")
            )
        else:
            record = chosen.record
            annotation = {
                "kind": "water_mask",
                "source": "machine_mask_human_accepted",
                "note": "A machine-made mask that a person accepted. It is not hand-drawn.",
                "prompt": chosen.prompt,
                "model_requested": record.get("model_requested"),
                "segmentation_run_id": chosen.run_id,
                "result_id": chosen.result_id,
                "processed_at_utc": record.get("processed_at_utc"),
                "transform": record.get("transform"),
                "masks": [
                    {
                        "sha256": h,
                        "mask_size": d.get("mask_size"),
                        "box_source_px": d.get("box_source_px"),
                    }
                    for h, d in zip(hashes, _detections(chosen), strict=False)
                ],
                "review_decision": "accepted",
            }
    return _evaluation(reasons, annotation)


def _detections(candidate: MaskCandidate) -> list[dict[str, Any]]:
    return [
        d
        for d in candidate.record.get("detections", [])
        if isinstance(d, dict) and d.get("mask_png")
    ]


def _mask_hashes(candidate: MaskCandidate) -> list[str]:
    try:
        return [sha256_file(p) for p in candidate.mask_paths if p.is_file()]
    except OSError:
        return []


def evaluate_gauge_height(loaded: LoadedObservation) -> dict[str, Any]:
    snap = loaded.snapshot
    reasons = _common_reasons(TASK_GAUGE_HEIGHT, loaded)
    reasons += _review_reasons(TASK_GAUGE_HEIGHT, snap)
    reasons += gauge_reasons(snap)
    annotation = None
    if not errors_in(reasons):
        annotation = _gauge_annotation(snap)
    return _evaluation(reasons, annotation)


def _gauge_annotation(snap: dict[str, Any]) -> dict[str, Any]:
    gauge = snap["gauge"]
    reading = gauge["reading"]
    station = gauge.get("station") or {}
    return {
        "kind": "gauge_height",
        "source": "instrument_gauge_reading",
        "note": "Instrument-derived supervision, not manually observed truth.",
        "value": reading["value"],
        "unit": reading["unit"],
        "parameter_code": reading.get("parameter_code"),
        "reading_datetime_utc": reading["datetime_utc"],
        "time_difference_seconds": gauge["time_difference_seconds"],
        "qualifiers": reading.get("qualifiers") or [],
        "quality_status": reading.get("quality_status"),
        "station_nwis_id": station.get("nwis_site_id"),
        "station_relationship": station.get("relationship"),
    }


def evaluate_classification(
    loaded: LoadedObservation, definition: dict[str, Any] | None
) -> dict[str, Any]:
    snap = loaded.snapshot
    reasons = _common_reasons(TASK_LEVEL_CLASSIFICATION, loaded)
    reasons += _review_reasons(TASK_LEVEL_CLASSIFICATION, snap)
    gauge_problems = gauge_reasons(snap)
    reasons += gauge_problems
    annotation = None
    if definition is None:
        reasons.append(
            reason(
                "definition_missing",
                "This dataset has no approved category definition for this site. Low, middle and "
                "high need versioned, approved thresholds with a unit and a source.",
            )
        )
    elif not errors_in(gauge_problems):
        reading = snap["gauge"]["reading"]
        station = (snap["gauge"].get("station") or {}).get("nwis_site_id")
        if station != definition["station_nwis_id"]:
            reasons.append(
                reason(
                    "definition_station_mismatch",
                    f"The category definition is for station {definition['station_nwis_id']}, but "
                    f"this reading is from {station}.",
                )
            )
        elif reading["unit"] != definition["unit"]:
            reasons.append(
                reason(
                    "definition_unit_mismatch",
                    f"The category definition uses {definition['unit']}, but this reading is in "
                    f"{reading['unit']}.",
                )
            )
        elif reading.get("parameter_code") != definition.get("parameter_code"):
            reasons.append(
                reason(
                    "definition_parameter_mismatch",
                    "The category definition is for a different measured quantity than this "
                    "reading.",
                )
            )
        else:
            category = categorize(float(reading["value"]), definition)
            if category is None:
                reasons.append(
                    reason(
                        "value_outside_bands",
                        "The gauge value is outside every band of the category definition.",
                    )
                )
            elif not errors_in(reasons):
                review = snap["review"] or {}
                annotation = {
                    "kind": "level_category",
                    "source": "gauge_value_with_approved_definition",
                    "note": "Derived from the numeric gauge value. It is not a sampling group.",
                    "category": category,
                    "gauge_value": reading["value"],
                    "unit": reading["unit"],
                    "definition": {
                        "site_id": definition["site_id"],
                        "version": definition["version"],
                    },
                    "human_label": review.get("human_label"),
                    "human_label_revision": review.get("label_revision"),
                    "gauge": _gauge_annotation(snap),
                }
    return _evaluation(reasons, annotation)


def evaluate_pair(
    earlier: LoadedObservation,
    later: LoadedObservation,
    *,
    change_tolerance: float | None,
) -> dict[str, Any]:
    """An explicitly chosen earlier/later pair from one stable camera view."""

    e, ls = earlier.snapshot, later.snapshot
    reasons: list[dict[str, str]] = []
    for label, loaded in (("earlier", earlier), ("later", later)):
        for item in _common_reasons(TASK_LEVEL_CHANGE, loaded) + gauge_reasons(loaded.snapshot):
            if item["severity"] == SEVERITY_WARNING and item["code"] == "locked_validation":
                reasons.append(item)
            else:
                reasons.append({**item, "message": f"The {label} image: {item['message']}"})
    if e["observation_key"] == ls["observation_key"]:
        reasons.append(reason("pair_same_image", "A pair needs two different images."))
    if (e["site"]["site_id"], e["site"]["camera_id"]) != (
        ls["site"]["site_id"],
        ls["site"]["camera_id"],
    ):
        reasons.append(
            reason("pair_different_camera", "Both images must come from the same site and camera.")
        )
    elapsed = None
    if e["source"]["captured_at_utc"] and ls["source"]["captured_at_utc"]:
        from datetime import datetime

        start = datetime.fromisoformat(e["source"]["captured_at_utc"])
        end = datetime.fromisoformat(ls["source"]["captured_at_utc"])
        elapsed = (end - start).total_seconds()
        if elapsed <= 0:
            reasons.append(
                reason("pair_not_ordered", "The earlier image must be older than the later one.")
            )
    if e["configuration"].get("reference_region") != ls["configuration"].get("reference_region"):
        reasons.append(
            reason(
                "pair_view_changed",
                "The two runs used different watched areas, so they may not show the same "
                "camera view.",
            )
        )
    annotation = None
    if not errors_in(reasons):
        a, b = e["gauge"], ls["gauge"]
        ra, rb = a["reading"], b["reading"]
        if (a.get("station") or {}).get("nwis_site_id") != (b.get("station") or {}).get(
            "nwis_site_id"
        ) or ra["unit"] != rb["unit"]:
            reasons.append(
                reason(
                    "pair_gauge_mismatch", "Both readings must come from the same station and unit."
                )
            )
        else:
            delta = float(rb["value"]) - float(ra["value"])
            direction = None
            if change_tolerance is not None:
                direction = (
                    "no_change"
                    if abs(delta) <= change_tolerance
                    else ("rising" if delta > 0 else "falling")
                )
            annotation = {
                "kind": "level_change",
                "source": "gauge_difference_between_explicit_pair",
                "note": "Target derived from two instrument readings. The direction needs an "
                "explicit tolerance and is empty without one.",
                "earlier_observation": e["observation_key"],
                "later_observation": ls["observation_key"],
                "earlier_value": ra["value"],
                "later_value": rb["value"],
                "unit": ra["unit"],
                "delta": round(delta, 6),
                "elapsed_seconds": elapsed,
                "change_tolerance": change_tolerance,
                "direction": direction,
                "station_nwis_id": (a.get("station") or {}).get("nwis_site_id"),
            }
    return _evaluation(reasons, annotation)


def image_paths_exist(paths: list[Path]) -> bool:
    return all(p.is_file() for p in paths)

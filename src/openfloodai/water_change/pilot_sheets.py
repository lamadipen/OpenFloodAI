"""Local, reproducible inventory and contact sheets for the water-change pilot (Issue #222).

Everything here is written to the pilot folder as plain files (PNG + HTML + JSON). Nothing is
uploaded and no segmentation is started. The blind sheet shows only the two images; the measured
sheet adds masks, the spatial overlay, the measurement and (afterwards) the frozen gauge context.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt

from openfloodai.curation.tasks import WATER_MASK_PROMPTS
from openfloodai.validation import hosted_sam_runner
from openfloodai.vision.water_change import (
    CALCULATION_VERSION,
    NEWLY_WET_BGR,
    NO_LONGER_WET_BGR,
    STILL_WET_BGR,
    Roi,
    change_overlay,
    roi_from_crop,
)
from openfloodai.water_change.pair import ResolvedEndpoint, resolve_endpoint
from openfloodai.water_change.pilot import (
    JUDGMENT_LABELS,
    PilotError,
    PilotPair,
    load_criteria,
    load_pairs,
    machine_direction,
)

PANEL_WIDTH = 480
Image = npt.NDArray[Any]


# ---------------------------------------------------------------- inventory


def inventory_accepted_masks(sites_dir: Path) -> dict[str, Any]:
    """Every human-accepted completed water mask on disk, grouped by camera and watched area.

    Read-only. Two accepted masks can only form a pair if they share a camera, image size and
    watched area, so those groups say how many pairs a camera could support.
    """

    rows: list[dict[str, Any]] = []
    for site_dir in sorted(p for p in sites_dir.iterdir() if p.is_dir()):
        for summary in hosted_sam_runner.list_sam_runs(site_dir):
            run_id = str(summary.get("run_id", ""))
            try:
                run = hosted_sam_runner.read_sam_run(site_dir, run_id)
            except (OSError, ValueError, KeyError):
                continue
            for result in run["results"]:
                if (
                    result.get("review_status") != "accepted"
                    or result.get("status") != "completed"
                    or result.get("prompt") not in WATER_MASK_PROMPTS
                ):
                    continue
                transform = result.get("transform") or {}
                filename = str(result.get("filename", ""))
                rows.append(
                    {
                        "site_folder": site_dir.name,
                        "camera_id": filename.split("___")[0],
                        "filename": filename,
                        "captured_at_utc": result.get("captured_at_utc"),
                        "sequence_id": run.get("sequence_id"),
                        "segmentation_run_id": run_id,
                        "result_id": result.get("result_id"),
                        "crop_px": transform.get("crop_px"),
                        "source_size": transform.get("source_size"),
                        "image_runs": _image_runs(site_dir, str(run.get("sequence_id", ""))),
                    }
                )
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = json.dumps([row["site_folder"], row["camera_id"], row["source_size"], row["crop_px"]])
        group = groups.setdefault(
            key,
            {
                "site_folder": row["site_folder"],
                "camera_id": row["camera_id"],
                "source_size": row["source_size"],
                "crop_px": row["crop_px"],
                "images": set(),
            },
        )
        group["images"].add(row["filename"])
    summary_rows = [
        {
            **{k: v for k, v in g.items() if k != "images"},
            "distinct_images_with_accepted_mask": len(g["images"]),
        }
        for g in groups.values()
    ]
    summary_rows.sort(key=lambda g: -g["distinct_images_with_accepted_mask"])
    return {
        "accepted_water_masks": len(rows),
        "by_camera_and_watched_area": summary_rows,
        "masks": rows,
        "note": (
            "Comparable pairs need two images of one camera with the same image size and "
            "watched area. Masks that are unreviewed, rejected or need correction are not listed."
        ),
    }


def _image_runs(site_dir: Path, sequence_id: str) -> list[str]:
    root = site_dir / "outputs" / "image-sequence-runs"
    runs: list[str] = []
    if not root.is_dir():
        return runs
    for run_dir in sorted(root.iterdir()):
        try:
            summary = json.loads((run_dir / "run-summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if summary.get("sequence_id") == sequence_id:
            runs.append(run_dir.name)
    return runs


# ---------------------------------------------------------------- rendering


def _read_image(endpoint: ResolvedEndpoint) -> Image | None:
    if endpoint.loaded is None or endpoint.loaded.image_path is None:
        return None
    image = cv2.imread(str(endpoint.loaded.image_path))
    return None if image is None else np.asarray(image)


def _fit(image: Image, width: int = PANEL_WIDTH) -> Image:
    scale = width / image.shape[1]
    return np.asarray(cv2.resize(image, (width, max(1, round(image.shape[0] * scale)))))


def _caption(image: Image, text: str) -> Image:
    band = np.full((22, image.shape[1], 3), 245, dtype=np.uint8)
    cv2.putText(band, text[:70], (4, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1)
    return np.vstack([band, image])


def _tinted(image: Image, mask: Image | None, roi: Roi | None) -> Image:
    out = image.copy()
    if mask is not None:
        selection = mask > 0
        out[selection] = (0.5 * out[selection] + 0.5 * np.array(NEWLY_WET_BGR)).astype(np.uint8)
    if roi is not None:
        cv2.rectangle(out, (roi.x0, roi.y0), (roi.x1 - 1, roi.y1 - 1), (0, 255, 255), 1)
    return out


def _roi_for(*endpoints: ResolvedEndpoint) -> Roi | None:
    for endpoint in endpoints:
        if endpoint.crop_px and endpoint.image_size:
            try:
                return roi_from_crop(endpoint.crop_px, endpoint.image_size)
            except ValueError:
                continue
    return None


def _write_png(path: Path, image: Image) -> None:
    if not cv2.imwrite(str(path), image):
        raise PilotError(f"Could not write {path.name}.")


def _resolve(
    pilot_dir_sites: Path, folder: str, pair: PilotPair
) -> tuple[ResolvedEndpoint, ResolvedEndpoint]:
    site_dir = pilot_dir_sites / folder
    return (
        resolve_endpoint(site_dir, pair.earlier, "EARLIER"),
        resolve_endpoint(site_dir, pair.later, "LATER"),
    )


def render_blind_sheet(pilot_dir: Path, sites_dir: Path) -> Path:
    """Images only, for people judging BEFORE they see machine results or gauge values."""

    folder, pairs = load_pairs(pilot_dir)
    out = pilot_dir / "blind-sheet"
    out.mkdir(exist_ok=True)
    cards: list[tuple[str, str | None, str]] = []
    template: dict[str, Any] = {
        "reviewer": "",
        "role": "",
        "judged_at_utc": "",
        "blind_to_machine_results": False,
        "blind_to_gauge": False,
        "judgments": {p.pair_id: {"later_vs_earlier": "", "note": ""} for p in pairs},
        "allowed_labels": list(JUDGMENT_LABELS),
        "instructions": (
            "Judge only the visible water inside the yellow box: does the LATER image show more "
            "water, less water or about the same as the EARLIER one? Use cannot_judge when you "
            "cannot tell (glare, ice, dark, blocked). Set the two blind_* fields to true only if "
            "you have seen no machine result and no gauge value. Save as judgments/<name>.json."
        ),
    }
    for pair in pairs:
        earlier, later = _resolve(sites_dir, folder, pair)
        a, b = _read_image(earlier), _read_image(later)
        if a is None or b is None:
            cards.append((pair.pair_id, None, "an image is not available"))
            continue
        roi = _roi_for(earlier, later)
        panels = [
            _caption(_fit(_tinted(a, None, roi)), f"EARLIER {earlier.captured_at_utc[:16]}"),
            _caption(_fit(_tinted(b, None, roi)), f"LATER {later.captured_at_utc[:16]}"),
        ]
        name = f"{pair.pair_id}.png"
        _write_png(out / name, np.hstack(panels))
        cards.append((pair.pair_id, name, ""))
    body = "".join(
        f"<h3>{html.escape(pid)}</h3>"
        + (
            f'<img src="{html.escape(name)}" style="max-width:100%">'
            if name
            else f"<p>{html.escape(why)}</p>"
        )
        for pid, name, why in cards
    )
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Blind sheet</title>"
        "<p>Images only. No machine result and no gauge value are shown here.</p>" + body,
        encoding="utf-8",
    )
    (out / "judgment-template.json").write_text(
        json.dumps(template, indent=2) + "\n", encoding="utf-8"
    )
    return out / "index.html"


def render_measured_sheet(pilot_dir: Path, sites_dir: Path, measurement: dict[str, Any]) -> Path:
    """Images, masks, the spatial overlay and the numbers. Open it only after judging."""

    criteria = load_criteria(pilot_dir)
    folder, pairs = load_pairs(pilot_dir)
    by_id = {p.pair_id: p for p in pairs}
    out = pilot_dir / "contact-sheet"
    out.mkdir(exist_ok=True)
    legend = (
        "<p>Overlay colours: "
        f"<b style='color:rgb{tuple(reversed(NEWLY_WET_BGR))}'>water arrived</b>, "
        f"<b style='color:rgb{tuple(reversed(NO_LONGER_WET_BGR))}'>water left</b>, "
        f"<b style='color:rgb{tuple(reversed(STILL_WET_BGR))}'>wet in both</b>. "
        "Yellow box = the fixed watched area. Image-space area only; not water level or flow.</p>"
    )
    sections = []
    for row in measurement["results"]:
        pair = by_id.get(row["pair_id"])
        if pair is None:
            continue
        evidence = row["evidence"]
        earlier, later = _resolve(sites_dir, folder, pair)
        a, b = _read_image(earlier), _read_image(later)
        figure = ""
        if a is not None and b is not None:
            roi = _roi_for(earlier, later)
            panels = [
                _caption(
                    _fit(_tinted(a, earlier.mask, roi)), f"EARLIER {earlier.captured_at_utc[:16]}"
                ),
                _caption(_fit(_tinted(b, later.mask, roi)), f"LATER {later.captured_at_utc[:16]}"),
            ]
            if earlier.mask is not None and later.mask is not None and roi is not None:
                panels.append(
                    _caption(_fit(change_overlay(b, earlier.mask, later.mask, roi)), "CHANGE")
                )
            name = f"{pair.pair_id}.png"
            _write_png(out / name, np.hstack(panels))
            figure = f'<img src="{html.escape(name)}" style="max-width:100%">'
        if evidence["status"] == "available":
            measure = evidence["quality"]["measurement"]
            direction = machine_direction(evidence["value"], criteria.stable_tolerance_pp)
            summary = (
                f"coverage {measure['earlier_fraction']:.1%} → {measure['later_fraction']:.1%} "
                f"({evidence['value']:+.1f} pp, machine reads: {direction}); newly wet "
                f"{measure['newly_wet_fraction']:.1%}, no longer wet "
                f"{measure['no_longer_wet_fraction']:.1%}; rate "
                f"{measure['change_rate_pp_per_hour']:+.2f} pp/h (image-space)"
            )
        else:
            summary = f"UNAVAILABLE ({evidence['status']}): {', '.join(evidence['reason_codes'])}"
        gauge = row["context"]
        gauge_text = _gauge_text(gauge)
        sections.append(
            f"<h3>{html.escape(pair.pair_id)} · {html.escape(pair.case_type)}"
            f"{' · HELD OUT' if pair.held_out else ''}</h3>{figure}"
            f"<p>{html.escape(summary)}</p><p><i>Gauge context (not a label): "
            f"{html.escape(gauge_text)}</i></p>"
        )
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Water-change contact sheet</title>"
        f"<p>Calculation {html.escape(CALCULATION_VERSION)}. Open after independent judging.</p>"
        + legend
        + "".join(sections),
        encoding="utf-8",
    )
    return out / "index.html"


def _gauge_text(context: dict[str, Any]) -> str:
    earlier, later = context.get("earlier_gauge"), context.get("later_gauge")
    if not earlier or not later or not earlier.get("usable") or not later.get("usable"):
        return "no usable matched reading at both ends"
    return f"{earlier['value']} → {later['value']} {later['unit']}"

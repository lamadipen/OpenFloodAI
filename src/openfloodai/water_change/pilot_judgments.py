"""Turn a reviewer's blind labels from the focused review page into a pilot judgments file.

The pilot compares the machine with independent human judgments written BEFORE anyone saw machine
results (see ``pilot.py``). The focused review page already collects exactly that: a label for one
image against a named reference, tagged ``blind`` when the reviewer had seen no machine or gauge
evidence. This module reads those saved labels for the pilot's pairs and writes
``judgments/<reviewer>.json`` in the format the pilot report expects.

Only blind labels are exported. An informed revision, an older save with no stage, or a pair this
reviewer has not labelled is left out and listed, so nothing is guessed. Directions are earlier ->
later: ``more_water`` means the later image shows more visible water.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openfloodai.curation.visual_change import collect_judgments
from openfloodai.water_change.pilot import (
    JUDGMENT_LABELS,
    JUDGMENTS_DIR,
    MEASUREMENTS_DIR,
    PilotError,
    load_pairs,
)


def _run_dir(sites_dir: Path, folder: str, run_id: str) -> Path:
    return sites_dir / folder / "outputs" / "image-sequence-runs" / run_id


def export_reviewer_judgments(pilot_dir: Path, sites_dir: Path, reviewer: str) -> dict[str, Any]:
    """Write ``judgments/<reviewer>.json`` for this reviewer's blind labels on the pilot pairs."""

    wanted = reviewer.strip()
    if not wanted:
        raise PilotError("Name the reviewer code to export.")
    folder, pairs = load_pairs(pilot_dir)
    judgments: dict[str, dict[str, str]] = {}
    times: list[str] = []
    missing: list[str] = []
    set_aside = 0
    for pair in pairs:
        found, ignored = collect_judgments(
            _run_dir(sites_dir, folder, pair.earlier.run_id),
            pair.earlier.filename,
            _run_dir(sites_dir, folder, pair.later.run_id),
            pair.later.filename,
        )
        set_aside += ignored
        mine = next((j for j in found if j.reviewer.casefold() == wanted.casefold()), None)
        if mine is None:
            missing.append(pair.pair_id)
            continue
        label = mine.direction or "cannot_judge"
        if label not in JUDGMENT_LABELS:
            raise PilotError(f"Pair '{pair.pair_id}' has an unusable label '{label}'.")
        judgments[pair.pair_id] = {"later_vs_earlier": label}
        times.append(mine.reviewed_at_utc)
    if not judgments:
        raise PilotError(
            f"No blind labels by '{wanted}' were found for these pairs. Label them on the focused "
            "review page in blind mode first."
        )
    target = pilot_dir / JUDGMENTS_DIR / f"{wanted}.json"
    payload = {
        "reviewer": wanted,
        "role": "",
        "judged_at_utc": max(times),
        "blind_to_machine_results": True,
        "blind_to_gauge": True,
        "source": "focused_review_blind_stage",
        "judgments": judgments,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")
    except FileExistsError as error:
        raise PilotError(
            f"{target.name} already exists. A reviewer has one judgments file; remove it first."
        ) from error
    measurements = sorted((pilot_dir / MEASUREMENTS_DIR).glob("*.json"))
    return {
        "path": str(target),
        "reviewer": wanted,
        "exported_pairs": sorted(judgments),
        "not_labelled_by_reviewer": missing,
        "labels_set_aside": set_aside,
        "judged_at_utc": payload["judged_at_utc"],
        "measurements_already_exist": bool(measurements),
        "warning": (
            "A machine measurement already exists, so the report will set this file aside "
            "if it was judged after that measurement."
            if measurements
            else None
        ),
    }

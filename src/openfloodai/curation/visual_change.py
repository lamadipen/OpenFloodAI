"""The visual-change task: a pair of images and what people saw changed.

Unlike the gauge-derived rising / falling task, the target here is the HUMAN judgment of a pair,
and it is only eligible when enough different people made it:

- Each judgment is a reviewer's label for one image compared with a named reference image.
- A label made in the blind stage (before machine evidence was shown) or in the informed stage
  (after it, as in Assisted review) counts. An informed label is never hidden: it is marked as such
  on the judgment, reported as a warning, and the annotation says it is not blind-only, so a
  dataset can still be filtered down to independent judgments. When one reviewer has both, the
  blind label is the one that counts. An older save with no stage, or one with no reviewer code, is
  kept as history but never counted.
- At least `MIN_JUDGMENTS` judgment is needed, so the pair has a direction (usually the person
  adding it). More reviewers are not required to add a pair: confirming what is in a dataset is a
  separate review step that runs after the data is added, and each example is stored as awaiting it.
  When several people did judge it, they must agree: disagreement, a "cannot judge" or "camera
  problem" answer, or a reported camera move makes the pair ineligible with the reason, never a
  majority vote.
- Directions are expressed earlier -> later: "more_water" means the later image shows more visible
  water. If the reviewer's reference was the later image, their label is flipped to match.

Reviewer codes are kept in the local draft for audit but are not part of a public release.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openfloodai.contracts import read_jsonl_records
from openfloodai.curation.common import (
    SEVERITY_WARNING,
    content_id,
    errors_in,
    reason,
)
from openfloodai.curation.snapshot import LoadedObservation

MIN_JUDGMENTS = 1
MIN_INDEPENDENT_REVIEWERS = 2  # what "independent blind agreement" means in an annotation
DIRECTION_BY_LABEL = {
    "water_level_rising": "more_water",
    "water_level_falling": "less_water",
    "no_water_level_change": "about_same",
}
UNJUDGED_LABELS = {"cannot_judge_water_level", "camera_video_problem"}
_FLIP = {"more_water": "less_water", "less_water": "more_water", "about_same": "about_same"}
DIRECTIONS = tuple(_FLIP)


@dataclass(frozen=True)
class Judgment:
    reviewer: str
    label: str
    direction: str | None  # earlier -> later; None for "cannot judge" / "camera problem"
    camera_stable: str | None
    reviewed_at_utc: str
    stage: str = "blind"  # "blind", or "informed" when the evidence had been shown first


def _reference_filename(observation: dict[str, Any]) -> str:
    ref = observation.get("reference")
    if isinstance(ref, dict) and ref.get("filename"):
        return str(ref["filename"])
    return str(observation.get("baseline_filename") or "")  # an older save used the run baseline


def _observations(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "human-review" / "observations.jsonl"
    if not path.is_file():
        return []
    return [dict(r) for r in read_jsonl_records(path) if r.get("kind") == "image"]


def _latest_counted(
    run_dir: Path, current_filename: str, reference_filename: str
) -> tuple[dict[str, dict[str, Any]], int]:
    """The label of each reviewer that counts for this image against this reference.

    A reviewer's latest blind label wins; without one, their latest informed label. Also counts the
    labels that were set aside: no stage or no reviewer code, and informed labels of a reviewer who
    also has a blind one.
    """

    blind: dict[str, dict[str, Any]] = {}
    informed: dict[str, dict[str, Any]] = {}
    set_aside = 0
    for observation in _observations(run_dir):
        if observation.get("filename") != current_filename:
            continue
        if _reference_filename(observation) != reference_filename:
            continue
        raw_label = observation.get("label")
        label: dict[str, Any] = raw_label if isinstance(raw_label, dict) else {}
        reviewer = str(label.get("reviewer_id") or "").strip()
        stage = observation.get("review_stage")
        if stage not in ("blind", "informed") or not reviewer:
            set_aside += 1
            continue
        bucket = blind if stage == "blind" else informed
        key = reviewer.casefold()
        previous = bucket.get(key)
        if previous is None or int(observation.get("label_revision") or 0) >= int(
            previous.get("label_revision") or 0
        ):
            bucket[key] = observation
    latest = dict(blind)
    for key, observation in informed.items():
        if key in blind:
            set_aside += 1
        else:
            latest[key] = observation
    return latest, set_aside


def collect_judgments(
    earlier_run: Path,
    earlier_filename: str,
    later_run: Path,
    later_filename: str,
) -> tuple[list[Judgment], int]:
    """Judgments for the pair in earlier -> later terms, and how many were set aside."""

    found: dict[str, Judgment] = {}
    set_aside = 0
    for run_dir, current, reference, flip in (
        (later_run, later_filename, earlier_filename, False),  # reviewed the later image
        (earlier_run, earlier_filename, later_filename, True),  # reviewed the earlier image
    ):
        latest, ignored = _latest_counted(run_dir, current, reference)
        set_aside += ignored
        for key, observation in latest.items():
            label_data = observation["label"]
            human = str(label_data.get("human_label") or "")
            direction = DIRECTION_BY_LABEL.get(human)
            if direction is not None and flip:
                direction = _FLIP[direction]
            judgment = Judgment(
                reviewer=str(label_data.get("reviewer_id")).strip(),
                label=human,
                direction=direction,
                camera_stable=label_data.get("camera_stable"),
                reviewed_at_utc=str(observation.get("reviewed_at_utc") or ""),
                stage=str(observation.get("review_stage")),
            )
            existing = found.get(key)
            # Between the two images a blind judgment beats an informed one, then the later wins.
            if existing is None or (judgment.stage == "blind", judgment.reviewed_at_utc) >= (
                existing.stage == "blind",
                existing.reviewed_at_utc,
            ):
                found[key] = judgment
    return sorted(found.values(), key=lambda j: j.reviewer.casefold()), set_aside


def _image_reasons(loaded: LoadedObservation) -> list[dict[str, str]]:
    snap = loaded.snapshot
    reasons = list(loaded.problems)
    if snap["dataset_group"] == "excluded":
        reasons.append(
            reason("excluded_group", "This image's date range is marked excluded for this site.")
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


def evaluate_visual_pair(
    earlier: LoadedObservation,
    later: LoadedObservation,
    judgments: list[Judgment],
    *,
    set_aside: int = 0,
    min_judgments: int = MIN_JUDGMENTS,
) -> dict[str, Any]:
    """Is this pair, with its recorded judgments, an eligible visual-change example?"""

    e, ls = earlier.snapshot, later.snapshot
    reasons: list[dict[str, str]] = []
    for label, loaded in (("earlier", earlier), ("later", later)):
        for item in _image_reasons(loaded):
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
        elapsed = (
            datetime.fromisoformat(ls["source"]["captured_at_utc"])
            - datetime.fromisoformat(e["source"]["captured_at_utc"])
        ).total_seconds()
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

    reviewers = [j.reviewer for j in judgments]
    if set_aside:
        reasons.append(
            reason(
                "reviews_set_aside",
                f"{set_aside} review(s) were not counted: older saves with no stage, reviews "
                "with no reviewer code, or informed labels replaced by the same reviewer's "
                "blind label.",
                SEVERITY_WARNING,
            )
        )
    informed = [j.reviewer for j in judgments if j.stage != "blind"]
    if informed:
        reasons.append(
            reason(
                "informed_judgments_counted",
                f"{', '.join(informed)} judged this pair after seeing machine evidence (informed). "
                "The judgment is counted and marked; it is not an independent blind judgment.",
                SEVERITY_WARNING,
            )
        )
    if len(judgments) < min_judgments:
        reasons.append(
            reason(
                "needs_a_judgment",
                "Nobody has judged this pair yet. Label it first (for example your own judgment) "
                "so the pair has a direction. Other reviewers confirm it after it is in a dataset.",
            )
        )
    undecided = [j.reviewer for j in judgments if j.direction is None]
    if undecided:
        reasons.append(
            reason(
                "reviewer_cannot_judge",
                f"{', '.join(undecided)} could not judge this pair or reported a camera problem, "
                "so it is not a clear example.",
            )
        )
    decided = {j.direction for j in judgments if j.direction is not None}
    if len(decided) > 1:
        reasons.append(
            reason(
                "reviewers_disagree",
                "Reviewers disagree: "
                + "; ".join(f"{j.reviewer}: {j.direction or j.label}" for j in judgments)
                + ". Resolve it before adding the pair; there is no majority vote.",
            )
        )
    moved = [j.reviewer for j in judgments if j.camera_stable == "no"]
    if moved:
        reasons.append(
            reason(
                "camera_moved_reported",
                f"{', '.join(moved)} reported that the camera view changed between the images.",
            )
        )
    unsure = [j.reviewer for j in judgments if j.camera_stable in (None, "", "unsure")]
    if unsure and judgments:
        reasons.append(
            reason(
                "camera_stability_unconfirmed",
                f"{', '.join(unsure)} did not confirm that the camera view stayed the same.",
                SEVERITY_WARNING,
            )
        )

    annotation: dict[str, Any] | None = None
    if not errors_in(reasons):
        direction = next(iter(decided))
        blind_only = not informed
        independent = blind_only and len(judgments) >= MIN_INDEPENDENT_REVIEWERS
        annotation = {
            "kind": "visual_change",
            "source": (
                "independent_blind_human_judgments_in_agreement"
                if independent
                else "human_judgments_awaiting_dataset_review"
            ),
            "note": (
                "What "
                + (
                    "at least two reviewers saw, each judged blind, before any machine or gauge "
                    "evidence. "
                    if independent
                    else f"{len(judgments)} reviewer(s) saw"
                    + (", some after machine evidence was shown" if informed else "")
                    + ". It is awaiting review inside the dataset. "
                )
                + "It is not a gauge measurement and not a flood decision."
            ),
            "dataset_review": "pending",
            "earlier_observation": e["observation_key"],
            "later_observation": ls["observation_key"],
            "direction": direction,
            "elapsed_seconds": elapsed,
            "reviewer_count": len(judgments),
            "reviewers": reviewers,
            "judgments": [
                {
                    "reviewer": j.reviewer,
                    "label": j.label,
                    "reviewed_at_utc": j.reviewed_at_utc,
                    "stage": j.stage,
                }
                for j in judgments
            ],
            "informed_count": len(informed),
            "blind_judgments_only": blind_only,
        }
    eligible = annotation is not None
    return {
        "eligible": eligible,
        "reasons": reasons,
        "annotation": annotation,
        "annotation_version": content_id(annotation, 16) if annotation else None,
    }


def agreement_summary(judgments: list[Judgment]) -> dict[str, Any]:
    """A short, display-ready view of where the reviewers stand."""

    by_direction: dict[str, list[str]] = defaultdict(list)
    for j in judgments:
        by_direction[j.direction or "cannot_judge"].append(j.reviewer)
    return {
        "reviewers": len(judgments),
        "needed": MIN_JUDGMENTS,
        "informed": sorted(j.reviewer for j in judgments if j.stage != "blind"),
        "by_direction": {k: sorted(v) for k, v in sorted(by_direction.items())},
        "agree": len(by_direction) == 1 and "cannot_judge" not in by_direction,
    }

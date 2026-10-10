"""The visual-change task: a pair of images and what independent people saw changed.

Unlike the gauge-derived rising / falling task, the target here is the HUMAN judgment of a pair,
and it is only eligible when enough people made it independently:

- Each judgment is a reviewer's label for one image compared with a named reference image.
- Only labels made in the blind stage count. An informed revision (made after machine evidence was
  shown) and an older save with no stage are kept as history but never counted.
- At least `MIN_REVIEWERS` different reviewer codes must agree on a direction. Disagreement, a
  "cannot judge" or "camera problem" answer, or a reported camera move makes the pair ineligible
  with the reason, never a majority vote.
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

MIN_REVIEWERS = 2
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


def _blind_latest(
    run_dir: Path, current_filename: str, reference_filename: str
) -> tuple[dict[str, dict[str, Any]], int]:
    """The latest BLIND label of each reviewer for this image against this reference.

    Also counts the labels that were set aside (informed, unspecified or unattributed).
    """

    latest: dict[str, dict[str, Any]] = {}
    set_aside = 0
    for observation in _observations(run_dir):
        if observation.get("filename") != current_filename:
            continue
        if _reference_filename(observation) != reference_filename:
            continue
        raw_label = observation.get("label")
        label: dict[str, Any] = raw_label if isinstance(raw_label, dict) else {}
        reviewer = str(label.get("reviewer_id") or "").strip()
        if observation.get("review_stage") != "blind" or not reviewer:
            set_aside += 1
            continue
        key = reviewer.casefold()
        previous = latest.get(key)
        if previous is None or int(observation.get("label_revision") or 0) >= int(
            previous.get("label_revision") or 0
        ):
            latest[key] = observation
    return latest, set_aside


def collect_judgments(
    earlier_run: Path,
    earlier_filename: str,
    later_run: Path,
    later_filename: str,
) -> tuple[list[Judgment], int]:
    """Blind judgments for the pair in earlier -> later terms, and how many were set aside."""

    found: dict[str, Judgment] = {}
    set_aside = 0
    for run_dir, current, reference, flip in (
        (later_run, later_filename, earlier_filename, False),  # reviewed the later image
        (earlier_run, earlier_filename, later_filename, True),  # reviewed the earlier image
    ):
        latest, ignored = _blind_latest(run_dir, current, reference)
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
            )
            existing = found.get(key)
            if existing is None or judgment.reviewed_at_utc >= existing.reviewed_at_utc:
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
    min_reviewers: int = MIN_REVIEWERS,
) -> dict[str, Any]:
    """Is this pair, with its recorded blind judgments, an eligible visual-change example?"""

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
                f"{set_aside} review(s) were not counted: informed revisions, older saves with no "
                "blind stage, or reviews with no reviewer code.",
                SEVERITY_WARNING,
            )
        )
    if len(judgments) < min_reviewers:
        reasons.append(
            reason(
                "needs_more_reviewers",
                f"{len(judgments)} independent blind reviewer(s) so far; at least {min_reviewers} "
                "different reviewers must judge this pair before it can be used.",
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
        annotation = {
            "kind": "visual_change",
            "source": "independent_blind_human_judgments_in_agreement",
            "note": (
                "What at least two reviewers independently saw, before any machine or gauge "
                "evidence. It is not a gauge measurement and not a flood decision."
            ),
            "earlier_observation": e["observation_key"],
            "later_observation": ls["observation_key"],
            "direction": direction,
            "elapsed_seconds": elapsed,
            "reviewer_count": len(judgments),
            "reviewers": reviewers,
            "judgments": [
                {"reviewer": j.reviewer, "label": j.label, "reviewed_at_utc": j.reviewed_at_utc}
                for j in judgments
            ],
            "blind_judgments_only": True,
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
        "needed": MIN_REVIEWERS,
        "by_direction": {k: sorted(v) for k, v in sorted(by_direction.items())},
        "agree": len(by_direction) == 1 and "cannot_judge" not in by_direction,
    }

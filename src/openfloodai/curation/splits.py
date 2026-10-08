"""Leakage-safe split assignment for a dataset version (Issue #215; compatible with #157/#207).

Neighbouring frames are never split at random. Two policies are supported:

- `site_camera` (default): every camera belongs to exactly one of train, validation or test, as the
  later release story (#207) requires. Fewer than three independent cameras is reported as a
  readiness gap; no split is fabricated to hide it.
- `single_site_time_block`: for a local pilot with one site. Explicit date blocks keep time
  together. It is site-specific evaluation only: it says nothing about unseen cameras and it does
  not satisfy #207's publication gate, and the manifest says so.

Locked-validation observations can only be in the test split and are never used for tuning.
A temporal pair never straddles a split. Identical image bytes cannot appear in two splits.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from openfloodai.curation.common import SPLITS, CurationError, reason

POLICY_SITE_CAMERA = "site_camera"
POLICY_TIME_BLOCK = "single_site_time_block"
POLICIES = (POLICY_SITE_CAMERA, POLICY_TIME_BLOCK)
POLICY_VERSION = 1


def default_policy() -> dict[str, Any]:
    return {"kind": POLICY_SITE_CAMERA, "version": POLICY_VERSION, "assignments": {}}


def validate_policy(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CurationError("The split policy must be an object.")
    kind = raw.get("kind")
    if kind == POLICY_SITE_CAMERA:
        assignments = raw.get("assignments") or {}
        if not isinstance(assignments, dict):
            raise CurationError("Camera assignments must be an object.")
        for camera, split in assignments.items():
            if split not in SPLITS:
                raise CurationError(f"{camera}: a split must be one of {', '.join(SPLITS)}.")
        return {"kind": kind, "version": POLICY_VERSION, "assignments": dict(assignments)}
    if kind == POLICY_TIME_BLOCK:
        site_id = raw.get("site_id")
        blocks = raw.get("blocks")
        if (
            not isinstance(site_id, str)
            or not site_id
            or not isinstance(blocks, list)
            or not blocks
        ):
            raise CurationError("A time-block policy needs a site and at least one block.")
        clean: list[dict[str, str]] = []
        for block in blocks:
            if not isinstance(block, dict) or block.get("split") not in SPLITS:
                raise CurationError("Each block needs a split of train, validation or test.")
            start, end = str(block.get("start_date", "")), str(block.get("end_date", ""))
            if not (len(start) == 10 and len(end) == 10 and start <= end):
                raise CurationError(
                    "Each block needs start and end dates as YYYY-MM-DD, start first."
                )
            clean.append({"split": str(block["split"]), "start_date": start, "end_date": end})
        ordered = sorted(clean, key=lambda b: b["start_date"])
        for first, second in zip(ordered, ordered[1:], strict=False):
            if second["start_date"] <= first["end_date"]:
                raise CurationError("Time blocks must not overlap.")
        return {"kind": kind, "version": POLICY_VERSION, "site_id": site_id, "blocks": ordered}
    raise CurationError(f"The split policy must be one of {', '.join(POLICIES)}.")


def _member_units(member: dict[str, Any]) -> list[dict[str, Any]]:
    """The observation snapshots a member is made of (one, or two for a pair)."""

    if member["kind"] == "pair":
        return [member["snapshots"]["earlier"], member["snapshots"]["later"]]
    return [member["snapshot"]]


def assign_splits(
    policy: dict[str, Any], members: list[dict[str, Any]]
) -> tuple[dict[str, str], list[dict[str, str]], list[dict[str, str]]]:
    """(member_id -> split, blocking problems, readiness gaps)."""

    assigned: dict[str, str] = {}
    problems: list[dict[str, str]] = []
    gaps: list[dict[str, str]] = []
    for member in members:
        member_id = member["member_id"]
        units = _member_units(member)
        splits: set[str] = set()
        for snap in units:
            split = _split_for(policy, snap)
            if split is None:
                where = (
                    snap["site"]["camera_id"]
                    if policy["kind"] == POLICY_SITE_CAMERA
                    else snap["source"]["captured_at_utc"][:10]
                )
                problems.append(
                    reason(
                        "split_unassigned",
                        f"{member_id}: {where} is not assigned to train, validation or test.",
                    )
                )
            else:
                splits.add(split)
        if len(splits) > 1:
            problems.append(
                reason(
                    "pair_crosses_split",
                    f"{member_id}: the two images of this pair fall in different splits "
                    f"({', '.join(sorted(splits))}). A pair must stay together.",
                )
            )
        elif splits:
            assigned[member_id] = next(iter(splits))
        for snap in units:
            if snap["dataset_group"] == "locked_validation" and assigned.get(member_id) not in (
                None,
                "test",
            ):
                problems.append(
                    reason(
                        "locked_not_test",
                        f"{member_id}: locked-validation data can only be in the test split.",
                    )
                )
    problems += _duplicate_content_problems(members, assigned)
    problems += _locked_camera_problems(policy, members, assigned)
    gaps += _readiness_gaps(policy, members, assigned)
    return assigned, problems, gaps


def _split_for(policy: dict[str, Any], snap: dict[str, Any]) -> str | None:
    if policy["kind"] == POLICY_SITE_CAMERA:
        return str(policy["assignments"].get(snap["site"]["camera_id"]) or "") or None
    if snap["site"]["site_id"] != policy["site_id"]:
        return None
    day = snap["source"]["captured_at_utc"][:10]
    for block in policy["blocks"]:
        if block["start_date"] <= day <= block["end_date"]:
            return str(block["split"])
    return None


def _duplicate_content_problems(
    members: list[dict[str, Any]], assigned: dict[str, str]
) -> list[dict[str, str]]:
    by_sha: dict[str, set[str]] = defaultdict(set)
    for member in members:
        split = assigned.get(member["member_id"])
        if split is None:
            continue
        for snap in _member_units(member):
            by_sha[snap["image"]["sha256"]].add(split)
    return [
        reason(
            "duplicate_content_across_splits",
            f"Identical image content appears in more than one split "
            f"({', '.join(sorted(splits))}).",
        )
        for splits in by_sha.values()
        if len(splits) > 1
    ]


def _locked_camera_problems(
    policy: dict[str, Any], members: list[dict[str, Any]], assigned: dict[str, str]
) -> list[dict[str, str]]:
    """A camera with locked data is a test camera; its other data would leak across the boundary."""

    if policy["kind"] != POLICY_SITE_CAMERA:
        return []
    locked_cameras: set[str] = set()
    for member in members:
        for snap in _member_units(member):
            if snap["dataset_group"] == "locked_validation":
                locked_cameras.add(snap["site"]["camera_id"])
    problems = []
    for member in members:
        for snap in _member_units(member):
            camera = snap["site"]["camera_id"]
            if camera in locked_cameras and assigned.get(member["member_id"]) not in (None, "test"):
                problems.append(
                    reason(
                        "locked_camera_leak",
                        f"{camera} has locked-validation data, so all of its examples must be in "
                        "test.",
                    )
                )
    return problems


def _readiness_gaps(
    policy: dict[str, Any], members: list[dict[str, Any]], assigned: dict[str, str]
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    if policy["kind"] == POLICY_TIME_BLOCK:
        gaps.append(
            reason(
                "site_specific_evaluation_only",
                "This split is by time blocks within one site. It supports site-specific "
                "evaluation only, says nothing about unseen cameras, and does not meet the "
                "site/camera-isolated publication rule.",
                "warning",
            )
        )
        return gaps
    cameras: dict[str, set[str]] = defaultdict(set)
    for member in members:
        split = assigned.get(member["member_id"])
        if split:
            for snap in _member_units(member):
                cameras[split].add(snap["site"]["camera_id"])
    missing = [s for s in SPLITS if not cameras.get(s)]
    if missing:
        gaps.append(
            reason(
                "insufficient_independent_cameras",
                f"No camera is assigned to: {', '.join(missing)}. A site/camera-isolated release "
                "needs different cameras in train, validation and test. This is a readiness gap, "
                "not something to hide with a random split.",
                "warning",
            )
        )
    return gaps

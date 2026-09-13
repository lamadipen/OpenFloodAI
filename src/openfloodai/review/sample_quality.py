"""Riverbank/reference quality derivation for human-reviewed validation samples.

See docs/architecture/data-contracts.md "Riverbank/Reference Quality Checks on
Validation Samples (Issue #164)" for the field contract this module derives from.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

FAILURE_RIVERBANK_NOT_VISIBLE = "riverbank_not_visible"
FAILURE_OBSTRUCTED_VIEW = "obstructed_view"
FAILURE_CAMERA_MOVED = "camera_moved"
FAILURE_WATER_BOUNDARY_UNCLEAR = "water_boundary_unclear"
FAILURE_POOR_VISIBILITY = "poor_visibility"
FAILURE_BASELINE_NOT_CONFIRMED = "baseline_not_confirmed"

ALLOWED_FAILURE_REASONS = {
    FAILURE_RIVERBANK_NOT_VISIBLE,
    FAILURE_OBSTRUCTED_VIEW,
    FAILURE_CAMERA_MOVED,
    FAILURE_WATER_BOUNDARY_UNCLEAR,
    FAILURE_POOR_VISIBILITY,
    FAILURE_BASELINE_NOT_CONFIRMED,
}

_POOR_VISIBILITY_CONDITIONS = {"dark", "glare", "rain", "fog", "blur"}

FRIENDLY_FAILURE_REASONS: dict[str, str] = {
    FAILURE_RIVERBANK_NOT_VISIBLE: (
        "The riverbank or stable reference is not visible in this sample."
    ),
    FAILURE_OBSTRUCTED_VIEW: "Something is blocking the camera's view in this sample.",
    FAILURE_CAMERA_MOVED: "The camera does not appear stable in this sample.",
    FAILURE_WATER_BOUNDARY_UNCLEAR: (
        "The water boundary is not clear enough to judge in this sample."
    ),
    FAILURE_POOR_VISIBILITY: (
        "Visibility conditions (dark, glare, rain, fog, or blur) limit this sample."
    ),
    FAILURE_BASELINE_NOT_CONFIRMED: (
        "The site does not yet have a confirmed normal-condition riverbank reference."
    ),
}


def is_normal_baseline_confirmed(confirmed_reference: Mapping[str, Any] | None) -> bool:
    """Return whether the site has a confirmed, normal-condition OF-082 reference.

    Both conditions matter: a reference with status "confirmed" but
    normal_condition False was not drawn from normal-condition footage, so it
    is not a trustworthy baseline to compare against.
    """

    if confirmed_reference is None:
        return False
    return (
        confirmed_reference.get("status") == "confirmed"
        and confirmed_reference.get("normal_condition") is True
    )


def compute_failure_reason(
    record: Mapping[str, object],
    confirmed_reference: Mapping[str, Any] | None,
) -> str | None:
    """Return why this sample cannot support riverbank comparison, or None.

    Checked in a fixed priority order; the first matching problem wins. An
    explicit "no" always beats "unsure" or a missing answer: unsure/absent
    fields are never treated as a failure by themselves, so a sample is not
    penalized just because a reviewer wasn't certain about every question.
    """

    if record.get("riverbank_visible") == "no":
        return FAILURE_RIVERBANK_NOT_VISIBLE
    if record.get("visibility_condition") == "obstruction":
        return FAILURE_OBSTRUCTED_VIEW
    if record.get("camera_stable") == "no":
        return FAILURE_CAMERA_MOVED
    if record.get("water_boundary_visible") == "no":
        return FAILURE_WATER_BOUNDARY_UNCLEAR
    if record.get("visibility_condition") in _POOR_VISIBILITY_CONDITIONS:
        return FAILURE_POOR_VISIBILITY
    if not is_normal_baseline_confirmed(confirmed_reference):
        return FAILURE_BASELINE_NOT_CONFIRMED
    return None


def friendly_failure_reason(reason: str | None) -> str:
    """Return a plain-language sentence for a failure reason code."""

    if reason is None:
        return "No reference-quality issue was recorded."
    return FRIENDLY_FAILURE_REASONS.get(reason, reason)


def is_baseline_ready(
    record: Mapping[str, object],
    confirmed_reference: Mapping[str, Any] | None,
) -> bool:
    """Return whether this sample is trustworthy enough for real comparison.

    A missing failure reason alone is too loose a bar: a record where every
    quality question was answered "unsure" would have no failure reason, but
    that is not the same as being confirmed good. Baseline-ready additionally
    requires an explicit "yes" on the two fields that directly define whether
    the riverbank can be compared against: riverbank_visible and
    water_boundary_visible. stable_marker_visible is extra, optional evidence
    (a pillar, rock, or similar) rather than a requirement, so it never
    affects baseline_ready or failure_reason regardless of its value; camera_stable
    may also stay "unsure" and still count, matching the issue's instruction
    not to require perfect conditions for every sample.
    """

    if compute_failure_reason(record, confirmed_reference) is not None:
        return False
    return (
        record.get("riverbank_visible") == "yes" and record.get("water_boundary_visible") == "yes"
    )


@dataclass(frozen=True)
class SampleQualitySummary:
    """Plain-language summary of reference quality across a set of samples."""

    total_samples: int
    baseline_ready_count: int
    practice_only_count: int
    failure_reason_counts: list[tuple[str, int]]


def summarize_sample_quality(
    records: Iterable[Mapping[str, object]],
    confirmed_reference: Mapping[str, Any] | None,
) -> SampleQualitySummary:
    """Summarize baseline-ready vs practice-only counts across samples."""

    records = list(records)
    baseline_ready_count = 0
    reason_counts: Counter[str] = Counter()

    for record in records:
        if is_baseline_ready(record, confirmed_reference):
            baseline_ready_count += 1
            continue
        reason = compute_failure_reason(record, confirmed_reference)
        if reason is not None:
            reason_counts[reason] += 1

    total_samples = len(records)
    practice_only_count = total_samples - baseline_ready_count
    failure_reason_counts = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))

    return SampleQualitySummary(
        total_samples=total_samples,
        baseline_ready_count=baseline_ready_count,
        practice_only_count=practice_only_count,
        failure_reason_counts=failure_reason_counts,
    )

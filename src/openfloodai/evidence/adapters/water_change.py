"""The mask-based water-change Observation adapter (Issue #222).

Measures how the VISIBLE water area changed between an explicitly ordered pair of images, from two
human-accepted water masks and one fixed watched area (see ``vision/water_change.py`` for the exact
definitions). It is evidence for human review: not flood detection, not physical water height and
not flow speed. Raw brightness never enters the calculation, so riverbank_crossing_v1 (which
measures pixel appearance change) keeps its own honest meaning and is not replaced or relabelled.

Anything missing, rejected, unreviewed, misaligned or unmeasurable becomes an unavailable/invalid
record with reason codes. It is never reported as zero change. Framing is confirmed by a named
person for this pilot; no automatic camera alignment is performed or claimed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openfloodai.evidence.contract import (
    EvidenceRecord,
    build_evidence_record,
    build_unavailable_evidence,
)
from openfloodai.vision.water_change import (
    CALCULATION_VERSION,
    MaskArray,
    Roi,
    WaterChangeInputError,
    measure_water_change,
)

PLUGIN_ID = "water_change_mask_v1"
PLUGIN_VERSION = "1.0.0"
PLUGIN_FAMILY = "observation"
EVIDENCE_TYPE = "water_coverage_change"
UNITS = "percentage_points"

REASON_INCREASED = "COVERAGE_INCREASED"
REASON_DECREASED = "COVERAGE_DECREASED"
REASON_UNCHANGED = "COVERAGE_UNCHANGED"
REASON_FRAMING_NOT_CONFIRMED = "FRAMING_NOT_CONFIRMED"
REASON_ALIGNMENT_NOT_AUTOMATIC = "ALIGNMENT_NOT_VERIFIED_AUTOMATICALLY"


@dataclass(frozen=True)
class WaterChangeEndpoint:
    """One image of the pair: when it was taken, its accepted water mask and where that came from.

    ``mask`` is ``None`` when no accepted water mask exists. ``details`` holds the frozen
    identifiers (image/mask hashes, run and result ids, review decision) copied into provenance.
    """

    captured_at_utc: str
    mask: MaskArray | None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WaterChangeInputs:
    site_id: str
    camera_id: str
    earlier: WaterChangeEndpoint
    later: WaterChangeEndpoint
    roi: Roi | None
    image_size: tuple[int, int] | None  # (width, height)
    framing_confirmed_by: str | None = None
    # Reasons found while resolving the pair (e.g. no accepted mask). Any of these means the
    # pair is unavailable; they are never turned into a measurement.
    blocking_reasons: tuple[str, ...] = ()
    # "invalid" when the resolver found inconsistent inputs (e.g. a different watched area),
    # "unavailable" when evidence is merely missing or not yet accepted.
    blocking_status: str = "unavailable"
    provenance: Mapping[str, Any] = field(default_factory=dict)


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class WaterChangeObservationAdapter:
    """Observation-family adapter over ``measure_water_change`` for one ordered pair."""

    plugin_id = PLUGIN_ID
    plugin_version = PLUGIN_VERSION
    plugin_family = PLUGIN_FAMILY

    def __init__(self, inputs: WaterChangeInputs) -> None:
        self._inputs = inputs

    @property
    def site_id(self) -> str:
        return self._inputs.site_id

    @property
    def camera_id(self) -> str:
        return self._inputs.camera_id

    def _problems(self) -> tuple[str, tuple[str, ...]]:
        """The worst status and every reason that stops a measurement, or ("", ())."""

        inputs = self._inputs
        reasons: list[str] = list(inputs.blocking_reasons)
        status = inputs.blocking_status
        if not inputs.framing_confirmed_by:
            reasons.append(REASON_FRAMING_NOT_CONFIRMED)
        earlier_time = _parse(inputs.earlier.captured_at_utc)
        later_time = _parse(inputs.later.captured_at_utc)
        if earlier_time is None or later_time is None:
            # Already explained when the resolver could not read an image at all.
            if not inputs.blocking_reasons:
                reasons.append("TIMESTAMP_INVALID")
                status = "invalid"
        elif earlier_time == later_time:
            reasons.append("TIMESTAMPS_EQUAL")
            status = "invalid"
        elif earlier_time > later_time:
            reasons.append("TIMESTAMPS_REVERSED")
            status = "invalid"
        if inputs.earlier.mask is None:
            reasons.append("EARLIER_MASK_MISSING")
        if inputs.later.mask is None:
            reasons.append("LATER_MASK_MISSING")
        if inputs.roi is None or inputs.image_size is None:
            reasons.append("INVALID_WATCHED_AREA")
            status = "invalid"
        return (status if reasons else ""), tuple(dict.fromkeys(reasons))

    def check_ready(self) -> tuple[bool, str]:
        _, reasons = self._problems()
        if reasons:
            return False, ", ".join(reasons)
        return True, "two accepted water masks and a confirmed fixed watched area"

    def collect(self) -> EvidenceRecord:
        inputs = self._inputs
        status, reasons = self._problems()
        if reasons:
            return self._unavailable(status, reasons)
        assert inputs.roi is not None and inputs.image_size is not None
        earlier_time = _parse(inputs.earlier.captured_at_utc)
        later_time = _parse(inputs.later.captured_at_utc)
        assert earlier_time is not None and later_time is not None
        elapsed = (later_time - earlier_time).total_seconds()
        try:
            change = measure_water_change(
                inputs.earlier.mask,
                inputs.later.mask,
                inputs.roi,
                inputs.image_size,
                elapsed_seconds=elapsed,
            )
        except WaterChangeInputError as error:
            return self._unavailable("invalid", (error.code,))

        delta = change.delta_percentage_points
        direction = (
            REASON_INCREASED if delta > 0 else REASON_DECREASED if delta < 0 else REASON_UNCHANGED
        )
        return build_evidence_record(
            plugin_id=PLUGIN_ID,
            plugin_version=PLUGIN_VERSION,
            plugin_family=PLUGIN_FAMILY,
            site_id=inputs.site_id,
            camera_id=inputs.camera_id,
            timestamp=inputs.later.captured_at_utc,
            window_start=inputs.earlier.captured_at_utc,
            window_end=inputs.later.captured_at_utc,
            evidence_type=EVIDENCE_TYPE,
            status="available",
            value=delta,
            units=UNITS,
            quality={
                "alignment_status": "confirmed_by_person",
                "framing_confirmed_by": inputs.framing_confirmed_by,
                "measurement": change.to_dict(),
                "roi_px": inputs.roi.to_list(),
                "image_size": list(inputs.image_size),
            },
            reason_codes=(direction, REASON_ALIGNMENT_NOT_AUTOMATIC),
            provenance={
                "calculation_version": CALCULATION_VERSION,
                "earlier": dict(inputs.earlier.details),
                "later": dict(inputs.later.details),
                **dict(inputs.provenance),
            },
        )

    def _unavailable(self, status: str, reasons: tuple[str, ...]) -> EvidenceRecord:
        inputs = self._inputs
        later_time = _parse(inputs.later.captured_at_utc)
        return build_unavailable_evidence(
            plugin_id=PLUGIN_ID,
            plugin_version=PLUGIN_VERSION,
            plugin_family=PLUGIN_FAMILY,
            site_id=inputs.site_id,
            camera_id=inputs.camera_id,
            evidence_type=EVIDENCE_TYPE,
            status=status,
            reason_codes=reasons,
            timestamp=inputs.later.captured_at_utc if later_time is not None else None,
            provenance={
                "calculation_version": CALCULATION_VERSION,
                "earlier": dict(inputs.earlier.details),
                "later": dict(inputs.later.details),
                **dict(inputs.provenance),
            },
        )

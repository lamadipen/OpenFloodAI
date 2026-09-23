"""The common evidence envelope from docs/architecture/plugin-evidence-architecture.md.

One shape every Observation/Quality/Context plugin's output is wrapped in,
so the core pipeline can consume plugins uniformly instead of reading each
one's raw output by hardcoded field name. Enforces the doc's central
invariant: missing evidence is not normal evidence -- an envelope whose
status isn't "available" can never carry a fabricated value or confidence.

Validation lives in EvidenceRecord.__post_init__, not just in the
build_* helpers below, so it applies no matter how a record is
constructed -- a caller cannot bypass the contract by calling the
dataclass directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

PLUGIN_FAMILIES = frozenset({"observation", "quality", "context"})
EVIDENCE_STATUSES = frozenset(
    {"available", "disabled", "unavailable", "failed", "stale", "invalid"}
)


class EvidenceContractError(ValueError):
    """Raised when an evidence record does not satisfy the common contract."""


def _require_non_empty(value: str, field_name: str) -> None:
    if not value:
        raise EvidenceContractError(f"{field_name} must be non-empty")


def _require_timezone_aware(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise EvidenceContractError(
            f"{field_name} must be an ISO 8601 datetime, got {value!r}"
        ) from error
    if parsed.tzinfo is None:
        raise EvidenceContractError(
            f"{field_name} must include an explicit time zone, got {value!r}"
        )
    return parsed


@dataclass(frozen=True)
class EvidenceRecord:
    """One plugin's evidence, in the shape the core pipeline consumes uniformly."""

    plugin_id: str
    plugin_version: str
    plugin_family: str
    site_id: str
    camera_id: str | None
    timestamp: str
    evidence_type: str
    status: str
    value: float | None = None
    units: str | None = None
    confidence: float | None = None
    quality: Mapping[str, object] | None = None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    provenance: Mapping[str, object] | None = None
    window_start: str | None = None
    window_end: str | None = None
    produced_at: str | None = None
    contract_version: str = "v1"
    record_id: str = field(default_factory=lambda: f"evidence-{uuid4()}")
    record_type: str = "evidence_record"

    def __post_init__(self) -> None:
        _require_non_empty(self.plugin_id, "plugin_id")
        _require_non_empty(self.plugin_version, "plugin_version")
        if self.plugin_family not in PLUGIN_FAMILIES:
            raise EvidenceContractError(
                f"plugin_family must be one of {sorted(PLUGIN_FAMILIES)}, "
                f"got {self.plugin_family!r}"
            )
        _require_non_empty(self.site_id, "site_id")
        _require_non_empty(self.evidence_type, "evidence_type")
        if self.status not in EVIDENCE_STATUSES:
            raise EvidenceContractError(
                f"status must be one of {sorted(EVIDENCE_STATUSES)}, got {self.status!r}"
            )

        if self.status == "available":
            if self.value is None:
                raise EvidenceContractError(
                    "status='available' requires a real value -- "
                    "an unavailable/failed/etc. outcome must use status!='available' instead"
                )
        elif self.value is not None or self.confidence is not None:
            raise EvidenceContractError(
                f"status={self.status!r} must not carry a value or confidence "
                "-- missing evidence is not normal evidence, so no measurement may be fabricated"
            )

        _require_non_empty(self.timestamp, "timestamp")
        _require_timezone_aware(self.timestamp, "timestamp")
        if self.produced_at is not None:
            _require_timezone_aware(self.produced_at, "produced_at")

        window_start_dt = (
            _require_timezone_aware(self.window_start, "window_start")
            if self.window_start is not None
            else None
        )
        window_end_dt = (
            _require_timezone_aware(self.window_end, "window_end")
            if self.window_end is not None
            else None
        )
        if (
            window_start_dt is not None
            and window_end_dt is not None
            and window_start_dt > window_end_dt
        ):
            raise EvidenceContractError("window_start must not be after window_end")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dict matching the doc's contract field table."""

        return {
            "contract_version": self.contract_version,
            "record_id": self.record_id,
            "record_type": self.record_type,
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "plugin_family": self.plugin_family,
            "site_id": self.site_id,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "produced_at": self.produced_at,
            "evidence_type": self.evidence_type,
            "value": self.value,
            "units": self.units,
            "status": self.status,
            "confidence": self.confidence,
            "quality": dict(self.quality) if self.quality is not None else None,
            "reason_codes": list(self.reason_codes),
            "provenance": dict(self.provenance) if self.provenance is not None else None,
        }


def build_evidence_record(
    *,
    plugin_id: str,
    plugin_version: str,
    plugin_family: str,
    site_id: str,
    camera_id: str | None,
    timestamp: str,
    evidence_type: str,
    status: str,
    value: float | None = None,
    units: str | None = None,
    confidence: float | None = None,
    quality: Mapping[str, object] | None = None,
    reason_codes: tuple[str, ...] = (),
    provenance: Mapping[str, object] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    produced_at: str | None = None,
) -> EvidenceRecord:
    """Build one evidence envelope. Validation happens in EvidenceRecord itself."""

    return EvidenceRecord(
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        plugin_family=plugin_family,
        site_id=site_id,
        camera_id=camera_id,
        timestamp=timestamp,
        evidence_type=evidence_type,
        status=status,
        value=value,
        units=units,
        confidence=confidence,
        quality=quality,
        reason_codes=tuple(reason_codes),
        provenance=provenance,
        window_start=window_start,
        window_end=window_end,
        produced_at=produced_at or datetime.now(tz=UTC).isoformat(),
    )


def build_unavailable_evidence(
    *,
    plugin_id: str,
    plugin_version: str,
    plugin_family: str,
    site_id: str,
    camera_id: str | None,
    evidence_type: str,
    status: str,
    reason_codes: tuple[str, ...],
    timestamp: str | None = None,
    quality: Mapping[str, object] | None = None,
    provenance: Mapping[str, object] | None = None,
) -> EvidenceRecord:
    """Build a degraded-outcome envelope: identity, status, and reasons -- no measurement.

    Use this whenever a plugin is disabled, times out, or fails, so that
    outcome is distinguishable from a real measurement that happens to be
    zero or "normal". `status` must not be "available".
    """

    if status == "available":
        raise EvidenceContractError(
            "build_unavailable_evidence cannot be used with status='available'; "
            "use build_evidence_record for a real measurement"
        )
    if not reason_codes:
        raise EvidenceContractError(
            "a degraded outcome must carry at least one reason code explaining why"
        )

    now = datetime.now(tz=UTC).isoformat()
    return build_evidence_record(
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        plugin_family=plugin_family,
        site_id=site_id,
        camera_id=camera_id,
        timestamp=timestamp or now,
        evidence_type=evidence_type,
        status=status,
        value=None,
        confidence=None,
        quality=quality,
        reason_codes=reason_codes,
        provenance=provenance,
        produced_at=now,
    )

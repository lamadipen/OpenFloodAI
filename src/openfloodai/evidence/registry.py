"""Minimal capability discovery over a fixed, explicit list of evidence adapters.

Per the doc: "Begin with an explicit local list of known adapters" rather
than a generic auto-discovering plugin registry, and "catch a plugin's
failure at its boundary" so one broken adapter never takes others down with
it. Callers pass in whatever adapters they've explicitly constructed --
there is no scanning, loading, or dynamic registration here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from openfloodai.evidence.contract import EvidenceRecord, build_unavailable_evidence


@runtime_checkable
class EvidenceAdapter(Protocol):
    """The uniform shape every Observation/Quality/Context adapter exposes."""

    plugin_id: str
    plugin_version: str
    plugin_family: str

    def check_ready(self) -> tuple[bool, str]:
        """Return (ready, reason) without doing the actual collection work."""
        ...

    def collect(self) -> EvidenceRecord:
        """Return one EvidenceRecord for this adapter's configured input."""
        ...


@dataclass(frozen=True)
class CapabilityStatus:
    """One adapter's discovered readiness, independent of the others."""

    plugin_id: str
    plugin_family: str
    ready: bool
    reason: str


def check_capabilities(adapters: Sequence[EvidenceAdapter]) -> list[CapabilityStatus]:
    """Report each adapter's readiness, isolating one adapter's failure from the rest."""

    statuses: list[CapabilityStatus] = []
    for adapter in adapters:
        try:
            ready, reason = adapter.check_ready()
        except Exception as error:  # noqa: BLE001 -- an adapter's own bug must not propagate
            ready, reason = False, f"check_ready raised {type(error).__name__}: {error}"
        statuses.append(
            CapabilityStatus(
                plugin_id=adapter.plugin_id,
                plugin_family=adapter.plugin_family,
                ready=ready,
                reason=reason,
            )
        )
    return statuses


def collect_evidence(adapters: Sequence[EvidenceAdapter]) -> list[EvidenceRecord]:
    """Collect one EvidenceRecord per adapter, in order, isolating adapter failures.

    A raising adapter never stops the others: it's converted into a
    status="failed" envelope carrying the exception as a reason code, so
    the caller still gets one record per adapter, never a missing one that
    could be mistaken for silently-normal.
    """

    records: list[EvidenceRecord] = []
    for adapter in adapters:
        try:
            records.append(adapter.collect())
        except Exception as error:  # noqa: BLE001 -- isolate this adapter's failure
            records.append(
                build_unavailable_evidence(
                    plugin_id=adapter.plugin_id,
                    plugin_version=adapter.plugin_version,
                    plugin_family=adapter.plugin_family,
                    site_id=getattr(adapter, "site_id", None) or "unknown",
                    camera_id=getattr(adapter, "camera_id", None),
                    evidence_type="adapter_collection_failure",
                    status="failed",
                    reason_codes=(f"ADAPTER_RAISED_{type(error).__name__}",),
                )
            )
    return records

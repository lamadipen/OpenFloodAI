"""Minimal capability discovery over a fixed, explicit list of evidence adapters.

Per the doc: "Begin with an explicit local list of known adapters" rather
than a generic auto-discovering plugin registry, and "catch a plugin's
failure at its boundary" so one broken adapter never takes others down with
it. Callers pass in whatever adapters they've explicitly constructed --
there is no scanning, loading, or dynamic registration here.

Every per-adapter step below -- reading metadata, calling check_ready(),
calling collect(), and building the failure fallback record -- is wrapped
so a single malformed adapter can never stop the adapters after it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from openfloodai.evidence.contract import (
    PLUGIN_FAMILIES,
    EvidenceContractError,
    EvidenceRecord,
    build_unavailable_evidence,
)

_UNKNOWN = "unknown"


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


def _safe_str_attr(adapter: object, name: str) -> str:
    """Read a string attribute off an adapter, never raising."""

    try:
        value = getattr(adapter, name, None)
    except Exception:  # noqa: BLE001 -- a property getter's own bug must not propagate
        return _UNKNOWN
    return value if isinstance(value, str) and value else _UNKNOWN


def _check_one_capability(adapter: EvidenceAdapter) -> CapabilityStatus:
    """Report one adapter's readiness. Never raises, regardless of adapter behavior."""

    plugin_id = _safe_str_attr(adapter, "plugin_id")
    plugin_family = _safe_str_attr(adapter, "plugin_family")
    try:
        ready, reason = adapter.check_ready()
    except Exception as error:  # noqa: BLE001 -- an adapter's own bug must not propagate
        return CapabilityStatus(
            plugin_id=plugin_id,
            plugin_family=plugin_family,
            ready=False,
            reason=f"check_ready raised {type(error).__name__}: {error}",
        )
    return CapabilityStatus(
        plugin_id=plugin_id, plugin_family=plugin_family, ready=ready, reason=reason
    )


def check_capabilities(adapters: Sequence[EvidenceAdapter]) -> list[CapabilityStatus]:
    """Report each adapter's readiness, isolating one adapter's failure from the rest."""

    return [_check_one_capability(adapter) for adapter in adapters]


def _failed_evidence_fallback(adapter: EvidenceAdapter, error: Exception) -> EvidenceRecord:
    """Build a status="failed" envelope for a raising adapter. Never raises itself.

    Adapter metadata is read defensively and, if it turns out to be
    invalid (e.g. an unknown plugin_family), falls back to the most
    minimal values that are always valid under the contract -- so a
    malformed adapter's metadata can never stop this from producing a
    record for it, or block the adapters after it.
    """

    plugin_id = _safe_str_attr(adapter, "plugin_id")
    plugin_version = _safe_str_attr(adapter, "plugin_version")
    plugin_family = _safe_str_attr(adapter, "plugin_family")
    if plugin_family not in PLUGIN_FAMILIES:
        plugin_family = "observation"
    site_id = _safe_str_attr(adapter, "site_id")
    camera_id = getattr(adapter, "camera_id", None)
    if not isinstance(camera_id, str):
        camera_id = None
    reason_codes = (f"ADAPTER_RAISED_{type(error).__name__}",)

    try:
        return build_unavailable_evidence(
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            plugin_family=plugin_family,
            site_id=site_id,
            camera_id=camera_id,
            evidence_type="adapter_collection_failure",
            status="failed",
            reason_codes=reason_codes,
        )
    except EvidenceContractError:
        # Metadata that looked plausible still failed validation (e.g. an
        # empty string _safe_str_attr couldn't catch). Fall back to values
        # that are always valid under the contract, so this still returns
        # a record instead of raising into the caller's loop.
        return build_unavailable_evidence(
            plugin_id=plugin_id if plugin_id != _UNKNOWN else "unknown-plugin",
            plugin_version=plugin_version if plugin_version != _UNKNOWN else "0.0.0",
            plugin_family="observation",
            site_id=site_id if site_id != _UNKNOWN else "unknown-site",
            camera_id=None,
            evidence_type="adapter_collection_failure",
            status="failed",
            reason_codes=(*reason_codes, "ADAPTER_METADATA_INVALID"),
        )


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
            records.append(_failed_evidence_fallback(adapter, error))
    return records

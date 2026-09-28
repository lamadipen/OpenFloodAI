"""Modular evidence and plugin architecture (docs/architecture/plugin-evidence-architecture.md).

This package is additive: nothing here changes the existing pipeline's
behavior or saved-record formats. It defines the common evidence envelope
and the smallest adapter needed to prove it, per the doc's own instruction
not to build a large generic plugin framework up front.
"""

from openfloodai.evidence.catalog import KNOWN_ADAPTERS, AdapterDescriptor
from openfloodai.evidence.contract import (
    EVIDENCE_STATUSES,
    PLUGIN_FAMILIES,
    EvidenceContractError,
    EvidenceRecord,
    build_evidence_record,
    build_unavailable_evidence,
)
from openfloodai.evidence.registry import (
    CapabilityStatus,
    check_capabilities,
    collect_evidence,
)
from openfloodai.evidence.settings import (
    describe_adapters_for_settings_ui,
    resolve_effective_adapter_settings,
    write_global_adapter_setting,
)

__all__ = [
    "EVIDENCE_STATUSES",
    "KNOWN_ADAPTERS",
    "PLUGIN_FAMILIES",
    "AdapterDescriptor",
    "CapabilityStatus",
    "EvidenceContractError",
    "EvidenceRecord",
    "build_evidence_record",
    "build_unavailable_evidence",
    "check_capabilities",
    "collect_evidence",
    "describe_adapters_for_settings_ui",
    "resolve_effective_adapter_settings",
    "write_global_adapter_setting",
]

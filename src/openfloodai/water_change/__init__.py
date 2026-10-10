"""Mask-based water-change measurement over saved site data and the one-camera pilot (Issue #222).

``pair`` resolves two saved, human-accepted water masks into a frozen measurement; ``pilot`` runs
the pre-registered feasibility pilot (criteria written first, independent judgments, report).
"""

from openfloodai.water_change.pair import (
    EndpointRef,
    ResolvedEndpoint,
    measure_pair,
    resolve_endpoint,
)

__all__ = ["EndpointRef", "ResolvedEndpoint", "measure_pair", "resolve_endpoint"]

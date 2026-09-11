"""Configuration helpers for OpenFloodAI."""

from openfloodai.config.region_selection import (
    RegionSelectionError,
    pixel_selection_to_reference_region,
    reference_region_to_dict,
)
from openfloodai.config.site_config import (
    ConfirmedReference,
    ConfirmedReferenceMarker,
    ReferenceRegion,
    SiteCameraConfig,
    SiteConfigError,
    invalidate_confirmed_reference,
    load_site_config,
    write_confirmed_reference,
    write_reference_region,
)

__all__ = [
    "ConfirmedReference",
    "ConfirmedReferenceMarker",
    "ReferenceRegion",
    "RegionSelectionError",
    "SiteCameraConfig",
    "SiteConfigError",
    "invalidate_confirmed_reference",
    "load_site_config",
    "pixel_selection_to_reference_region",
    "reference_region_to_dict",
    "write_confirmed_reference",
    "write_reference_region",
]

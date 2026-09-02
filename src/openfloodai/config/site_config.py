"""Site and camera configuration -- re-exports from the unified config.

All site configuration is now defined in :mod:`openfloodai.common.site_config`.
This module re-exports the public symbols so existing ``from openfloodai.config``
imports continue to work.
"""

from openfloodai.common.site_config import (
    InputType,
    ReferenceRegion,
    SiteConfig,
    SiteConfigError,
    load_site_config,
)

__all__ = [
    "InputType",
    "ReferenceRegion",
    "SiteConfig",
    "SiteConfigError",
    "load_site_config",
]

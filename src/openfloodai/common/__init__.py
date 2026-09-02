"""Shared OpenFloodAI utilities and types."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from openfloodai.common.site_config import (
    InputType,
    ReferenceRegion,
    SiteConfig,
    SiteConfigError,
    find_site,
    load_site_config,
    save_site_config,
)

FrameArray = NDArray[np.generic]

__all__ = [
    "FrameArray",
    "InputType",
    "ReferenceRegion",
    "SiteConfig",
    "SiteConfigError",
    "find_site",
    "load_site_config",
    "save_site_config",
]

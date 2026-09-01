"""Shared OpenFloodAI utilities and types."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FrameArray = NDArray[np.generic]

__all__ = ["FrameArray"]

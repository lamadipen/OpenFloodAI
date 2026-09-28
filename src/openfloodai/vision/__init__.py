"""Camera and vision components for OpenFloodAI."""

from openfloodai.vision.simple_signals import (
    VisualSignalError,
    compare_frames,
    compare_region_signals,
    extract_frame_signals,
    extract_region_signals,
    patch_change_score,
)

__all__ = [
    "VisualSignalError",
    "compare_frames",
    "compare_region_signals",
    "extract_frame_signals",
    "extract_region_signals",
    "patch_change_score",
]

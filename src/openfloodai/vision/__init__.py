"""Camera and vision components for OpenFloodAI."""

from openfloodai.vision.simple_signals import (
    VisualSignalError,
    compare_frames,
    extract_frame_signals,
)

__all__ = ["VisualSignalError", "compare_frames", "extract_frame_signals"]

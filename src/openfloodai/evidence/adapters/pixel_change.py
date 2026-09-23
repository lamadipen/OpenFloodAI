"""The first Observation adapter: wraps the existing pixel-change comparison.

Per the doc, "the existing pixel change measurement is the first adapter
candidate" for proving the evidence envelope shape. This module calls
openfloodai.vision.simple_signals.compare_region_signals exactly as
image_sequence_runner.py already does -- it does not change that function,
its output, or its current caller. It only wraps the same output in the
common EvidenceRecord envelope for a future consumer that wants a list of
uniform envelopes instead of raw dicts.
"""

from __future__ import annotations

from openfloodai.evidence.contract import EvidenceRecord, build_evidence_record
from openfloodai.vision.simple_signals import (
    FrameArray,
    ReferenceRegionInput,
    compare_region_signals,
)

PLUGIN_ID = "pixel_change_region_v1"
PLUGIN_VERSION = "1.0.0"
PLUGIN_FAMILY = "observation"


class PixelChangeObservationAdapter:
    """Observation-family adapter over compare_region_signals for one frame pair."""

    plugin_id = PLUGIN_ID
    plugin_version = PLUGIN_VERSION
    plugin_family = PLUGIN_FAMILY

    def __init__(
        self,
        *,
        site_id: str,
        camera_id: str,
        reference_region: ReferenceRegionInput,
        previous_frame: FrameArray,
        current_frame: FrameArray,
        timestamp: str | None = None,
    ) -> None:
        self.site_id = site_id
        self.camera_id = camera_id
        self._reference_region = reference_region
        self._previous_frame = previous_frame
        self._current_frame = current_frame
        self._timestamp = timestamp

    def check_ready(self) -> tuple[bool, str]:
        return True, "pixel-change region comparison has no external dependency"

    def collect(self) -> EvidenceRecord:
        signal = compare_region_signals(
            self._previous_frame,
            self._current_frame,
            self._reference_region,
            self.site_id,
            self.camera_id,
            timestamp=self._timestamp,
        )
        return build_evidence_record(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            plugin_family=self.plugin_family,
            site_id=self.site_id,
            camera_id=self.camera_id,
            timestamp=str(signal["timestamp"]),
            evidence_type="region_pixel_change_score",
            status="available",
            value=float(signal["region_change_score"]),  # type: ignore[arg-type]
            units="normalized_change_ratio",
            quality={
                "region_brightness_score": signal["region_brightness_score"],
                "region_sharpness_score": signal["region_sharpness_score"],
            },
            reason_codes=(str(signal["water_level_evidence_state"]),),
            provenance={
                "source_function": "openfloodai.vision.simple_signals.compare_region_signals",
                "source_record_id": signal["record_id"],
            },
        )


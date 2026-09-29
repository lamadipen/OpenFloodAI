"""The riverbank-crossing Observation adapter (Issue #200 / OF-088).

Wraps `openfloodai.vision.riverbank_crossing.evaluate_riverbank_crossing` in
the common EvidenceRecord envelope. Unevaluated against the human-reviewed
pilot yet, so it ships registered but disabled by default (see
evidence/catalog.py) -- per the issue, its score must not be fused into any
decision until that evaluation shows measurable improvement over the
existing pixel-change baseline.

No camera alignment is performed anywhere in this codebase yet, so every
"available" result here also carries a CAMERA_ALIGNMENT_UNAVAILABLE reason
code alongside the real measurement -- a deliberately degraded, not
fabricated, outcome. See the vision module's own docstring for why.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime

from openfloodai.evidence.contract import (
    EvidenceRecord,
    build_evidence_record,
    build_unavailable_evidence,
)
from openfloodai.vision.riverbank_crossing import (
    DEFAULT_BAND_WIDTH_PX,
    DEFAULT_CROSSING_THRESHOLD,
    DEFAULT_MAX_SEARCH_PIXELS,
    DEFAULT_SAMPLE_COUNT,
    DEFAULT_SEARCH_STEP_PIXELS,
    RiverbankCrossingError,
    WaterlinePointInput,
    evaluate_riverbank_crossing,
)
from openfloodai.vision.simple_signals import FrameArray, ReferenceRegionInput

PLUGIN_ID = "riverbank_crossing_v1"
PLUGIN_VERSION = "1.0.0"
PLUGIN_FAMILY = "observation"
# The algorithm only measures land-side PIXEL change; it never identifies the
# changed substance as water (vegetation, snow, a person, or shadow can all
# trigger this). Named accordingly -- never "POSSIBLE_WATER_..." -- until a
# separate adapter supplies real water evidence.
REASON_POSSIBLE_VISUAL_CHANGE = "POSSIBLE_VISUAL_CHANGE_BEYOND_NORMAL_LINE"
REASON_NO_CLEAR_CROSSING = "NO_CLEAR_CROSSING"


def _guide_fingerprint(
    guide_points: tuple[Mapping[str, object], ...], water_side_point: Mapping[str, object] | None
) -> str:
    """A short, deterministic fingerprint of the exact geometry a run used.

    Lets a historical run's evidence be traced back to the guide/config
    version that produced it, even after the guide is later edited.
    """

    payload = json.dumps(
        {"points": guide_points, "water_side_point": water_side_point}, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _point_to_plain_dict(point: WaterlinePointInput) -> dict[str, float]:
    if isinstance(point, Mapping):
        return {"x": float(point["x"]), "y": float(point["y"])}  # type: ignore[arg-type]
    return {"x": float(point.x), "y": float(point.y)}


class RiverbankCrossingObservationAdapter:
    """Observation-family adapter over evaluate_riverbank_crossing for one frame pair.

    Readiness is not enforced by the shared registry (collect_evidence()
    calls collect() unconditionally, see evidence/registry.py), so collect()
    itself always returns a valid, never-fabricated EvidenceRecord for every
    case check_ready() would flag.
    """

    plugin_id = PLUGIN_ID
    plugin_version = PLUGIN_VERSION
    plugin_family = PLUGIN_FAMILY

    def __init__(
        self,
        *,
        site_id: str,
        camera_id: str,
        guide_id: str | None,
        guide_points: tuple[WaterlinePointInput, ...] | None,
        water_side_point: WaterlinePointInput | None,
        reference_region: ReferenceRegionInput,
        previous_frame: FrameArray,
        current_frame: FrameArray,
        timestamp: str | None = None,
        band_width_px: int = DEFAULT_BAND_WIDTH_PX,
        crossing_threshold: float = DEFAULT_CROSSING_THRESHOLD,
        max_search_pixels: int = DEFAULT_MAX_SEARCH_PIXELS,
        search_step_pixels: int = DEFAULT_SEARCH_STEP_PIXELS,
        sample_count: int = DEFAULT_SAMPLE_COUNT,
    ) -> None:
        self.site_id = site_id
        self.camera_id = camera_id
        self._guide_id = guide_id
        self._guide_points = guide_points
        self._water_side_point = water_side_point
        self._reference_region = reference_region
        self._previous_frame = previous_frame
        self._current_frame = current_frame
        self._timestamp = timestamp
        self._band_width_px = band_width_px
        self._crossing_threshold = crossing_threshold
        self._max_search_pixels = max_search_pixels
        self._search_step_pixels = search_step_pixels
        self._sample_count = sample_count

    def check_ready(self) -> tuple[bool, str]:
        if not self._guide_points:
            return False, "no confirmed normal waterline guide"
        if self._water_side_point is None:
            return False, "guide has no water_side_point set"
        if self._previous_frame.shape != self._current_frame.shape:
            return False, "previous and current frames have different shapes"
        return True, "riverbank-crossing geometry has no external dependency"

    def collect(self) -> EvidenceRecord:
        if not self._guide_points:
            return self._unavailable(status="invalid", reason_codes=("GUIDE_MISSING",))
        if self._water_side_point is None:
            return self._unavailable(status="invalid", reason_codes=("WATER_SIDE_NOT_SET",))

        try:
            result = evaluate_riverbank_crossing(
                self._previous_frame,
                self._current_frame,
                self._guide_points,
                self._water_side_point,
                self._reference_region,
                band_width_px=self._band_width_px,
                crossing_threshold=self._crossing_threshold,
                max_search_pixels=self._max_search_pixels,
                search_step_pixels=self._search_step_pixels,
                sample_count=self._sample_count,
            )
        except RiverbankCrossingError as error:
            return self._unavailable(
                status="failed", reason_codes=(f"GEOMETRY_ERROR_{type(error).__name__}",)
            )

        crossing_reason = (
            REASON_POSSIBLE_VISUAL_CHANGE
            if result.crossed_line_percentage > 0
            else REASON_NO_CLEAR_CROSSING
        )
        guide_points_plain = tuple(_point_to_plain_dict(point) for point in self._guide_points)
        water_side_plain = _point_to_plain_dict(self._water_side_point)

        return build_evidence_record(
            plugin_id=PLUGIN_ID,
            plugin_version=PLUGIN_VERSION,
            plugin_family=PLUGIN_FAMILY,
            site_id=self.site_id,
            camera_id=self.camera_id,
            timestamp=self._timestamp or datetime.now(tz=UTC).isoformat(),
            evidence_type="riverbank_crossing_percentage",
            status="available",
            value=result.crossed_line_percentage,
            units="percent",
            quality={
                "alignment_status": "unavailable",
                "changed_bank_length_percentage": result.changed_bank_length_percentage,
                "measured_bank_length_percentage": result.measured_bank_length_percentage,
                "maximum_crossing_pixels": result.maximum_crossing_pixels,
                "band_width_px": result.band_width_px,
                "crossing_threshold": result.crossing_threshold,
                "sample_count": result.sample_count,
                "samples": [asdict(sample) for sample in result.samples],
            },
            reason_codes=(crossing_reason, "CAMERA_ALIGNMENT_UNAVAILABLE"),
            provenance={
                "source_function": (
                    "openfloodai.vision.riverbank_crossing.evaluate_riverbank_crossing"
                ),
                "guide_id": self._guide_id,
                "guide_fingerprint": _guide_fingerprint(guide_points_plain, water_side_plain),
            },
        )

    def _unavailable(self, *, status: str, reason_codes: tuple[str, ...]) -> EvidenceRecord:
        return build_unavailable_evidence(
            plugin_id=PLUGIN_ID,
            plugin_version=PLUGIN_VERSION,
            plugin_family=PLUGIN_FAMILY,
            site_id=self.site_id,
            camera_id=self.camera_id,
            evidence_type="riverbank_crossing_percentage",
            status=status,
            timestamp=self._timestamp,
            reason_codes=reason_codes,
        )

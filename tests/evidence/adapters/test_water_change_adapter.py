"""The water-change adapter wraps measurements in the common evidence contract (Issue #222)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from openfloodai.evidence.adapters.water_change import (
    PLUGIN_ID,
    WaterChangeEndpoint,
    WaterChangeInputs,
    WaterChangeObservationAdapter,
)
from openfloodai.evidence.catalog import KNOWN_ADAPTERS
from openfloodai.vision.water_change import Roi

SIZE = (20, 10)
ROI = Roi(2, 2, 12, 8)
T1 = "2026-01-01T10:00:00+00:00"
T2 = "2026-01-01T12:00:00+00:00"


def wet(x1: int) -> np.ndarray:
    out = np.zeros((SIZE[1], SIZE[0]), dtype=np.uint8)
    out[2:8, 2:x1] = 255
    return out


def inputs(**overrides: object) -> WaterChangeInputs:
    base: dict[str, object] = {
        "site_id": "site-a",
        "camera_id": "CAM_A",
        "earlier": WaterChangeEndpoint(T1, wet(7), {"image_sha256": "a" * 64}),
        "later": WaterChangeEndpoint(T2, wet(10), {"image_sha256": "b" * 64}),
        "roi": ROI,
        "image_size": SIZE,
        "framing_confirmed_by": "Dipen",
    }
    base.update(overrides)
    return WaterChangeInputs(**base)  # type: ignore[arg-type]


def test_available_record_carries_the_measurement_and_frozen_provenance() -> None:
    adapter = WaterChangeObservationAdapter(inputs())
    assert adapter.check_ready()[0]
    record = adapter.collect()
    assert record.status == "available"
    assert record.plugin_id == PLUGIN_ID
    assert record.plugin_family == "observation"
    assert record.units == "percentage_points"
    assert record.value == pytest.approx(30.0)
    assert record.window_start == T1 and record.window_end == T2 and record.timestamp == T2
    assert "COVERAGE_INCREASED" in record.reason_codes
    assert "ALIGNMENT_NOT_VERIFIED_AUTOMATICALLY" in record.reason_codes
    quality: Any = record.quality or {}
    assert quality["measurement"]["change_rate_pp_per_hour"] == pytest.approx(15.0)
    assert quality["measurement"]["denominator"] == "roi_pixels"
    assert quality["framing_confirmed_by"] == "Dipen"
    provenance: Any = record.provenance or {}
    assert provenance["earlier"]["image_sha256"] == "a" * 64
    assert str(provenance["calculation_version"]).startswith("water_change_mask_v1")


def test_decrease_and_unchanged_have_their_own_reason_codes() -> None:
    down = WaterChangeObservationAdapter(
        inputs(earlier=WaterChangeEndpoint(T1, wet(10)), later=WaterChangeEndpoint(T2, wet(7)))
    ).collect()
    assert down.reason_codes[0] == "COVERAGE_DECREASED" and (down.value or 0) < 0
    same = WaterChangeObservationAdapter(
        inputs(earlier=WaterChangeEndpoint(T1, wet(7)), later=WaterChangeEndpoint(T2, wet(7)))
    ).collect()
    assert same.status == "available" and same.value == 0.0
    assert same.reason_codes[0] == "COVERAGE_UNCHANGED"


@pytest.mark.parametrize(
    ("overrides", "code", "status"),
    [
        ({"earlier": WaterChangeEndpoint(T1, None)}, "EARLIER_MASK_MISSING", "unavailable"),
        ({"later": WaterChangeEndpoint(T2, None)}, "LATER_MASK_MISSING", "unavailable"),
        ({"framing_confirmed_by": None}, "FRAMING_NOT_CONFIRMED", "unavailable"),
        ({"framing_confirmed_by": ""}, "FRAMING_NOT_CONFIRMED", "unavailable"),
        (
            {"blocking_reasons": ("EARLIER_MASK_UNREVIEWED",)},
            "EARLIER_MASK_UNREVIEWED",
            "unavailable",
        ),
        ({"roi": None}, "INVALID_WATCHED_AREA", "invalid"),
        (
            {"earlier": WaterChangeEndpoint(T2, wet(7)), "later": WaterChangeEndpoint(T1, wet(10))},
            "TIMESTAMPS_REVERSED",
            "invalid",
        ),
        (
            {"earlier": WaterChangeEndpoint(T1, wet(7)), "later": WaterChangeEndpoint(T1, wet(10))},
            "TIMESTAMPS_EQUAL",
            "invalid",
        ),
        (
            {"earlier": WaterChangeEndpoint("2026-01-01T10:00:00", wet(7))},
            "TIMESTAMP_INVALID",
            "invalid",
        ),
        (
            {"earlier": WaterChangeEndpoint("not a time", wet(7))},
            "TIMESTAMP_INVALID",
            "invalid",
        ),
    ],
)
def test_unmeasurable_pairs_are_unavailable_with_reasons_and_never_zero(
    overrides: dict[str, object], code: str, status: str
) -> None:
    adapter = WaterChangeObservationAdapter(inputs(**overrides))
    ready, why = adapter.check_ready()
    assert not ready and code in why
    record = adapter.collect()
    assert record.status == status
    assert code in record.reason_codes
    assert record.value is None and record.confidence is None


def test_mask_pixels_outside_the_watched_area_are_invalid_not_clipped() -> None:
    outside = np.zeros((SIZE[1], SIZE[0]), dtype=np.uint8)
    outside[0:3, 0:3] = 255
    record = WaterChangeObservationAdapter(inputs(later=WaterChangeEndpoint(T2, outside))).collect()
    assert record.status == "invalid"
    assert "MASK_OUTSIDE_WATCHED_AREA" in record.reason_codes
    assert record.value is None


def test_wrong_size_mask_is_invalid() -> None:
    record = WaterChangeObservationAdapter(
        inputs(later=WaterChangeEndpoint(T2, np.zeros((3, 3), dtype=np.uint8)))
    ).collect()
    assert record.status == "invalid" and "MASK_SIZE_MISMATCH" in record.reason_codes


def test_lighting_changes_cannot_matter_because_only_masks_are_inputs() -> None:
    first = WaterChangeObservationAdapter(inputs()).collect()
    # The adapter has no image input at all: identical masks give identical numbers whatever the
    # frames looked like (a sunset, glare or exposure change leaves the masks unchanged).
    second = WaterChangeObservationAdapter(inputs()).collect()
    assert first.value == second.value
    assert (first.quality or {}).get("measurement") == (second.quality or {}).get("measurement")


def test_adapter_is_registered_but_off_by_default() -> None:
    entry = next(a for a in KNOWN_ADAPTERS if a.plugin_id == PLUGIN_ID)
    assert entry.plugin_family == "observation" and entry.is_default is False

from __future__ import annotations

import numpy as np

from openfloodai.evidence.adapters.riverbank_crossing import (
    RiverbankCrossingObservationAdapter,
)
from openfloodai.evidence.registry import check_capabilities, collect_evidence

GUIDE_POINTS = ({"x": 0, "y": 50}, {"x": 100, "y": 50})
WATER_SIDE_POINT = {"x": 50, "y": 80}
FULL_REGION = {"x": 0, "y": 0, "width": 100, "height": 100}


def two_band_frame(*, changed_band: tuple[int, int] | None = None) -> np.ndarray:
    frame = np.full((100, 100, 3), 200, dtype=np.uint8)
    frame[50:, :, :] = 50
    if changed_band is not None:
        start, end = changed_band
        frame[start:end, :, :] = 50
    return frame


def test_adapter_reports_a_possible_crossing_as_available_evidence() -> None:
    adapter = RiverbankCrossingObservationAdapter(
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        guide_id="left_bank",
        guide_points=GUIDE_POINTS,
        water_side_point=WATER_SIDE_POINT,
        reference_region=FULL_REGION,
        previous_frame=two_band_frame(),
        current_frame=two_band_frame(changed_band=(40, 50)),
        timestamp="2026-06-18T00:00:00+00:00",
    )

    record = adapter.collect()

    assert record.plugin_id == "riverbank_crossing_v1"
    assert record.plugin_family == "observation"
    assert record.status == "available"
    assert record.value is not None and record.value > 0
    assert record.units == "percent"
    assert "POSSIBLE_VISUAL_CHANGE_BEYOND_NORMAL_LINE" in record.reason_codes
    assert "CAMERA_ALIGNMENT_UNAVAILABLE" in record.reason_codes
    assert record.quality is not None
    assert record.quality["alignment_status"] == "unavailable"
    samples = record.quality["samples"]
    assert isinstance(samples, list)
    assert any(sample["crossed"] is True for sample in samples)
    assert all("land_band_x" in sample and "water_band_x" in sample for sample in samples)
    assert record.provenance is not None
    assert record.provenance["guide_id"] == "left_bank"
    assert isinstance(record.provenance["guide_fingerprint"], str)


def test_adapter_reports_no_clear_crossing_when_nothing_changes() -> None:
    adapter = RiverbankCrossingObservationAdapter(
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        guide_id="left_bank",
        guide_points=GUIDE_POINTS,
        water_side_point=WATER_SIDE_POINT,
        reference_region=FULL_REGION,
        previous_frame=two_band_frame(),
        current_frame=two_band_frame(),
    )

    record = adapter.collect()

    assert record.status == "available"
    assert record.value == 0.0
    assert "NO_CLEAR_CROSSING" in record.reason_codes


def test_adapter_is_invalid_without_a_confirmed_guide() -> None:
    adapter = RiverbankCrossingObservationAdapter(
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        guide_id=None,
        guide_points=None,
        water_side_point=None,
        reference_region=FULL_REGION,
        previous_frame=two_band_frame(),
        current_frame=two_band_frame(),
    )

    ready, _ = adapter.check_ready()
    record = adapter.collect()

    assert ready is False
    assert record.status == "invalid"
    assert record.reason_codes == ("GUIDE_MISSING",)
    assert record.value is None


def test_adapter_is_invalid_without_a_water_side_point() -> None:
    adapter = RiverbankCrossingObservationAdapter(
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        guide_id="left_bank",
        guide_points=GUIDE_POINTS,
        water_side_point=None,
        reference_region=FULL_REGION,
        previous_frame=two_band_frame(),
        current_frame=two_band_frame(),
    )

    ready, _ = adapter.check_ready()
    record = adapter.collect()

    assert ready is False
    assert record.status == "invalid"
    assert record.reason_codes == ("WATER_SIDE_NOT_SET",)


def test_adapter_fails_cleanly_on_mismatched_frame_shapes() -> None:
    adapter = RiverbankCrossingObservationAdapter(
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        guide_id="left_bank",
        guide_points=GUIDE_POINTS,
        water_side_point=WATER_SIDE_POINT,
        reference_region=FULL_REGION,
        previous_frame=two_band_frame(),
        current_frame=np.zeros((10, 10, 3), dtype=np.uint8),
    )

    ready, _ = adapter.check_ready()
    record = adapter.collect()

    assert ready is False
    assert record.status == "failed"
    assert record.value is None


def test_adapter_works_through_the_shared_registry_helpers() -> None:
    adapter = RiverbankCrossingObservationAdapter(
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        guide_id="left_bank",
        guide_points=GUIDE_POINTS,
        water_side_point=WATER_SIDE_POINT,
        reference_region=FULL_REGION,
        previous_frame=two_band_frame(),
        current_frame=two_band_frame(changed_band=(40, 50)),
    )

    statuses = check_capabilities([adapter])
    records = collect_evidence([adapter])

    assert statuses[0].ready is True
    assert statuses[0].plugin_id == "riverbank_crossing_v1"
    assert len(records) == 1
    assert records[0].status == "available"

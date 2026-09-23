from __future__ import annotations

import numpy as np

from openfloodai.evidence.adapters.pixel_change import PixelChangeObservationAdapter
from openfloodai.evidence.registry import check_capabilities, collect_evidence

_REGION = {"x": 0, "y": 0, "width": 100, "height": 100}


def test_pixel_change_adapter_wraps_a_real_comparison_into_an_evidence_record() -> None:
    previous_frame = np.zeros((10, 10), dtype=np.uint8)
    current_frame = np.full((10, 10), 255, dtype=np.uint8)

    adapter = PixelChangeObservationAdapter(
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        reference_region=_REGION,
        previous_frame=previous_frame,
        current_frame=current_frame,
        timestamp="2026-06-18T00:00:00+00:00",
    )

    record = adapter.collect()

    assert record.plugin_id == "pixel_change_region_v1"
    assert record.plugin_family == "observation"
    assert record.status == "available"
    assert record.site_id == "site-demo-01"
    assert record.camera_id == "camera-demo-01"
    assert record.evidence_type == "region_pixel_change_score"
    assert record.value == 1.0
    assert record.units == "normalized_change_ratio"
    assert record.quality is not None
    assert "region_brightness_score" in record.quality
    assert record.provenance is not None
    assert (
        record.provenance["source_function"]
        == "openfloodai.vision.simple_signals.compare_region_signals"
    )


def test_pixel_change_adapter_is_always_ready() -> None:
    adapter = PixelChangeObservationAdapter(
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        reference_region=_REGION,
        previous_frame=np.zeros((10, 10), dtype=np.uint8),
        current_frame=np.zeros((10, 10), dtype=np.uint8),
    )

    statuses = check_capabilities([adapter])

    assert len(statuses) == 1
    assert statuses[0].ready is True
    assert statuses[0].plugin_id == "pixel_change_region_v1"


def test_pixel_change_adapter_works_through_the_shared_registry_helpers() -> None:
    adapter = PixelChangeObservationAdapter(
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        reference_region=_REGION,
        previous_frame=np.zeros((10, 10), dtype=np.uint8),
        current_frame=np.zeros((10, 10), dtype=np.uint8),
    )

    records = collect_evidence([adapter])

    assert len(records) == 1
    assert records[0].status == "available"
    assert records[0].value == 0.0

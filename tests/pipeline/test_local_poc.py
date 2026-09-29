from __future__ import annotations

from pathlib import Path
from typing import cast

import cv2
import numpy as np
import pytest

from openfloodai.config import write_evidence_adapter_override
from openfloodai.contracts import read_jsonl_records
from openfloodai.contracts.local_store import JsonObject
from openfloodai.evidence.settings import write_global_adapter_setting
from openfloodai.pipeline import LocalPocPipelineError, run_local_poc_pipeline
from openfloodai.pipeline.local_poc import run_local_region_poc_pipeline


def create_tiny_video(path: Path, *, frame_count: int = 2) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 2.0, (8, 8))
    assert writer.isOpened(), "test video writer should open"

    try:
        for index in range(frame_count):
            frame = np.full((8, 8, 3), 20 + index * 100, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


def write_site_config(path: Path, *, include_reference_region: bool = True) -> None:
    reference_region = """
  "reference_region": {
    "x": 0,
    "y": 50,
    "width": 100,
    "height": 50
  },
"""
    path.write_text(
        f"""{{
  "site_id": "site-demo-01",
  "camera_id": "camera-demo-01",
  "site_name": "Demo River Bridge",
  "public_location": "Demo River near Example Town",
  "input_type": "local_video",
{reference_region if include_reference_region else ""}
  "privacy_notes": "Broad public location only."
}}
""",
        encoding="utf-8",
    )


def write_site_config_with_eligible_guide(
    path: Path, *, video_id: str = "sample", video_time_seconds: float = 0
) -> None:
    """A site with a confirmed, normal-condition guide that has a water_side_point.

    `video_id` defaults to "sample" to match every test in this file's
    `video_path = tmp_path / "sample.avi"` -- riverbank_crossing_v1 only
    treats a guide as usable when its saved video_id matches the video
    actually being validated (video_path.stem), so tests exercising the
    "available" path must keep these in sync; call with a different
    video_id to exercise the GUIDE_SOURCE_MISMATCH path instead.
    """

    path.write_text(
        f"""{{
  "site_id": "site-demo-01",
  "camera_id": "camera-demo-01",
  "site_name": "Demo River Bridge",
  "public_location": "Demo River near Example Town",
  "input_type": "local_video",
  "reference_region": {{
    "x": 0,
    "y": 50,
    "width": 100,
    "height": 50
  }},
  "normal_waterline_guides": [
    {{
      "id": "left_bank",
      "label": "left bank",
      "points": [{{"x": 0, "y": 60}}, {{"x": 100, "y": 60}}],
      "video_id": "{video_id}",
      "video_time_seconds": {video_time_seconds},
      "site_id": "site-demo-01",
      "camera_id": "camera-demo-01",
      "status": "confirmed",
      "normal_condition": true,
      "notes": "",
      "confirmed_at": "2026-01-01T00:00:00+00:00",
      "invalidated_at": null,
      "invalidation_reason": null,
      "water_side_point": {{"x": 50, "y": 90}}
    }}
  ],
  "privacy_notes": "Broad public location only."
}}
""",
        encoding="utf-8",
    )


def write_site_config_with_full_region_guide(
    path: Path, *, video_id: str = "sample", video_time_seconds: float
) -> None:
    """A full-frame-region site, for tests needing real pixel separation between
    the land and water sides (the default 50%-tall region is too short for
    riverbank_crossing_v1's fixed band_width_px=10 to distinguish bands on a
    small test frame).
    """

    path.write_text(
        f"""{{
  "site_id": "site-demo-01",
  "camera_id": "camera-demo-01",
  "site_name": "Demo River Bridge",
  "public_location": "Demo River near Example Town",
  "input_type": "local_video",
  "reference_region": {{
    "x": 0,
    "y": 0,
    "width": 100,
    "height": 100
  }},
  "normal_waterline_guides": [
    {{
      "id": "left_bank",
      "label": "left bank",
      "points": [{{"x": 0, "y": 50}}, {{"x": 100, "y": 50}}],
      "video_id": "{video_id}",
      "video_time_seconds": {video_time_seconds},
      "site_id": "site-demo-01",
      "camera_id": "camera-demo-01",
      "status": "confirmed",
      "normal_condition": true,
      "notes": "",
      "confirmed_at": "2026-01-01T00:00:00+00:00",
      "invalidated_at": null,
      "invalidation_reason": null,
      "water_side_point": {{"x": 50, "y": 80}}
    }}
  ],
  "privacy_notes": "Broad public location only."
}}
""",
        encoding="utf-8",
    )


def create_two_band_video(path: Path, frames: list[np.ndarray]) -> None:
    """Write a 100x100 video whose frames are given explicitly, one array each."""

    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 2.0, (100, 100))
    assert writer.isOpened(), "test video writer should open"
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()


def two_band_frame(*, top_value: int, bottom_value: int) -> np.ndarray:
    frame = np.full((100, 100, 3), top_value, dtype=np.uint8)
    frame[50:, :, :] = bottom_value
    return frame


def test_local_poc_pipeline_writes_records_for_readable_video(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "records.jsonl"
    create_tiny_video(video_path)

    summary = run_local_poc_pipeline(
        video_path=video_path,
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)
    record_types = [record["record_type"] for record in records]

    assert summary["completed"] is True
    assert summary["records_written"] == len(records)
    assert record_types[0] == "camera_health_output"
    assert "video_frame_metadata" in record_types
    assert "visual_signal_output" in record_types
    assert record_types[-1] == "risk_state_output"
    assert all(record["site_id"] == "site-demo-01" for record in records)
    assert all(record["camera_id"] == "camera-demo-01" for record in records)


def test_local_poc_pipeline_preserves_record_order(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "records.jsonl"
    create_tiny_video(video_path, frame_count=3)

    run_local_poc_pipeline(
        video_path=video_path,
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)
    record_types = [record["record_type"] for record in records]

    assert record_types == [
        "camera_health_output",
        "video_frame_metadata",
        "video_frame_metadata",
        "video_frame_metadata",
        "evidence_window_output",
        "visual_signal_output",
        "risk_state_output",
    ]


def test_local_poc_pipeline_writes_only_health_record_for_missing_video(tmp_path: Path) -> None:
    output_path = tmp_path / "records.jsonl"

    summary = run_local_poc_pipeline(
        video_path=tmp_path / "missing.avi",
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)

    assert summary["completed"] is False
    assert summary["records_written"] == 1
    assert records[0]["record_type"] == "camera_health_output"
    assert records[0]["input_quality_state"] == "UNKNOWN"
    assert records[0]["reason_codes"] == ["INPUT_UNKNOWN"]


def test_local_poc_pipeline_writes_only_health_record_for_unreadable_video(tmp_path: Path) -> None:
    video_path = tmp_path / "not-a-video.avi"
    output_path = tmp_path / "records.jsonl"
    video_path.write_text("not real video", encoding="utf-8")

    summary = run_local_poc_pipeline(
        video_path=video_path,
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)

    assert summary["completed"] is False
    assert summary["records_written"] == 1
    assert records[0]["record_type"] == "camera_health_output"
    assert records[0]["input_quality_state"] == "UNKNOWN"
    assert records[0]["failure_detail"] == "video_file_unreadable"


def test_local_region_poc_pipeline_writes_region_signal_records(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    config_path = tmp_path / "site-config.json"
    output_path = tmp_path / "region-records.jsonl"
    create_tiny_video(video_path)
    write_site_config(config_path)

    summary = run_local_region_poc_pipeline(
        video_path=video_path,
        config_path=config_path,
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)
    visual_records = [
        record for record in records if record["record_type"] == "visual_signal_output"
    ]

    assert summary["completed"] is True
    assert summary["reference_region_used"] is True
    assert summary["config_path"] == str(config_path)
    assert len(visual_records) == 1
    assert visual_records[0]["reference_region_used"] is True
    assert visual_records[0]["region_x"] == 0.0
    assert visual_records[0]["region_y"] == 4.0
    assert visual_records[0]["region_width"] == 8.0
    assert visual_records[0]["region_height"] == 4.0
    assert "region_change_score" in visual_records[0]
    assert all(record["site_id"] == "site-demo-01" for record in records)
    assert all(record["camera_id"] == "camera-demo-01" for record in records)


def test_local_region_poc_pipeline_keeps_old_pipeline_shape_separate(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "records.jsonl"
    create_tiny_video(video_path)

    run_local_poc_pipeline(
        video_path=video_path,
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)
    visual_records = [
        record for record in records if record["record_type"] == "visual_signal_output"
    ]

    assert len(visual_records) == 1
    assert "frame_change_score" in visual_records[0]
    assert "region_change_score" not in visual_records[0]


def test_local_region_poc_pipeline_requires_reference_region(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.avi"
    config_path = tmp_path / "site-config.json"
    output_path = tmp_path / "region-records.jsonl"
    create_tiny_video(video_path)
    write_site_config(config_path, include_reference_region=False)

    with pytest.raises(LocalPocPipelineError, match="requires a reference_region"):
        run_local_region_poc_pipeline(
            video_path=video_path,
            config_path=config_path,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_local_region_poc_pipeline_writes_health_only_for_missing_video(tmp_path: Path) -> None:
    config_path = tmp_path / "site-config.json"
    output_path = tmp_path / "region-records.jsonl"
    write_site_config(config_path)

    summary = run_local_region_poc_pipeline(
        video_path=tmp_path / "missing.avi",
        config_path=config_path,
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)

    assert summary["completed"] is False
    assert summary["records_written"] == 1
    assert records[0]["record_type"] == "camera_health_output"
    assert records[0]["input_quality_state"] == "UNKNOWN"


def _nested_site_config(tmp_path: Path) -> Path:
    """A properly nested <sites_dir>/<site>/configs/<name>.json, matching real usage.

    _run_pipeline derives the reference directory from config_path assuming
    this exact layout (see _find_config_path elsewhere in the codebase) --
    the flat config_path used by the tests above is fine for tests that
    never touch settings, but adapter-settings tests need the real shape.
    """

    config_path = tmp_path / "sites" / "site" / "configs" / "site.json"
    config_path.parent.mkdir(parents=True)
    write_site_config(config_path)
    return config_path


def _nested_site_config_with_guide(tmp_path: Path, *, video_id: str = "sample") -> Path:
    config_path = tmp_path / "sites" / "site" / "configs" / "site.json"
    config_path.parent.mkdir(parents=True)
    write_site_config_with_eligible_guide(config_path, video_id=video_id)
    return config_path


def _reference_dir_for(config_path: Path) -> Path:
    site_dir = config_path.parent.parent
    return site_dir.parent.parent / "reference"


def test_local_region_poc_pipeline_disabled_adapter_skips_the_comparison(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "region-records.jsonl"
    create_tiny_video(video_path)
    config_path = _nested_site_config(tmp_path)
    write_global_adapter_setting(_reference_dir_for(config_path), "pixel_change_region_v1", False)

    summary = run_local_region_poc_pipeline(
        video_path=video_path, config_path=config_path, output_path=output_path
    )

    records = read_jsonl_records(output_path)
    record_types = [record["record_type"] for record in records]
    assert "visual_signal_output" not in record_types, "disabled means no comparison at all"
    assert record_types.count("evidence_record") == 2
    assert record_types.count("risk_state_output") == 1

    evidence_record = next(
        r
        for r in records
        if r["record_type"] == "evidence_record" and r["plugin_id"] == "pixel_change_region_v1"
    )
    assert evidence_record["status"] == "disabled"
    assert evidence_record["value"] is None
    assert "ADAPTER_DISABLED" in cast(list[str], evidence_record["reason_codes"])

    risk = next(r for r in records if r["record_type"] == "risk_state_output")
    assert risk["risk_state"] == "UNKNOWN"
    assert risk["reason_codes"] == ["ADAPTER_DISABLED"]

    assert summary["effective_evidence_adapters"] == [
        {
            "plugin_id": "pixel_change_region_v1",
            "plugin_version": "1.0.0",
            "enabled": False,
            "source": "global_override",
        },
        {
            "plugin_id": "riverbank_crossing_v1",
            "plugin_version": "1.0.0",
            "enabled": False,
            "source": "catalog_default",
        },
    ]


def test_local_region_poc_pipeline_enabled_adapter_writes_evidence_from_the_same_signal(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "region-records.jsonl"
    create_tiny_video(video_path)
    config_path = _nested_site_config(tmp_path)

    summary = run_local_region_poc_pipeline(
        video_path=video_path, config_path=config_path, output_path=output_path
    )

    records = read_jsonl_records(output_path)
    visual = next(r for r in records if r["record_type"] == "visual_signal_output")
    evidence_record = next(
        r
        for r in records
        if r["record_type"] == "evidence_record" and r["plugin_id"] == "pixel_change_region_v1"
    )

    assert evidence_record["status"] == "available"
    assert evidence_record["value"] == visual["region_change_score"]

    risk = next(r for r in records if r["record_type"] == "risk_state_output")
    assert risk["risk_state"] != "UNKNOWN" or risk["reason_codes"] != ["ADAPTER_DISABLED"]

    assert summary["effective_evidence_adapters"] == [
        {
            "plugin_id": "pixel_change_region_v1",
            "plugin_version": "1.0.0",
            "enabled": True,
            "source": "catalog_default",
        },
        {
            "plugin_id": "riverbank_crossing_v1",
            "plugin_version": "1.0.0",
            "enabled": False,
            "source": "catalog_default",
        },
    ]


def test_local_region_poc_pipeline_site_override_re_enables_a_globally_disabled_adapter(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "region-records.jsonl"
    create_tiny_video(video_path)
    config_path = _nested_site_config(tmp_path)
    write_global_adapter_setting(_reference_dir_for(config_path), "pixel_change_region_v1", False)
    write_evidence_adapter_override(config_path, "pixel_change_region_v1", True)

    summary = run_local_region_poc_pipeline(
        video_path=video_path, config_path=config_path, output_path=output_path
    )

    records = read_jsonl_records(output_path)
    assert any(r["record_type"] == "visual_signal_output" for r in records)
    adapters = cast(list[dict[str, object]], summary["effective_evidence_adapters"])
    assert adapters[0]["enabled"] is True
    assert adapters[0]["source"] == "site_override"


def test_local_poc_pipeline_whole_frame_path_is_unaffected_by_adapter_settings(
    tmp_path: Path,
) -> None:
    """run_local_poc_pipeline (no reference region) has no adapter identity yet."""

    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "records.jsonl"
    create_tiny_video(video_path)

    summary = run_local_poc_pipeline(
        video_path=video_path,
        site_id="site-demo-01",
        camera_id="camera-demo-01",
        output_path=output_path,
    )

    records = read_jsonl_records(output_path)
    assert not any(r["record_type"] == "evidence_record" for r in records)
    assert summary["effective_evidence_adapters"] == []


def _riverbank_crossing_records(records: list[JsonObject]) -> JsonObject:
    return next(
        r
        for r in records
        if r["record_type"] == "evidence_record" and r["plugin_id"] == "riverbank_crossing_v1"
    )


def test_riverbank_crossing_disabled_by_default_produces_disabled_evidence(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "region-records.jsonl"
    create_tiny_video(video_path)
    config_path = _nested_site_config_with_guide(tmp_path)

    summary = run_local_region_poc_pipeline(
        video_path=video_path, config_path=config_path, output_path=output_path
    )

    records = read_jsonl_records(output_path)
    evidence = _riverbank_crossing_records(records)
    assert evidence["status"] == "disabled"
    assert evidence["reason_codes"] == ["ADAPTER_DISABLED"]

    adapters = cast(list[dict[str, object]], summary["effective_evidence_adapters"])
    riverbank_adapter = next(a for a in adapters if a["plugin_id"] == "riverbank_crossing_v1")
    assert riverbank_adapter["enabled"] is False
    assert riverbank_adapter["source"] == "catalog_default"


def test_riverbank_crossing_enabled_with_a_confirmed_guide_produces_available_evidence(
    tmp_path: Path,
) -> None:
    """Proves the guide's OWN source frame is used, not frames[before] from the pair.

    Frame 0 (t=0.0, the pair's own "before") is a uniform "already flooded"
    frame -- deliberately different from the guide's real source. The
    guide's video_time_seconds points at frame 2 (t=1.0), which -- like
    frame 1 (t=0.5, the pair's "after"/current) -- shows the true normal
    condition (dry land on top, water on the bottom). time_windows
    restricts the compared pair to (0.0, 1) only, so frame 2 is never
    itself part of the comparison; it exists solely to supply the guide's
    baseline. If the adapter used frames[before] (frame 0) instead of the
    guide's own source -- the exact bug this test guards against -- the
    land side would appear to change from "flooded" to "dry", registering
    a false crossing. Using the guide's real source correctly reports no
    change at all.
    """

    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "region-records.jsonl"
    create_two_band_video(
        video_path,
        [
            two_band_frame(top_value=50, bottom_value=50),  # t=0.0: pair's "before"
            two_band_frame(top_value=200, bottom_value=50),  # t=0.5: pair's "after"
            two_band_frame(top_value=200, bottom_value=50),  # t=1.0: guide's real source
        ],
    )
    config_path = tmp_path / "sites" / "site" / "configs" / "site.json"
    config_path.parent.mkdir(parents=True)
    write_site_config_with_full_region_guide(config_path, video_time_seconds=1.0)
    write_global_adapter_setting(_reference_dir_for(config_path), "riverbank_crossing_v1", True)

    run_local_region_poc_pipeline(
        video_path=video_path,
        config_path=config_path,
        output_path=output_path,
        time_windows=[(0.0, 0.75)],
    )

    records = read_jsonl_records(output_path)
    evidence = _riverbank_crossing_records(records)
    assert evidence["status"] == "available"
    provenance = cast(dict[str, object], evidence["provenance"])
    assert provenance["guide_id"] == "left_bank"
    # Comparing against the guide's real source (content-identical to the
    # "after" frame) correctly finds nothing. Comparing against frames[before]
    # (the bug this guards against) would instead show the land side
    # "changing" from flooded to dry and wrongly report a crossing.
    assert evidence["value"] == 0.0
    assert evidence["reason_codes"] == ["NO_CLEAR_CROSSING", "CAMERA_ALIGNMENT_UNAVAILABLE"]


def test_riverbank_crossing_reports_source_mismatch_for_a_guide_from_another_video(
    tmp_path: Path,
) -> None:
    """A guide traced on a DIFFERENT video must never supply a baseline here.

    Regression for the exact bug reported in review: without this check,
    the pipeline would silently compare against an arbitrary sampled frame
    from THIS video instead of refusing -- convincing but wrong crossing
    evidence, since the guide's points were only ever traced relative to
    some other video entirely.
    """

    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "region-records.jsonl"
    create_tiny_video(video_path)
    config_path = _nested_site_config_with_guide(tmp_path, video_id="a-different-video")
    write_global_adapter_setting(_reference_dir_for(config_path), "riverbank_crossing_v1", True)

    run_local_region_poc_pipeline(
        video_path=video_path, config_path=config_path, output_path=output_path
    )

    records = read_jsonl_records(output_path)
    evidence = _riverbank_crossing_records(records)
    assert evidence["status"] == "invalid"
    assert evidence["reason_codes"] == ["GUIDE_SOURCE_MISMATCH"]


def test_riverbank_crossing_enabled_without_an_eligible_guide_is_invalid(
    tmp_path: Path,
) -> None:
    """No confirmed+normal_condition+water_side_point guide -> GUIDE_MISSING, not a crash."""

    video_path = tmp_path / "sample.avi"
    output_path = tmp_path / "region-records.jsonl"
    create_tiny_video(video_path)
    config_path = _nested_site_config(tmp_path)
    write_global_adapter_setting(_reference_dir_for(config_path), "riverbank_crossing_v1", True)

    run_local_region_poc_pipeline(
        video_path=video_path, config_path=config_path, output_path=output_path
    )

    records = read_jsonl_records(output_path)
    evidence = _riverbank_crossing_records(records)
    assert evidence["status"] == "invalid"
    assert evidence["reason_codes"] == ["GUIDE_MISSING"]


def test_riverbank_crossing_never_affects_the_risk_state(tmp_path: Path) -> None:
    """Enabling/disabling riverbank_crossing must not change pixel_change's risk output."""

    video_path = tmp_path / "sample.avi"
    disabled_output = tmp_path / "disabled.jsonl"
    enabled_output = tmp_path / "enabled.jsonl"
    create_tiny_video(video_path)
    config_path = _nested_site_config_with_guide(tmp_path)

    run_local_region_poc_pipeline(
        video_path=video_path, config_path=config_path, output_path=disabled_output
    )
    write_global_adapter_setting(_reference_dir_for(config_path), "riverbank_crossing_v1", True)
    run_local_region_poc_pipeline(
        video_path=video_path, config_path=config_path, output_path=enabled_output
    )

    disabled_risk = next(
        r for r in read_jsonl_records(disabled_output) if r["record_type"] == "risk_state_output"
    )
    enabled_risk = next(
        r for r in read_jsonl_records(enabled_output) if r["record_type"] == "risk_state_output"
    )
    # Compare content, not generated identifiers (record_id/source_record_ids
    # are fresh uuids each run regardless of riverbank_crossing's state).
    stable_fields = ("risk_state", "reason_codes", "confidence", "human_summary")
    assert {field: disabled_risk[field] for field in stable_fields} == {
        field: enabled_risk[field] for field in stable_fields
    }

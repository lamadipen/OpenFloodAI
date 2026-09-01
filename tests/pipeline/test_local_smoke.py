from __future__ import annotations

from pathlib import Path

from openfloodai.contracts import read_jsonl_records
from openfloodai.pipeline import run_local_poc_smoke


def test_local_poc_smoke_creates_end_to_end_review_outputs(tmp_path: Path) -> None:
    result = run_local_poc_smoke(tmp_path / "smoke")

    records_path = Path(result.records_path)
    summary_path = Path(result.summary_path)
    operator_notes_path = Path(result.operator_notes_path)
    review_image_paths = [Path(path) for path in result.review_image_paths]

    records = read_jsonl_records(records_path)
    record_types = [record["record_type"] for record in records]
    visual_records = [
        record for record in records if record["record_type"] == "visual_signal_output"
    ]

    assert result.reference_region_used is True
    assert result.records_written == len(records)
    assert "camera_health_output" in record_types
    assert "video_frame_metadata" in record_types
    assert "visual_signal_output" in record_types
    assert "risk_state_output" in record_types
    assert len(visual_records) == 1
    assert visual_records[0]["reference_region_used"] is True
    assert "region_change_score" in visual_records[0]
    assert records_path.exists()
    assert summary_path.exists()
    assert operator_notes_path.exists()
    assert all(path.exists() for path in review_image_paths)
    assert "visual_signal_output" in summary_path.read_text(encoding="utf-8")
    assert "not an official public warning" in operator_notes_path.read_text(encoding="utf-8")

from __future__ import annotations

from pathlib import Path

import pytest

from openfloodai.contracts import write_jsonl_records
from openfloodai.replay import ReplaySummaryError, render_summary_markdown, summarize_jsonl_records


def test_summarizes_small_jsonl_file(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    write_jsonl_records(
        path,
        [
            {
                "record_type": "camera_health_output",
                "record_id": "health-001",
                "timestamp": "2026-08-31T00:00:00+00:00",
                "input_quality_state": "USABLE",
            },
            {
                "record_type": "visual_signal_output",
                "record_id": "signal-001",
                "timestamp": "2026-08-31T00:00:01+00:00",
                "frame_change_score": 0.25,
                "brightness_score": 0.4,
            },
            {
                "record_type": "visual_signal_output",
                "record_id": "signal-002",
                "timestamp": "2026-08-31T00:00:02+00:00",
                "frame_change_score": 0.5,
                "brightness_score": 0.3,
            },
            {
                "record_type": "risk_state_output",
                "record_id": "risk-001",
                "timestamp": "2026-08-31T00:00:03+00:00",
                "risk_state": "WATCH",
                "confidence": 0.72,
            },
        ],
    )

    summary = summarize_jsonl_records(path)

    assert summary.total_records == 4
    assert summary.record_type_counts == {
        "camera_health_output": 1,
        "risk_state_output": 1,
        "visual_signal_output": 2,
    }
    assert summary.risk_state_counts == {"WATCH": 1}
    assert summary.unknown_or_degraded_records == 0
    assert summary.first_timestamp == "2026-08-31T00:00:00+00:00"
    assert summary.last_timestamp == "2026-08-31T00:00:03+00:00"
    assert summary.highest_visual_signals["frame_change_score"] == 0.5
    assert summary.highest_visual_signals["brightness_score"] == 0.4
    assert summary.highest_risk_confidence == 0.72


def test_counts_unknown_and_degraded_records(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    write_jsonl_records(
        path,
        [
            {
                "record_type": "camera_health_output",
                "input_quality_state": "UNKNOWN",
                "reason_codes": ["INPUT_UNKNOWN"],
            },
            {
                "record_type": "risk_state_output",
                "risk_state": "UNKNOWN",
                "reason_codes": ["DEGRADED_EVIDENCE_USED"],
            },
        ],
    )

    summary = summarize_jsonl_records(path)

    assert summary.unknown_or_degraded_records == 2
    assert summary.risk_state_counts == {"UNKNOWN": 1}


def test_missing_optional_fields_do_not_crash_report(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    write_jsonl_records(
        path,
        [
            {"record_id": "minimal-001"},
            {"record_type": "visual_signal_output", "brightness_score": "not-a-number"},
        ],
    )

    summary = summarize_jsonl_records(path)

    assert summary.total_records == 2
    assert summary.record_type_counts == {
        "unknown_record_type": 1,
        "visual_signal_output": 1,
    }
    assert summary.first_timestamp is None
    assert summary.last_timestamp is None
    assert summary.highest_visual_signals == {}


def test_bad_jsonl_input_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"record_id": "ok"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ReplaySummaryError, match="Could not summarize JSONL records"):
        summarize_jsonl_records(path)


def test_markdown_report_is_simple_and_does_not_dump_private_fields(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    write_jsonl_records(
        path,
        [
            {
                "record_type": "camera_health_output",
                "timestamp": "2026-08-31T00:00:00+00:00",
                "input_quality_state": "USABLE",
                "camera_stream_url": "rtsp://private-camera.example/live",
                "contact_email": "private@example.com",
            },
            {
                "record_type": "risk_state_output",
                "timestamp": "2026-08-31T00:00:01+00:00",
                "risk_state": "NORMAL",
                "confidence": 0.93,
            },
        ],
    )

    markdown = render_summary_markdown(summarize_jsonl_records(path))

    assert "# POC Summary" in markdown
    assert "- camera_health_output: 1" in markdown
    assert "- NORMAL: 1" in markdown
    assert "## Prototype Confidence" in markdown
    assert "- Highest risk confidence: 0.930" in markdown
    assert "not flood probability" in markdown
    assert "No public warning was created" in markdown
    assert "rtsp://" not in markdown
    assert "private@example.com" not in markdown


def test_summary_ignores_invalid_risk_confidence_values(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    write_jsonl_records(
        path,
        [
            {
                "record_type": "risk_state_output",
                "risk_state": "NORMAL",
                "confidence": 1.5,
            },
            {
                "record_type": "risk_state_output",
                "risk_state": "WATCH",
                "confidence": "high",
            },
        ],
    )

    summary = summarize_jsonl_records(path)
    markdown = render_summary_markdown(summary)

    assert summary.highest_risk_confidence is None
    assert "- Highest risk confidence: Not found" in markdown

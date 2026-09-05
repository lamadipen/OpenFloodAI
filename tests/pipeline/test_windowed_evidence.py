"""Regression evidence for issue #104: time coverage, quality, and exact images."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from openfloodai.contracts import read_jsonl_records
from openfloodai.ingestion.evidence_sampling import SamplingSettings, sample_indices
from openfloodai.pipeline import run_local_poc_pipeline, run_local_video_review
from openfloodai.pipeline.local_poc import read_selected_frames, run_local_region_poc_pipeline
from openfloodai.review import compare_label_records


def video(path: Path, values: list[int]) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),  # type: ignore[attr-defined]
        2.0,
        (32, 24),
    )
    assert writer.isOpened()
    try:
        for value in values:
            writer.write(np.full((24, 32, 3), value, dtype=np.uint8))
    finally:
        writer.release()


def config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "site_id": "test",
                "camera_id": "test",
                "site_name": "Test",
                "public_location": "Synthetic",
                "input_type": "local_video",
                "privacy_notes": "Synthetic only",
                "reference_region": {"x": 0, "y": 0, "width": 100, "height": 100},
            }
        )
    )


def label(window: tuple[float, float], value: str = "water_rising") -> dict[str, object]:
    return {"video_id": "test", "time_window_seconds": list(window), "human_label": value}


@pytest.mark.parametrize("region", [False, True])
def test_slow_change_has_full_window_evidence(tmp_path: Path, region: bool) -> None:
    path = tmp_path / "test.avi"
    output = tmp_path / "records.jsonl"
    cfg = tmp_path / "config.json"
    # Neighbouring 5s changes stay below 0.05; total change exceeds it.
    video(path, [50 + i // 2 for i in range(60)])
    config(cfg)
    if region:
        run_local_region_poc_pipeline(path, cfg, output, time_windows=[(0, 30)])
    else:
        run_local_poc_pipeline(path, "test", "test", output, time_windows=[(0, 30)])
    records = read_jsonl_records(output)
    metadata = [r for r in records if r["record_type"] == "video_frame_metadata"]
    signals = [r for r in records if r["record_type"] == "visual_signal_output"]
    assert len(metadata) == 60
    assert len(signals) > 1
    assert max(float(str(r["comparison_end_seconds"])) for r in signals) == 29.5
    assert all(r["video_time_seconds"] == r["comparison_end_seconds"] for r in signals)
    field = "region_change_score" if region else "frame_change_score"
    short = [
        r
        for r in signals
        if float(str(r["comparison_end_seconds"])) - float(str(r["comparison_start_seconds"])) <= 5
    ]
    assert max(float(str(r[field])) for r in short) < 0.05
    assert max(float(str(r[field])) for r in signals) > 0.05
    by_id = {r["record_id"]: r for r in metadata}
    for signal in signals:
        source_ids = signal["source_record_ids"]
        assert isinstance(source_ids, list)
        assert [by_id[str(i)]["video_time_seconds"] for i in source_ids] == [
            signal["comparison_start_seconds"],
            signal["comparison_end_seconds"],
        ]
    report = compare_label_records(
        system_records=records, human_labels=[label((0, 30))], video_id="test"
    )
    assert report.agree_count == 1


@pytest.mark.parametrize(
    ("values", "expected", "reason"),
    [
        ([80] * 60, "agree", ""),
        ([0] * 10 + [80] * 50, "agree", "IMAGE_TOO_DARK"),
        ([0] * 60, "cannot_compare", "Fewer than two"),
        ([0] * 59 + [80], "cannot_compare", "Fewer than two"),
        ([80] * 10 + [0] * 40 + [80] * 10, "cannot_compare", "large gap"),
        ([80] * 4, "cannot_compare", "large gap"),
    ],
)
def test_quality_and_coverage_are_visible(
    tmp_path: Path,
    values: list[int],
    expected: str,
    reason: str,
) -> None:
    path, cfg = tmp_path / "test.avi", tmp_path / "config.json"
    video(path, values)
    config(cfg)
    result = run_local_video_review(
        video_path=path, config_path=cfg, output_dir=tmp_path / "out", time_windows=[(0, 30)]
    )
    records = read_jsonl_records(Path(result.records_path))
    comparison = compare_label_records(
        system_records=records, human_labels=[label((0, 30), "no_clear_change")], video_id="test"
    ).comparisons[0]
    assert comparison.result == expected
    assert reason in comparison.note
    metadata = [r for r in records if r["record_type"] == "video_frame_metadata"]
    assert len(metadata) == len(values)
    assert sum(r["input_quality_state"] == "DEGRADED" for r in metadata) == values.count(0)
    for signal in (r for r in records if r["record_type"] == "visual_signal_output"):
        assert values[int(str(signal["baseline_frame_index"]))] != 0
        assert values[int(str(signal["changed_frame_index"]))] != 0
    summary = Path(result.summary_path).read_text()
    assert "Unusable frames:" in summary
    if values.count(0) >= len(values) - 1:
        assert result.review_image_paths == ()
        assert not any(r.get("risk_state") == "NORMAL" for r in records)


def test_separate_windows_do_not_compare_across_a_jump(tmp_path: Path) -> None:
    path, cfg = tmp_path / "test.avi", tmp_path / "config.json"
    video(path, [50] * 20 + [200] * 20)
    config(cfg)
    result = run_local_video_review(
        video_path=path,
        config_path=cfg,
        output_dir=tmp_path / "out",
        time_windows=[(0, 10), (10, 20)],
    )
    records = read_jsonl_records(Path(result.records_path))
    report = compare_label_records(
        system_records=records,
        human_labels=[label((0, 10), "no_clear_change"), label((10, 20), "no_clear_change")],
        video_id="test",
    )
    assert report.agree_count == 2
    assert len(result.review_image_paths) == 12
    assert sorted(path.name for path in (tmp_path / "out" / "review-images").glob("*.png"))[:3] == [
        "review-window-0-10s-baseline-overlay.png",
        "review-window-0-10s-baseline.png",
        "review-window-0-10s-changed-overlay.png",
    ]
    signals = [r for r in records if r["record_type"] == "visual_signal_output"]
    assert all(
        not (
            float(str(r["comparison_start_seconds"]))
            < 10
            <= float(str(r["comparison_end_seconds"]))
        )
        for r in signals
    )


def test_review_image_uses_exact_saved_pair_and_refreshes_outputs(tmp_path: Path) -> None:
    path, cfg, out = tmp_path / "test.avi", tmp_path / "config.json", tmp_path / "out"
    video(path, [0] * 10 + list(range(50, 100)))
    config(cfg)
    result = run_local_video_review(video_path=path, config_path=cfg, output_dir=out)
    records = read_jsonl_records(Path(result.records_path))
    signals = [r for r in records if r["record_type"] == "visual_signal_output"]
    chosen = max(signals, key=lambda r: float(str(r["region_change_score"])))
    indices = [int(str(chosen[k])) for k in ("baseline_frame_index", "changed_frame_index")]
    decoded = read_selected_frames(path, indices)
    image_dir = out / "review-images"
    filenames = [
        next(image_dir.glob("*-baseline.png")).name,
        next(image_dir.glob("*-changed.png")).name,
    ]
    for filename, index in zip(filenames, indices, strict=True):
        saved = cv2.imread(str(out / "review-images" / filename))
        # The top 24 pixels are a timestamp caption; the evidence pixels are unchanged.
        assert saved is not None
        assert np.array_equal(saved[24:, :32], decoded[index])
    assert str(chosen["record_id"]) in Path(result.summary_path).read_text()
    assert "Review images:" in Path(result.summary_path).read_text()
    video(path, [0] * 60)
    rerun = run_local_video_review(video_path=path, config_path=cfg, output_dir=out)
    assert rerun.review_image_paths == ()
    assert not list((out / "review-images").glob("*.png"))
    assert not any(
        r["record_type"] == "visual_signal_output"
        for r in read_jsonl_records(Path(rerun.records_path))
    )


def test_cap_spans_long_clip_instead_of_stopping_early() -> None:
    metadata: list[dict[str, object]] = [
        {"video_time_seconds": i * 0.5, "input_quality_state": "USABLE"} for i in range(2400)
    ]
    selected = sample_indices(metadata, (0, 1200), SamplingSettings(max_samples=12))
    assert len(selected) <= 12
    assert selected[0] == 0
    assert selected[-1] == 2399
    assert max(b - a for a, b in zip(selected, selected[1:], strict=False)) <= 219


@pytest.mark.parametrize("interval", [0.0, -1.0, float("nan"), float("inf")])
def test_reject_invalid_interval(interval: float) -> None:
    with pytest.raises(ValueError):
        SamplingSettings(interval_seconds=interval)


@pytest.mark.parametrize("reverse", [False, True])
def test_issue_104_synthetic_waterline(tmp_path: Path, reverse: bool) -> None:
    path, cfg = tmp_path / "test.avi", tmp_path / "config.json"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),  # type: ignore[attr-defined]
        2.0,
        (96, 64),
    )
    assert writer.isOpened()
    try:
        for index in range(59, -1, -1) if reverse else range(60):
            frame = np.zeros((64, 96, 3), dtype=np.uint8)
            frame[:32, :] = (200, 180, 150)
            frame[32:, :] = (60, 80, 95)
            water_top = int(round(62 - index / 59 * 16))
            frame[water_top:, :] = (130, 90, 40)
            frame[:, 44:52] = (150, 150, 140)
            frame[water_top:, 44:52] = (120, 95, 70)
            writer.write(frame)
    finally:
        writer.release()
    config(cfg)
    payload = json.loads(cfg.read_text())
    payload["reference_region"].update(y=50, height=50)
    cfg.write_text(json.dumps(payload))
    result = run_local_video_review(
        video_path=path,
        config_path=cfg,
        output_dir=tmp_path / "out",
        time_windows=[(0, 30)],
    )
    report = compare_label_records(
        system_records=read_jsonl_records(Path(result.records_path)),
        human_labels=[label((0, 30), "water_falling" if reverse else "water_rising")],
        video_id="test",
    )
    assert report.agree_count == 1
    assert report.comparisons[0].system_result == "water_change_seen"

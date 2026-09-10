from pathlib import Path

import pytest

from openfloodai.validation.input_snapshot import capture_run_inputs, read_input_snapshot


def test_processing_uses_private_copies_and_cleans_them_on_failure(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    config = site / "config.json"
    config.write_text('{"site_id":"site-1","reference_region":{"x":0}}')
    video = site / "clip.mp4"
    video.write_bytes(b"original local bytes")
    run = site / "outputs/runs/run-1"
    run.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="interrupted"):
        with capture_run_inputs(site_dir=site, run_dir=run, config_path=config, videos=[video], labels=[]) as (saved_config, saved_videos):
            video.write_bytes(b"changed later")
            config.write_text('{"reference_region":{"x":50}}')
            assert saved_videos[0].read_bytes() == b"original local bytes"
            assert '"x":0' in saved_config.read_text()
            temporary_video = saved_videos[0]
            raise RuntimeError("interrupted")
    assert not temporary_video.exists()
    assert read_input_snapshot(run)["receipt"]["status"] == "failed"


def test_old_run_without_snapshot_does_not_use_live_inputs(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_input_snapshot(tmp_path)

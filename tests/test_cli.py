from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.cli import main


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "sites.json"
    config_path.write_text(
        json.dumps(
            [
                {
                    "site_id": "test-site",
                    "camera_id": "cam-test",
                    "latitude": 27.7,
                    "longitude": 85.3,
                    "description": "Test site",
                }
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def test_no_command(capsys: pytest.CaptureFixture[str]) -> None:
    result = main([])
    assert result == 0
    captured = capsys.readouterr()
    assert "openfloodai" in captured.out


def test_validate_config(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = main(["validate-config", str(config_path)])
    assert result == 0


def test_validate_config_invalid(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("not json array", encoding="utf-8")
    result = main(["validate-config", str(bad_path)])
    assert result == 1


def test_sites_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = _write_config(tmp_path)
    result = main(["sites", str(config_path)])
    assert result == 0
    captured = capsys.readouterr()
    assert "test-site" in captured.out
    assert "cam-test" in captured.out


def test_monitor_missing_site(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = main(
        [
            "monitor",
            "--config",
            str(config_path),
            "--site",
            "nonexistent",
            "--stream",
            "rtsp://example.com",
        ]
    )
    assert result == 1

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.ingestion.river_registry import RiverRegistryError, load_river_registry

VALID_CAMERA = {
    "river_id": "test-river",
    "camera_id": "TEST_CAMERA_ONE",
    "nwis_id": "09999999",
    "state": "CO",
    "latitude": 40.0,
    "longitude": -105.0,
    "display_name": "Test Camera One",
    "folder_name": "test-river-one",
    "gage_relationship": "same_site",
    "timezone": "America/Denver",
}


def _write_registry(reference_dir: Path, river_id: str, payload: dict[str, object]) -> None:
    rivers_dir = reference_dir / "rivers"
    rivers_dir.mkdir(parents=True, exist_ok=True)
    (rivers_dir / f"{river_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_load_river_registry_parses_valid_file(tmp_path: Path) -> None:
    _write_registry(
        tmp_path,
        "test-river",
        {
            "river_id": "test-river",
            "display_name": "Test River",
            "source": "https://example.invalid",
            "cameras": [VALID_CAMERA],
        },
    )

    registry = load_river_registry("test-river", tmp_path)

    assert registry.river_id == "test-river"
    assert len(registry.cameras) == 1
    camera = registry.camera("TEST_CAMERA_ONE")
    assert camera is not None
    assert camera.folder_name == "test-river-one"
    assert registry.camera("missing") is None


def test_load_river_registry_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RiverRegistryError, match="No river registry"):
        load_river_registry("does-not-exist", tmp_path)


def test_load_river_registry_rejects_invalid_river_id(tmp_path: Path) -> None:
    with pytest.raises(RiverRegistryError, match="Invalid river id"):
        load_river_registry("../etc/passwd", tmp_path)


def test_load_river_registry_rejects_duplicate_camera_ids(tmp_path: Path) -> None:
    _write_registry(
        tmp_path,
        "test-river",
        {
            "river_id": "test-river",
            "display_name": "Test River",
            "cameras": [VALID_CAMERA, VALID_CAMERA],
        },
    )
    with pytest.raises(RiverRegistryError, match="Duplicate camera_id"):
        load_river_registry("test-river", tmp_path)


def test_load_river_registry_requires_note_for_nearby_gage(tmp_path: Path) -> None:
    camera = dict(VALID_CAMERA, gage_relationship="nearby")
    _write_registry(
        tmp_path,
        "test-river",
        {"river_id": "test-river", "display_name": "Test River", "cameras": [camera]},
    )
    with pytest.raises(RiverRegistryError, match="gage_relationship_note"):
        load_river_registry("test-river", tmp_path)


def test_load_river_registry_accepts_nearby_gage_with_note(tmp_path: Path) -> None:
    camera = dict(
        VALID_CAMERA,
        gage_relationship="nearby",
        gage_relationship_note="Closest gage is 2 miles up.",
    )
    _write_registry(
        tmp_path,
        "test-river",
        {"river_id": "test-river", "display_name": "Test River", "cameras": [camera]},
    )
    registry = load_river_registry("test-river", tmp_path)
    assert registry.cameras[0].gage_relationship_note == "Closest gage is 2 miles up."


def test_load_river_registry_rejects_empty_camera_list(tmp_path: Path) -> None:
    _write_registry(
        tmp_path,
        "test-river",
        {"river_id": "test-river", "display_name": "Test River", "cameras": []},
    )
    with pytest.raises(RiverRegistryError, match="non-empty"):
        load_river_registry("test-river", tmp_path)


def test_load_river_registry_rejects_invalid_json(tmp_path: Path) -> None:
    rivers_dir = tmp_path / "rivers"
    rivers_dir.mkdir()
    (rivers_dir / "test-river.json").write_text("not json", encoding="utf-8")
    with pytest.raises(RiverRegistryError, match="not valid JSON"):
        load_river_registry("test-river", tmp_path)


def test_real_colorado_river_registry_loads() -> None:
    reference_dir = Path(__file__).resolve().parents[2] / "data" / "reference"
    registry = load_river_registry("colorado-river", reference_dir)
    assert registry.river_id == "colorado-river"
    assert len(registry.cameras) == 10
    assert all(camera.gage_relationship == "same_site" for camera in registry.cameras)

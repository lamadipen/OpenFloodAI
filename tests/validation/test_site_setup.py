"""Tests for local validation site setup."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from openfloodai.validation import setup_validation_site


def test_setup_validation_site_creates_structure() -> None:
    """Test that the setup helper creates the expected folder structure and config."""

    with TemporaryDirectory() as tmp_dir:
        sites_base_dir = Path(tmp_dir)
        folder_name = "test-site"
        site_id = "site-test"
        camera_id = "camera-test"
        site_name = "Test Site"
        public_location = "Test Location"

        result = setup_validation_site(
            sites_base_dir=sites_base_dir,
            folder_name=folder_name,
            site_id=site_id,
            camera_id=camera_id,
            site_name=site_name,
            public_location=public_location,
        )

        assert result.created
        assert result.site_dir.exists()
        assert result.config_path.exists()

        # Check subdirectories
        expected_subdirs = [
            "configs",
            "inputs/videos",
            "inputs/other",
            "labels",
            "expected-behavior",
            "human-evidence/flood-images",
            "human-evidence/notes",
            "outputs",
        ]
        for subdir in expected_subdirs:
            assert (result.site_dir / subdir).is_dir()
            assert (result.site_dir / subdir / ".gitkeep").exists()

        # Check config content
        with open(result.config_path, encoding="utf-8") as f:
            config = json.load(f)
        
        assert config["site_id"] == site_id
        assert config["camera_id"] == camera_id
        assert config["site_name"] == site_name
        assert config["public_location"] == public_location
        assert config["input_type"] == "local_video"


def test_setup_validation_site_refuses_empty_required_fields() -> None:
    """Test that the setup helper refuses empty required fields."""

    with TemporaryDirectory() as tmp_dir:
        sites_base_dir = Path(tmp_dir)
        
        # Missing folder_name
        result = setup_validation_site(
            sites_base_dir=sites_base_dir,
            folder_name="",
            site_id="site-test",
            camera_id="camera-test",
            site_name="Test Site",
            public_location="Test Location",
        )
        assert not result.created
        assert "Missing required fields" in result.message


def test_setup_validation_site_avoids_overwriting_by_default() -> None:
    """Test that the setup helper avoids overwriting existing data by default."""

    with TemporaryDirectory() as tmp_dir:
        sites_base_dir = Path(tmp_dir)
        folder_name = "test-site"
        
        # Create it once
        setup_validation_site(
            sites_base_dir=sites_base_dir,
            folder_name=folder_name,
            site_id="site-1",
            camera_id="camera-1",
            site_name="Site 1",
            public_location="Location 1",
        )

        # Try to create again with different values
        result = setup_validation_site(
            sites_base_dir=sites_base_dir,
            folder_name=folder_name,
            site_id="site-2",
            camera_id="camera-2",
            site_name="Site 2",
            public_location="Location 2",
        )
        
        assert not result.created
        assert "already exists" in result.message

        # Check that original config is preserved
        config_path = sites_base_dir / folder_name / "configs" / f"{folder_name}.json"
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        assert config["site_id"] == "site-1"


def test_setup_validation_site_overwrites_when_requested() -> None:
    """Test that the setup helper overwrites when requested."""

    with TemporaryDirectory() as tmp_dir:
        sites_base_dir = Path(tmp_dir)
        folder_name = "test-site"
        
        # Create it once
        setup_validation_site(
            sites_base_dir=sites_base_dir,
            folder_name=folder_name,
            site_id="site-1",
            camera_id="camera-1",
            site_name="Site 1",
            public_location="Location 1",
        )

        # Try to create again with overwrite=True
        result = setup_validation_site(
            sites_base_dir=sites_base_dir,
            folder_name=folder_name,
            site_id="site-2",
            camera_id="camera-2",
            site_name="Site 2",
            public_location="Location 2",
            overwrite=True
        )
        
        assert result.created
        
        # Check that config is updated
        with open(result.config_path, encoding="utf-8") as f:
            config = json.load(f)
        assert config["site_id"] == "site-2"

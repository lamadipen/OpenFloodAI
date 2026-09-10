from __future__ import annotations

import json
from pathlib import Path

from openfloodai.validation import delete_all_sites, delete_site


def make_site(sites_dir: Path, folder_name: str) -> Path:
    site_dir = sites_dir / folder_name
    (site_dir / "configs").mkdir(parents=True)
    (site_dir / "inputs" / "videos").mkdir(parents=True)
    (site_dir / "labels").mkdir(parents=True)
    (site_dir / "configs" / "site-config.json").write_text(
        json.dumps({"site_id": folder_name}), encoding="utf-8"
    )
    (site_dir / "manifest.jsonl").write_text("", encoding="utf-8")
    return site_dir


def test_delete_site_removes_the_site_folder(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir = make_site(sites_dir, "example-site")

    result = delete_site(sites_dir, "example-site")

    assert result.deleted, result.message
    assert not site_dir.exists()


def test_delete_site_does_not_remove_other_sites(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    make_site(sites_dir, "site-a")
    site_b = make_site(sites_dir, "site-b")

    result = delete_site(sites_dir, "site-a")

    assert result.deleted, result.message
    assert not (sites_dir / "site-a").exists()
    assert site_b.is_dir()


def test_delete_site_refuses_empty_folder_name(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    result = delete_site(sites_dir, "")

    assert not result.deleted
    assert "Missing required field" in result.message


def test_delete_site_refuses_missing_site(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    result = delete_site(sites_dir, "does-not-exist")

    assert not result.deleted
    assert "does not exist" in result.message


def test_delete_site_refuses_path_traversal(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    outside_dir = tmp_path / "outside-site"
    outside_dir.mkdir()

    result = delete_site(sites_dir, "../outside-site")

    assert not result.deleted
    assert "must stay inside the sites directory" in result.message
    assert outside_dir.is_dir()


def test_delete_site_refuses_nested_path(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    site_dir = make_site(sites_dir, "site-a")

    result = delete_site(sites_dir, "site-a/configs")

    assert not result.deleted
    assert "must stay inside the sites directory" in result.message
    assert (site_dir / "configs").is_dir()


def test_delete_all_sites_removes_only_direct_site_folders(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    make_site(sites_dir, "site-a")
    make_site(sites_dir, "site-b")
    stray_file = sites_dir / "notes.txt"
    stray_file.write_text("keep me", encoding="utf-8")

    result = delete_all_sites(sites_dir)

    assert result.deleted, result.message
    assert sorted(result.deleted_site_names) == ["site-a", "site-b"]
    assert sites_dir.is_dir()
    assert not (sites_dir / "site-a").exists()
    assert not (sites_dir / "site-b").exists()
    assert stray_file.is_file()


def test_delete_all_sites_does_not_delete_the_parent_directory(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    make_site(sites_dir, "site-a")

    delete_all_sites(sites_dir)

    assert sites_dir.exists()
    assert sites_dir.is_dir()


def test_delete_all_sites_handles_empty_sites_directory(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    result = delete_all_sites(sites_dir)

    assert result.deleted
    assert result.deleted_site_names == []

"""Safely delete local validation site folders.

Two operations are supported:

- ``delete_site`` removes one site folder (config, labels, manifest,
  videos, outputs, and any saved runs) from the local sites directory.
- ``delete_all_sites`` removes every direct site folder inside the local
  sites directory, without touching the sites directory itself.

Both refuse to act on anything that is not a direct child of the sites
directory, so a caller cannot delete files outside the configured local
sites directory even with a crafted ``folder_name`` such as
``../outside-site`` or a nested path such as ``site-a/configs``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class SiteDeleteResult:
    """Result of deleting one local site folder."""

    sites_dir: Path
    folder_name: str
    deleted: bool
    message: str


@dataclass(frozen=True)
class SiteDeleteAllResult:
    """Result of deleting every local site folder."""

    sites_dir: Path
    deleted: bool
    message: str
    deleted_site_names: list[str]


def delete_site(sites_dir: Path, folder_name: str) -> SiteDeleteResult:
    """Delete one site folder that is a direct child of ``sites_dir``."""

    empty = SiteDeleteResult(
        sites_dir=sites_dir, folder_name=folder_name, deleted=False, message=""
    )

    if not folder_name:
        return replace(empty, message="Missing required field: folder_name.")

    site_dir = (sites_dir / folder_name).resolve()
    if site_dir.parent != sites_dir.resolve():
        return replace(
            empty, message="Invalid folder_name: site folder must stay inside the sites directory."
        )

    if not site_dir.is_dir():
        return replace(empty, message=f"Site folder does not exist: {folder_name}.")

    shutil.rmtree(site_dir)
    return SiteDeleteResult(
        sites_dir=sites_dir,
        folder_name=folder_name,
        deleted=True,
        message=f"Deleted local site {folder_name}.",
    )


def delete_all_sites(sites_dir: Path) -> SiteDeleteAllResult:
    """Delete every direct site folder under ``sites_dir``, leaving it in place."""

    empty = SiteDeleteAllResult(
        sites_dir=sites_dir, deleted=False, message="", deleted_site_names=[]
    )

    if not sites_dir.exists() or not sites_dir.is_dir():
        return replace(empty, message=f"Sites folder does not exist: {sites_dir}.")

    site_dirs = sorted(path for path in sites_dir.iterdir() if path.is_dir())
    if not site_dirs:
        return replace(empty, message="No local sites were found to delete.", deleted=True)

    deleted_site_names: list[str] = []
    for site_dir in site_dirs:
        shutil.rmtree(site_dir)
        deleted_site_names.append(site_dir.name)

    return SiteDeleteAllResult(
        sites_dir=sites_dir,
        deleted=True,
        message=f"Deleted {len(deleted_site_names)} local site(s).",
        deleted_site_names=deleted_site_names,
    )

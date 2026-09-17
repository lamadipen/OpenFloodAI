"""Safely create or reuse validation sites for registry-driven camera bootstrap runs.

Issue #152's "safe site creation" rule: create a site if it does not exist,
reuse it without modifying config if it exists with the same camera_id, and
stop only that one camera (reporting a conflict) if it exists with a
different camera_id. Existing manual configuration (watched areas,
riverbank guides, privacy notes) is never touched here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openfloodai.config.site_config import SiteConfigError, load_site_config
from openfloodai.validation.site_setup import setup_validation_site

ALLOWED_SITE_BOOTSTRAP_STATUSES = {"created", "reused", "conflict"}


@dataclass(frozen=True)
class SiteBootstrapResult:
    """What happened when bootstrapping one camera's site."""

    camera_id: str
    folder_name: str
    site_dir: Path
    status: str
    message: str


def bootstrap_camera_site(
    *,
    sites_base_dir: Path,
    folder_name: str,
    camera_id: str,
    site_name: str,
    public_location: str = "",
    privacy_notes: str = "",
) -> SiteBootstrapResult:
    """Create a site for one camera, or safely reuse it / report a conflict.

    A folder that does not exist yet is created with a starter config. A
    folder that exists with the SAME camera_id is reused as-is: its config
    is not read into a new file and nothing is overwritten. A folder that
    exists with a DIFFERENT camera_id is reported as a conflict so the
    caller can skip only this camera and continue with the rest of a batch.
    """

    site_dir = (sites_base_dir / folder_name).resolve()
    config_path = site_dir / "configs" / f"{folder_name}.json"

    if not site_dir.exists():
        result = setup_validation_site(
            sites_base_dir=sites_base_dir,
            folder_name=folder_name,
            site_id=f"{folder_name}_sid",
            camera_id=camera_id,
            site_name=site_name,
            public_location=public_location,
            privacy_notes=privacy_notes,
        )
        if not result.created:
            return SiteBootstrapResult(camera_id, folder_name, site_dir, "conflict", result.message)
        return SiteBootstrapResult(
            camera_id, folder_name, site_dir, "created", f"Created site at {site_dir}."
        )

    if not config_path.is_file():
        return SiteBootstrapResult(
            camera_id,
            folder_name,
            site_dir,
            "conflict",
            f"Site folder exists but its config is missing or unreadable: {config_path}.",
        )

    try:
        existing = load_site_config(config_path)
    except SiteConfigError as error:
        return SiteBootstrapResult(
            camera_id,
            folder_name,
            site_dir,
            "conflict",
            f"Could not read the existing site config: {error}",
        )

    if existing.camera_id != camera_id:
        return SiteBootstrapResult(
            camera_id,
            folder_name,
            site_dir,
            "conflict",
            f"Site folder '{folder_name}' already exists with a different camera_id "
            f"({existing.camera_id!r}, not {camera_id!r}). Skipping this camera; "
            "its existing manual configuration was left untouched.",
        )

    return SiteBootstrapResult(
        camera_id,
        folder_name,
        site_dir,
        "reused",
        f"Reusing existing site at {site_dir} (same camera_id); config left unchanged.",
    )

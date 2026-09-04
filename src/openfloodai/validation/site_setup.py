"""Setup local validation site folder structure and starter config."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ValidationSiteSetupResult:
    """Result of setting up a local validation site."""

    site_dir: Path
    config_path: Path
    created: bool
    message: str


def setup_validation_site(
    sites_base_dir: Path,
    folder_name: str,
    site_id: str,
    camera_id: str,
    site_name: str,
    public_location: str,
    privacy_notes: str = "",
    overwrite: bool = False,
) -> ValidationSiteSetupResult:
    """Create a new local validation site folder and starter config."""

    # Safety checks for required fields
    if not folder_name or not site_id or not camera_id or not site_name or not public_location:
        return ValidationSiteSetupResult(
            site_dir=Path(),
            config_path=Path(),
            created=False,
            message=(
                "Missing required fields: folder_name, site_id, camera_id, "
                "site_name, and public_location are all required."
            ),
        )

    site_dir = sites_base_dir / folder_name

    if site_dir.exists() and not overwrite:
        return ValidationSiteSetupResult(
            site_dir=site_dir,
            config_path=Path(),
            created=False,
            message=(
                f"Site folder already exists: {site_dir}. "
                "Use overwrite=True if you want to modify it."
            ),
        )

    # Create directory structure
    subdirs = [
        "configs",
        "inputs/videos",
        "inputs/other",
        "labels",
        "expected-behavior",
        "human-evidence/flood-images",
        "human-evidence/notes",
        "outputs",
    ]

    for subdir in subdirs:
        (site_dir / subdir).mkdir(parents=True, exist_ok=True)
        # Add a .gitkeep to ensure empty folders are tracked if needed,
        # though usually these are for local use.
        (site_dir / subdir / ".gitkeep").touch()

    # Create starter config JSON
    config = {
        "site_id": site_id,
        "camera_id": camera_id,
        "site_name": site_name,
        "public_location": public_location,
        "input_type": "local_video",
        "reference_region": {"x": 0, "y": 50, "width": 100, "height": 50},
        "privacy_notes": privacy_notes or "This site uses a broad public location only.",
    }

    config_path = site_dir / "configs" / f"{folder_name}.json"

    if not config_path.exists() or overwrite:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    # Create README.md
    readme_path = site_dir / "README.md"
    if not readme_path.exists() or overwrite:
        readme_content = f"""# {site_name} Validation Site

Local validation site for {public_location}.

## Folder Structure
- `configs/`: Site configuration JSON files.
- `inputs/videos/`: Place local validation videos here.
- `inputs/other/`: Other input files (e.g. metadata).
- `labels/`: Human labels in .jsonl format.
- `expected-behavior/`: Hard cases and expected behavior definitions.
- `human-evidence/`: Flood images and operator notes.
- `outputs/`: Validation reports and review images.

## Site ID: {site_id}
## Camera ID: {camera_id}
"""
        readme_path.write_text(readme_content, encoding="utf-8")

    return ValidationSiteSetupResult(
        site_dir=site_dir,
        config_path=config_path,
        created=True,
        message=f"Successfully created site structure at {site_dir}",
    )

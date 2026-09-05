#!/usr/bin/env python3
"""Command-line helper to setup a new local validation site."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openfloodai.validation import setup_validation_site


def main() -> None:
    """Run the site setup helper."""

    parser = argparse.ArgumentParser(
        description="Setup a new local validation site folder and config."
    )
    parser.add_argument(
        "--folder-name",
        required=True,
        help="Name of the site folder (e.g. demo-bridge)",
    )
    parser.add_argument(
        "--site-id",
        required=True,
        help="Site ID (e.g. site-demo-bridge)",
    )
    parser.add_argument(
        "--camera-id",
        required=True,
        help="Camera ID (e.g. camera-demo-bridge-01)",
    )
    parser.add_argument(
        "--site-name",
        required=True,
        help="Human-friendly site name (e.g. Demo Bridge)",
    )
    parser.add_argument(
        "--public-location",
        required=True,
        help="Public location description",
    )
    parser.add_argument(
        "--privacy-notes",
        default="",
        help="Optional privacy notes",
    )
    parser.add_argument(
        "--sites-dir",
        default="data/sites",
        help="Base directory for validation sites",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing folder or config",
    )

    args = parser.parse_args()

    sites_base_dir = Path(args.sites_dir)

    result = setup_validation_site(
        sites_base_dir=sites_base_dir,
        folder_name=args.folder_name,
        site_id=args.site_id,
        camera_id=args.camera_id,
        site_name=args.site_name,
        public_location=args.public_location,
        privacy_notes=args.privacy_notes,
        overwrite=args.overwrite,
    )

    if result.created:
        print(f"Success: {result.message}")
        print(f"Site directory: {result.site_dir}")
        print(f"Config file:    {result.config_path}")
        print("\nNext steps:")
        print("1. Add a local video with scripts/intake_validation_video.py or Home UI.")
        print(f"2. Add human labels to {result.site_dir}/labels/")
        print("3. Run the Home UI to verify readiness: python3 scripts/run_openfloodai_home_ui.py")
    else:
        print(f"Error: {result.message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

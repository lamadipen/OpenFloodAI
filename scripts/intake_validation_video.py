#!/usr/bin/env python3
"""Command-line helper to add a local validation video and manifest row."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openfloodai.validation import intake_validation_video


def main() -> None:
    """Run the video intake helper."""

    parser = argparse.ArgumentParser(
        description="Copy a local video into a validation site and record manifest metadata."
    )
    parser.add_argument(
        "--site-dir",
        help="Path to the site folder (e.g. data/sites/example-site)",
    )
    parser.add_argument(
        "--folder-name",
        help="Site folder name under --sites-dir (e.g. example-site)",
    )
    parser.add_argument(
        "--sites-dir",
        default="data/sites",
        help="Base directory for validation sites",
    )
    parser.add_argument(
        "--video-path",
        required=True,
        help="Path to a local video file already on this computer",
    )
    parser.add_argument(
        "--video-id",
        required=True,
        help="Video ID used by labels and reports (e.g. rising-001)",
    )
    parser.add_argument(
        "--purpose",
        required=True,
        help="Why this video exists (e.g. possible_rising_water)",
    )
    parser.add_argument(
        "--split",
        required=True,
        choices=["practice", "locked_validation"],
        help="practice or locked_validation",
    )
    parser.add_argument(
        "--notes",
        required=True,
        help="Short plain-language notes about the video",
    )
    parser.add_argument(
        "--hard-case-type",
        default="",
        help="Optional confusing condition (e.g. heavy_glare)",
    )
    parser.add_argument(
        "--approved-for-repo",
        action="store_true",
        help="Set only when the video is clearly safe to commit. Default is false.",
    )
    parser.add_argument(
        "--has-human-label",
        action="store_true",
        help="Set when a human label already exists for this video_id",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing video file or manifest row",
    )

    args = parser.parse_args()

    if args.site_dir:
        site_dir = Path(args.site_dir)
    elif args.folder_name:
        site_dir = Path(args.sites_dir) / args.folder_name
    else:
        parser.error("Provide --site-dir or --folder-name")

    result = intake_validation_video(
        site_dir=site_dir,
        video_path=Path(args.video_path),
        video_id=args.video_id,
        purpose=args.purpose,
        split=args.split,
        notes=args.notes,
        approved_for_repo=args.approved_for_repo,
        has_human_label=args.has_human_label,
        hard_case_type=args.hard_case_type,
        overwrite=args.overwrite,
    )

    if result.created:
        print(f"Success: {result.message}")
        print(f"Video file:    {result.video_path}")
        print(f"Manifest file: {result.manifest_path}")
        print("\nThis helper copies a local file only. It does not upload video,")
        print("commit files, send alerts, or claim flood accuracy.")
        if not args.approved_for_repo:
            print("approved_for_repo is false, so the video should stay local.")
    else:
        print(f"Error: {result.message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

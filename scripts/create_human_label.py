#!/usr/bin/env python3
"""Command-line helper to create or update a human label record."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openfloodai.review import (
    ALLOWED_CONFIDENCE_LEVELS,
    ALLOWED_HUMAN_LABELS,
    create_human_label_record,
)


def main() -> None:
    """Run the human label creation helper."""

    parser = argparse.ArgumentParser(
        description=(
            "Create a human label record for a site video without manual JSON Lines editing."
        )
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
        "--video-id",
        required=True,
        help="Video ID for the reviewed video (e.g. rising-001)",
    )
    parser.add_argument(
        "--start",
        "--start-second",
        dest="start_second",
        required=True,
        type=float,
        help="Start second of the reviewed window (e.g. 30)",
    )
    parser.add_argument(
        "--end",
        "--end-second",
        dest="end_second",
        required=True,
        type=float,
        help="End second of the reviewed window (e.g. 60)",
    )
    parser.add_argument(
        "--label",
        "--human-label",
        dest="human_label",
        required=True,
        help=(
            "Human label value. Recommended values: "
            f"{', '.join(sorted(ALLOWED_HUMAN_LABELS))}. "
            "Custom values may use letters, numbers, dash, and underscore."
        ),
    )
    parser.add_argument(
        "--confidence",
        choices=sorted(ALLOWED_CONFIDENCE_LEVELS),
        default=None,
        help="Optional confidence level (low, medium, high)",
    )
    parser.add_argument(
        "--note",
        "--notes",
        dest="note",
        default="",
        help="Optional plain-language reviewer note",
    )
    parser.add_argument(
        "--reviewer-id",
        default="",
        help="Optional safe reviewer ID",
    )
    parser.add_argument(
        "--site-id",
        default="",
        help="Optional site ID",
    )
    parser.add_argument(
        "--camera-id",
        default="",
        help="Optional camera ID",
    )
    parser.add_argument(
        "--labels-file",
        default=None,
        help="Optional labels filename under labels/ (e.g. labels.jsonl)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing label record for this exact video and time window",
    )

    args = parser.parse_args()

    if args.site_dir:
        site_dir = Path(args.site_dir)
    elif args.folder_name:
        site_dir = Path(args.sites_dir) / args.folder_name
    else:
        parser.error("Provide --site-dir or --folder-name")

    result = create_human_label_record(
        site_dir=site_dir,
        video_id=args.video_id,
        start_second=args.start_second,
        end_second=args.end_second,
        human_label=args.human_label,
        confidence=args.confidence,
        note=args.note,
        reviewer_id=args.reviewer_id,
        site_id=args.site_id,
        camera_id=args.camera_id,
        labels_filename=args.labels_file,
        overwrite=args.overwrite,
    )

    if result.created:
        print(f"Success: {result.message}")
        print(f"Labels file: {result.labels_path}")
        if result.record:
            print(f"Record:      {json.dumps(result.record, separators=(',', ':'))}")
        print("\nThis helper creates local review evidence only. It does not")
        print("send alerts, train models, or publish warnings.")
    else:
        print(f"Error: {result.message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

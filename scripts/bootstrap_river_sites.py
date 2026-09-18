#!/usr/bin/env python3
"""Command-line helper to bootstrap validation sites from a river camera registry.

Issue #152: create or reuse sites for a river's cameras, download a
date-ranged image sequence for each (default: one daylight image per day,
nearest local noon), and enrich each sequence with USGS gage data. Always
run with --preview first to see what a run would do before downloading.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openfloodai.ingestion.river_bootstrap import preview_bootstrap_run, run_bootstrap
from openfloodai.ingestion.river_images import (
    DEFAULT_DAYLIGHT_WINDOW_END_HOUR,
    DEFAULT_DAYLIGHT_WINDOW_START_HOUR,
    RiverImageError,
)
from openfloodai.ingestion.river_registry import RiverRegistryError


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap validation sites and image sequences for a river's cameras."
    )
    parser.add_argument("--river", required=True, help="River id (e.g. colorado-river)")
    parser.add_argument("--start-date", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="End date, YYYY-MM-DD")
    parser.add_argument(
        "--sampling-mode",
        default="one_daylight_image_per_day",
        help="Sampling mode (default: one_daylight_image_per_day)",
    )
    parser.add_argument(
        "--camera",
        action="append",
        dest="cameras",
        default=[],
        help="Camera id to include; repeat to select several. Default: every registry camera.",
    )
    parser.add_argument(
        "--reference-dir",
        default="data/reference",
        help="Base directory holding rivers/<river>.json (default: data/reference)",
    )
    parser.add_argument(
        "--sites-dir", default="data/sites", help="Base directory for validation sites"
    )
    parser.add_argument(
        "--daylight-window-start-hour",
        type=int,
        default=DEFAULT_DAYLIGHT_WINDOW_START_HOUR,
        help=f"Daylight window start hour, local (default {DEFAULT_DAYLIGHT_WINDOW_START_HOUR})",
    )
    parser.add_argument(
        "--daylight-window-end-hour",
        type=int,
        default=DEFAULT_DAYLIGHT_WINDOW_END_HOUR,
        help=f"Daylight window end hour, local time (default: {DEFAULT_DAYLIGHT_WINDOW_END_HOUR})",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show what this run would do without downloading anything.",
    )
    parser.add_argument(
        "--replace-sequence",
        action="store_true",
        help="Replace an existing image sequence for a camera/date-range from scratch.",
    )
    parser.add_argument(
        "--replace-site-config",
        action="store_true",
        help=(
            "Not implemented by this script's normal workflow. Site configs are never "
            "modified automatically; edit a site's config file directly if you need to "
            "replace it, and confirm you mean to before doing so."
        ),
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not reuse already-downloaded images; only matters without --replace-sequence.",
    )

    args = parser.parse_args()

    if args.replace_site_config:
        print(
            "Error: --replace-site-config is not part of the normal workflow. "
            "Edit the site's config file directly if you are certain you want to replace it.",
            file=sys.stderr,
        )
        sys.exit(1)

    reference_dir = Path(args.reference_dir)
    sites_dir = Path(args.sites_dir)

    try:
        if args.preview:
            preview = preview_bootstrap_run(
                reference_dir=reference_dir,
                sites_base_dir=sites_dir,
                river_id=args.river,
                camera_ids=args.cameras,
                start_date=args.start_date,
                end_date=args.end_date,
                sampling_mode=args.sampling_mode,
                daylight_window_start_hour=args.daylight_window_start_hour,
                daylight_window_end_hour=args.daylight_window_end_hour,
            )
            print(json.dumps(preview.to_dict(), indent=2))
            return

        outcomes = run_bootstrap(
            reference_dir=reference_dir,
            sites_base_dir=sites_dir,
            river_id=args.river,
            camera_ids=args.cameras,
            start_date=args.start_date,
            end_date=args.end_date,
            sampling_mode=args.sampling_mode,
            replace_sequence=args.replace_sequence,
            resume=not args.no_resume,
            daylight_window_start_hour=args.daylight_window_start_hour,
            daylight_window_end_hour=args.daylight_window_end_hour,
        )
    except (RiverRegistryError, RiverImageError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps([outcome.to_dict() for outcome in outcomes], indent=2))
    if any(outcome.error for outcome in outcomes):
        sys.exit(1)


if __name__ == "__main__":
    main()

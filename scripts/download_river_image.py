"""Download four public USGS archive image slots into a local review folder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openfloodai.ingestion.river_images import DEFAULT_CAMERA_URL, download_river_images


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("datetime", help="Camera-local date and hour: YYYY-MM-DD HH or HH:00")
    parser.add_argument("--camera-url", default=DEFAULT_CAMERA_URL)
    parser.add_argument(
        "--timezone", default="", help="IANA timezone override, e.g. America/Denver"
    )
    parser.add_argument("-o", "--output", type=Path, default=Path("data/river-images"))
    args = parser.parse_args()
    try:
        result = download_river_images(
            camera_url=args.camera_url,
            local_hour=args.datetime,
            timezone_name=args.timezone,
            output_root=args.output,
        )
    except (ValueError, OSError) as error:
        parser.exit(1, f"Download failed: {error}\n")
    payload = result.to_dict()
    print(json.dumps(payload, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

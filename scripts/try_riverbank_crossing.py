"""Manual try-it-out script for the riverbank_crossing_v1 adapter (Issue #200).

Not wired into any pipeline or the console yet -- this is the fastest way to
run it against two real images from a site you already have. Edit the
CONFIG section below, then run:

    .venv/bin/python scripts/try_riverbank_crossing.py
"""

from __future__ import annotations

import cv2

from openfloodai.evidence.adapters.riverbank_crossing import RiverbankCrossingObservationAdapter

# --- CONFIG: edit these for your site --------------------------------------

BASELINE_IMAGE = (
    "data/sites/colorado-river-windy-gap/inputs/image-sequences/"
    "usgs-CO_Colorado_River_at_Windy_Gap_near_Granby-2026-08-01-2026-09-03-"
    "one_daylight_image_per_day/images/"
    "CO_Colorado_River_at_Windy_Gap_near_Granby___2026-08-01T18-00-11Z.jpg"
)
CURRENT_IMAGE = (
    "data/sites/colorado-river-windy-gap/inputs/image-sequences/"
    "usgs-CO_Colorado_River_at_Windy_Gap_near_Granby-2026-08-01-2026-09-03-"
    "one_daylight_image_per_day/images/"
    "CO_Colorado_River_at_Windy_Gap_near_Granby___2026-08-02T18-00-16Z.jpg"
)

# Copy a confirmed guide's "points" straight out of your site's config JSON
# (normal_waterline_guides[N].points) -- percentages of the frame, 0-100.
GUIDE_POINTS = (
    {"x": 6.875, "y": 39.3125},
    {"x": 14.21875, "y": 34.0625},
    {"x": 20.625, "y": 29.5625},
    {"x": 26.71875, "y": 26.3125},
    {"x": 31.09375, "y": 25.0625},
    {"x": 34.84375, "y": 21.8125},
    {"x": 36.875, "y": 20.8125},
)

# One point you'd expect to land in the water, as a percentage of the frame.
# This is the one new setting the adapter needs (see NormalWaterlineGuide's
# new `water_side_point` field) -- not yet saveable from the console UI.
WATER_SIDE_POINT = {"x": 50, "y": 60}

# ----------------------------------------------------------------------------


def main() -> None:
    baseline = cv2.imread(BASELINE_IMAGE)
    current = cv2.imread(CURRENT_IMAGE)
    if baseline is None or current is None:
        raise SystemExit("Could not read one of the configured image paths.")

    adapter = RiverbankCrossingObservationAdapter(
        site_id="try-it-out",
        camera_id="try-it-out",
        guide_id="try-it-out-guide",
        guide_points=GUIDE_POINTS,
        water_side_point=WATER_SIDE_POINT,
        previous_frame=baseline,
        current_frame=current,
    )
    record = adapter.collect()

    print(f"status:       {record.status}")
    print(f"value:        {record.value} {record.units}")
    print(f"reason_codes: {record.reason_codes}")
    print(f"quality:      {record.quality}")


if __name__ == "__main__":
    main()

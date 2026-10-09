# Measure Water Change From Masks

Measure how the **visible water area** changed between two images of one fixed camera, from two
water masks a person accepted. Evidence for human review only: not flood detection, not water
height, not flow speed, no alert. The full guide is `docs/learning/water-change-measurement.md`;
this page keeps the same metrics and limits.

## What is measured

For an ordered pair (earlier, later) inside the fixed watched area (the ROI the segmentation used):

- **Water fraction** of each image: water pixels ÷ ROI pixels.
- **Change in percentage points**: later − earlier, signed.
- **Newly wet** and **no longer wet** fractions: pixels that changed, ÷ ROI pixels. Equal totals in
  a different shape are therefore still visible.
- **Change per hour** (optional): an image-space area rate, not a level rise or speed.

One denominator (ROI pixels). Several detections in one result are combined with OR. Only pixels
inside the ROI are measured; a mask with water outside it is refused. Coordinates are original
image pixels, right and bottom edges exclusive. Brightness is never read.

## Unavailable, never zero

Missing, unreviewed, rejected, needs-correction or non-water masks; changed images; a different
camera, image size or watched area; reversed or equal timestamps; or unconfirmed framing give an
unavailable or invalid record with reason codes. An accepted "no match" is not a verified empty
mask. A named person confirms the fixed framing; there is no automatic camera alignment.

## Saved evidence

Each result is frozen once in `outputs/water-change-pairs/` with image and mask hashes, run and
result ids, review decision, configuration, calculation version and frozen gauge context. Original
runs are never modified. The adapter `water_change_mask_v1` is off by default.

## The pilot

10–15 diverse pairs from one camera (rising, falling, stable-high, equal area different shape,
difficult). Write the criteria first; two reviewers judge blind to machine results and gauge; then
measure, view the contact sheet and report; show frozen gauge context last; a person records
proceed, revise or stop. Errors and the unavailable rate are both reported, held-out pairs are
scored only on request and logged, and unknown-for-everything cannot pass. Commands are in
`scripts/water_change_pilot.py`.

## Compare any two images in Review

Optional, in Review: **Compare with another image…** next to the comparison view switch. Pick any
other saved image of the same camera (across sequences and runs, with thumbnails, exact times and
the mask state; the same file name in two sequences counts as two images). The existing Side by
side and Overlay views then show the two images **earlier then later**, whichever you picked first.

With accepted water masks on both and your confirmation that the view did not move, it shows
**Water coverage change**: coverage at each end, the signed change in percentage points, newly wet
and no longer wet areas, an image-space rate, and a picture of where water arrived and left. If a
number is not possible (missing, unreviewed or rejected mask, different watched area or size, equal
times, unconfirmed view) you still see the images with a plain reason. It is separate from the
run's Pixel appearance change score and never combined with it. Viewing writes nothing and starts
no segmentation; **Save this comparison** is a separate, explicit button that never overwrites an
earlier result. Closing returns you to the same image, filters and scroll position.

## Limits

Image-space area only; hosted masks with no editor; person-confirmed framing; a few pairs from one
camera cannot show accuracy. No training, alerts, risk-engine wiring, public upload, extra baseline
lines or gauge-height regression are part of this.

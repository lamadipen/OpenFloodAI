# Measure Water Change From Masks

OpenFloodAI can measure how the **visible water area** changed between two images of one
fixed camera, using two water masks that a person accepted. It is evidence for human review.
It is **not** flood detection, **not** physical water height, and **not** flow velocity, and it
sends no alert.

The measurement is the first test of a visual-first idea: judge change from what the camera
shows, relative to a watched area a person drew, and use gauge data only afterwards as outside
context. Whether the idea works is decided by a small pilot (below), not assumed.

## What it measures

For an explicitly ordered pair (earlier image, later image) inside the fixed **watched area**
(the "ROI", the same rectangle the segmentation was run on):

| Number | Meaning |
| --- | --- |
| Water fraction (each image) | water pixels ÷ ROI pixels |
| Change in percentage points | later fraction − earlier fraction, signed (positive = more water) |
| Newly wet fraction | pixels dry in the earlier mask and wet in the later one ÷ ROI pixels |
| No longer wet fraction | pixels wet in the earlier mask and dry in the later one ÷ ROI pixels |
| Changed fraction | newly wet + no longer wet, whatever the direction |
| Change per hour (optional) | change in percentage points ÷ elapsed hours |

Rules that matter:

- **One denominator.** Every fraction is divided by the ROI pixel count, so the parts add up:
  the change in percentage points always equals newly wet minus no longer wet.
- **Equal area is not no change.** If water moves from the left to the right bank the net change
  is 0 but newly wet and no longer wet are both large. Both are kept.
- **Union and overlap.** If one saved result has several detections, their masks are combined with
  a logical OR; overlapping pixels count once.
- **Valid domain.** Only pixels inside the ROI are measured. A mask with water outside the ROI
  does not belong to this watched area and the pair is refused rather than clipped.
- **Coordinates.** Masks and the ROI are in original image pixels, `[x0, y0, x1, y1)`, right and
  bottom edges exclusive. The ROI is the crop that the hosted segmentation recorded.
- **The rate is image-space.** It is a rate of change of visible area, not a rise in water level
  or a speed. Two endpoints cannot show a peak in between.
- **Masks only.** Brightness is never read, so a lighting change with unchanged masks measures zero.
  (`riverbank_crossing_v1` and `pixel_change_region_v1` still measure pixel appearance change and
  keep that meaning. They are not renamed, reinterpreted or moved into a quality family.)

## When a pair is unavailable

A missing, unreviewed, rejected, needs-correction or non-water mask, a changed source image, a
different camera, image size or watched area, reversed or equal timestamps, an unreadable file, or
framing that nobody confirmed all produce an **unavailable** or **invalid** record with reason
codes. The value is empty, never zero. An accepted "no match" result is not a verified empty
mask either: it means the provider found nothing, not that the area is dry.

Framing is confirmed by a named person for this pilot. The software does not align cameras and
makes no claim that it does; every available record says so.

## What is saved

Each measurement is frozen once under the site folder in
`outputs/water-change-pairs/<pair_key>.json`: the evidence record, both image hashes, mask
hashes, the segmentation run and result ids, review decision and time, configuration hash,
watched area, calculation version and the frozen matched gauge context. The key changes when the
review decision or mask changes, so a later rejection never silently reuses an old number.
Original runs, reviews and masks are never edited. Running the same pair again returns the saved
result.

The adapter is `water_change_mask_v1` (observation family). It is registered but **off by
default**.

## The one-camera pilot

The pilot tests feasibility on 10–15 diverse pairs from one fixed camera: rising coverage, falling
coverage, stable coverage at a high level, equal area in a different shape, and difficult or
unavailable cases. It is not an accuracy study.

1. **Inventory.** `python scripts/water_change_pilot.py inventory` lists accepted water masks by
   camera and watched area (read-only). Paid segmentation needs separate explicit approval and a
   spending ceiling; nothing here starts it.
2. **Write the criteria first** in `criteria.json`: the tolerance for "about the same",
   minimum pairs, maximum unavailable rate, minimum agreement with the reviewers, how close to
   human-to-human agreement the machine must be, and the stop conditions. Who wrote it and when
   is recorded; its hash is stored with every measurement.
3. **Choose the pairs** in `pairs.json` (one site folder, each pair a `case_type`, a person who
   confirmed the framing, and `held_out` for pairs reserved for the end).
4. **Judge blind.** `blind-sheet` writes images only. A hydrologist or reviewer and a second person
   each fill `judgments/<name>.json` saying whether the later image shows more, less or about the
   same visible water (or `cannot_judge`), before seeing machine results or gauge values. Files
   dated after the first measurement, or not marked blind, are set aside.
5. **Measure** (`measure`), view the contact sheet (`sheet`: images, masks, spatial overlay,
   numbers, reasons), then `report`.
6. **Gauge context comes last**, from the readings frozen at run time with the existing ±15 minute
   match rule. Disagreement is flagged for investigation. Image area need not track gauge height
   in a straight line, and a nearby station does not prove the same water level at the camera.
7. **Record a decision** (`decision`): proceed, revise or stop, by a named person with reasoning
   and known limitations.

The report lists errors **and** the unavailable count and rate. A system that answers "unknown"
for everything cannot pass. Held-out pairs are measured and scored only when asked for, and every
such request is logged; do not tune on them.

## Limitations

- Image-space area only. Narrow or deep channels can change height with little visible area change.
- Masks come from a hosted model that a person accepted. Errors beside the bank can reverse a
  small change, and there is no mask editor yet.
- Fixed framing is confirmed by a person, not detected.
- A handful of pairs from one camera cannot establish accuracy, and nothing here supports a
  production or warning claim.

Out of scope: training, alerts, risk-engine wiring, public upload, extra baseline lines and
gauge-height regression. Selecting any two images in the review screen and charting these numbers
are separate follow-ups.

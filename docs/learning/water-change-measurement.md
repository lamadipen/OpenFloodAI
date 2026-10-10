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
codes. So does a mask that was cut from a different watched area than the one the run froze: each
mask records the crop it was made with, and it is compared with the crop the run's own frozen
watched area gives for that image size. A smaller or stale region would otherwise be measured
against the wrong area and still return a number, so such a mask is **invalid**
(`…_MASK_WATCHED_AREA_DIFFERS_FROM_RUN`), and a run with no recorded watched area leaves the mask
unverifiable (`…_WATCHED_AREA_NOT_VERIFIABLE`). The Review chart applies the same check to every
point. The value is empty, never zero. An accepted "no match" result is not a verified empty
mask either: it means the provider found nothing, not that the area is dry.

Framing is confirmed by a named person for this pilot. The software does not align cameras and
makes no claim that it does; every available record says so.

## What is saved

Each measurement is frozen once under the site folder in
`outputs/water-change-pairs/<pair_key>.json`: the evidence record, both image hashes, mask
hashes, the segmentation run and result ids, review decision and time, configuration hash,
watched area, calculation version and the frozen matched gauge context. The key changes when the
review decision or mask changes, and also when the image's human review changes: its revision, time
and camera and visibility answers. So a later rejection, or marking the camera as moved, never
silently reuses an old "available" number; it makes a new result and the old one is kept as it was.
The key also records whether each original image is still present and unchanged right now. Delete or
change an image and the same pair gives a new, unavailable result (`…_SOURCE_MISSING` or
`…_SOURCE_CHANGED`) instead of replaying the saved one; put the identical file back and the original
result is valid and reused again.
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
   confirmed the framing, and `held_out` for pairs reserved for the end). The pairs, their
   references and the held-out marks are **frozen** into `pairs.frozen.json` with a hash the first
   time anything uses them (the blind sheet, a judgments export or a measurement), so always before
   the first measurement. After that, a changed `pairs.json` is refused, every measurement records
   the pairs hash it ran under, and the report takes the held-out split from the frozen file. An
   edited `pairs.json`, a measurement under other pairs, or no frozen file is reported as a protocol
   problem. To change the pairs, start a new pilot folder. The pairs must also keep the final check
   independent: the same two images cannot appear twice (under another name or in the other order),
   and no image may be used by both a development pair and a held-out pair. Sharing an image between
   two development pairs, or between two held-out pairs, is allowed.
   Images are compared by identity, not by file name: the checksum their run froze. Two different
   sequences that both hold `frame-001.jpg` are different images, and one image reused by several
   runs is still one image. An image that cannot be identified (a run or file missing from the frozen
   inputs) is never treated as equal to another. The frozen pairs file records each end's identity.
4. **Judge blind.** `blind-sheet` writes images only. A hydrologist or reviewer and a second person
   each fill `judgments/<name>.json` saying whether the later image shows more, less or about the
   same visible water (or `cannot_judge`), before seeing machine results or gauge values. Files
   dated after the first measurement, or not marked blind, are set aside. You can also collect the judgments on the focused review page and export them: label each pair's later image against the earlier one in blind mode, then run `python scripts/water_change_pilot.py judgments --pilot-dir <dir> --reviewer <your code>`. Only blind labels are exported; informed labels (made with machine evidence in view, for example in Assisted review) and unlabelled pairs are listed and left out.
5. **Measure** (`measure`), view the contact sheet (`sheet`: images, masks, spatial overlay,
   numbers, reasons), then `report`.
6. **Gauge context comes last**, from the readings frozen at run time with the existing ±15 minute
   match rule. Disagreement is flagged for investigation. Image area need not track gauge height
   in a straight line, and a nearby station does not prove the same water level at the camera. A gauge
   change is only computed when both ends have the same station, the same measurement type
   (parameter) and the same unit; if any of these differs or is not recorded, the comparison is shown
   as unavailable instead of subtracting unlike readings.
7. **Record a decision** (`decision`): proceed, revise or stop, by a named person with reasoning
   and known limitations.

The report lists errors **and** the unavailable count and rate. A system that answers "unknown"
for everything cannot pass. Held-out pairs are measured and scored only when asked for, and every
such request is logged; do not tune on them.

## The Review chart: pixel change or water coverage

The second chart in **Review** plots one number per image over time. A **Measurement** switch above it
has two choices, and a short explanation under the switch says what the current one means. The choice is
remembered in your browser, and nothing changes until you use it.

- **Pixel appearance change** (default; the original "Region change score"). How different the watched
  area looks from the baseline image, from pixel brightness. Anything that changes the picture raises it:
  water, but also light, shadow, snow or a moved camera.
- **Segmentation: water coverage.** For each image, the share of your watched area that the segmentation
  marks as water, in percent. A higher point means more of the watched area is water in that picture, so
  the line shows how visible water changes from image to image. It measures the picture, not water depth
  or flow.

Water coverage rules:

- **Filled and hollow points.** A filled point uses a water mask a reviewer accepted. A hollow point uses
  an unreviewed draft mask, so you can see the line as soon as segmentation has run and still tell
  accepted from draft. Accepting a mask fills its point at once. Rejected, needs-correction, riverbank and
  "no match" results are never plotted.
- **No point means no mask, not zero.** An image without a usable mask is simply missing from the line,
  and the button shows how many images have one (for example `6/8`). If nothing can be plotted the chart
  says what to do.
- **Same watched area.** Each mask must have been cut from the watched area your run froze, and all must
  share one image size; any that do not are left out, so a whole set from an older, smaller region is
  not trusted just because it agrees with itself.
  The chart cannot detect a camera that moved, so treat it as a screening view and use **Compare with
  another image** for a pair you confirm yourself.
- **Separate numbers.** The two measurements are never combined or substituted for each other. The
  selected-image line shows both, and marks a draft.
- **Getting masks.** Use the checkbox beside Run validation or the Segmentation panel under the image.

## Compare any two images in Review

In **Review**, the selected image has a **Compare with another image…** button beside the
comparison view switch. It is optional, and nothing about ordinary review changes.

1. **Choose the other image.** A compact picker lists the other saved images of the same
   camera, across sequences and runs, with a thumbnail, exact capture time, a mask state
   (accepted, not reviewed, rejected, needs correction, none) and a note when the image's sequence
   has no saved run. Filter by sequence, dates, or "only images with an accepted mask". The same
   file name in two sequences is two different images and is listed twice.
2. **Read it in the views you already use.** The existing **Side by side**, **Overlay** and **Both**
   switch now shows the two chosen images. They are always shown **earlier then later**, with exact
   times and the gap between them, whichever image you picked first.
3. **Water coverage change.** When both images have an accepted water mask, the screen shows the
   coverage of the watched area at each end, the signed change in percentage points, how much is
   newly wet and no longer wet, an image-space rate per hour, and a picture of where water arrived
   (blue) and left (red). It uses the same calculation as this page's measurement above, with the
   same limits.
4. **You confirm the framing.** Same camera does not prove the view did not move, and the software
   does not align cameras. Tick the confirmation to get numbers.
5. **When a number is not possible, you still see the images.** A missing, unreviewed or rejected
   mask, a different watched area or image size, equal capture times, or an unconfirmed view each
   show a plain reason and no number. Nothing is substituted, and the run's **Pixel appearance
   change** score is a separate number that is never combined with this one.
6. **Viewing writes nothing.** No label, baseline, dataset membership or saved run changes, and no
   segmentation, paid call or upload starts. **Save this comparison** is a separate, optional
   button. It keeps the exact image, mask and calculation references once and never overwrites an
   earlier result.
7. **Close** returns you to the same image, filters and scroll position. Selecting another image
   also ends the comparison.

Not included: comparing different cameras, automatic pairing, training, alerts and risk decisions.

## Limitations

- Image-space area only. Narrow or deep channels can change height with little visible area change.
- Masks come from a hosted model that a person accepted. Errors beside the bank can reverse a
  small change, and there is no mask editor yet.
- Fixed framing is confirmed by a person, not detected.
- A handful of pairs from one camera cannot establish accuracy, and nothing here supports a
  production or warning claim.

Out of scope: training, alerts, risk-engine wiring, public upload, extra baseline lines and
gauge-height regression. Cross-camera comparisons are out of scope.

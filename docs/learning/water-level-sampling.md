# Sample Images By Water Level

Reviewing every image in a month or a year is slow. **Sample by water level**
uses a camera's linked USGS gauge to propose a small set of low, middle, and high
water images, so a reviewer can start with useful variety. It builds on the
existing image download, analysis, and review workflow. It does not replace
regular sampling, which is unchanged.

## What the groups mean

Low, middle, and high are **collection groups, relative to one station and the
date range you chose**. They are not flood thresholds, human labels, or machine
observations.

- High does not mean flooding. Low does not mean a dry river. Middle does not mean
  normal or safe.
- A nearly flat period has no meaningful low or high. The tool says so instead of
  inventing groups.
- A very short date range gives little contrast.

A collection group is why an image was sampled. It is shown separately from the
machine's result and from any human label, and it never creates a label.

## Use it

1. Open **Add media** for a site, choose **Images**, and set the start and end
   dates and the camera.
2. Choose **Sample by water level** (instead of Regular sampling).
3. Tick Low, Middle, and/or High, and set **Images per group** (default 3,
   at most 10).
4. Choose the **time of day**: **Any time of day** (the default) or **Daytime
   only**, which keeps both the gauge reading and the image inside the local
   10:00 to 14:00 window, the same daylight window regular daylight sampling uses.
   Changing it (or the groups, images per group, dates, or camera) clears the
   preview and the confirmation, so run Find samples again.
5. Select **Find samples**. This reads the gauge data, ranks the readings, and
   then checks the camera archive only around the readings it is considering, one
   day at a time, until each group has its picks. It never lists or downloads the
   whole period, and **it downloads no images.**
6. Review the preview. Each row shows the group, the gauge reading time, gauge
   height and unit, USGS quality (provisional readings are marked), the image time,
   and the exact gap between them.
7. Untick a row to leave it out, or select **Replace** to get another candidate
   for that group. A replacement keeps the group's other rows, respects the same
   rules, and never uses an image hours away.
8. Tick the confirmation and select **Download N selected images**. Only the
   approved rows are downloaded, through the existing image-sequence intake. The
   server checks them against what you asked for (groups, and no more than the
   requested images per group) before it fetches anything.

If you ask for more than can be found, the preview shows how many it found and
why. Requested counts are maximums, not guarantees.

## What it needs

- The camera URL must be the camera this site is set up for. The images, the
  gauge station, and the saved gauge data all follow that one camera. If the URL
  names a different camera, Find samples and Download are refused before anything is
  fetched.

- The camera must have a USGS gauge association from the river registry. The
  nearest station is never guessed. A gauge the registry marks `nearby` is
  allowed, with USGS's note shown.
- The station must report **gauge height**. If it only reports flow (discharge),
  water-level sampling is unavailable. Flow is never used in place of height.
- Readings use the same rules as run evidence: only valid, finite, non-no-data
  readings, with USGS qualifiers kept. The image must be within **15 minutes**
  (inclusive) of the reading, and the window is never widened.

## Selection policy `water-level-sampling-v1`

The same inputs always give the same picks. The policy version is saved with
every selection.

| Rule | Behavior |
| --- | --- |
| Group bands | Computed once from all valid readings in the range by nearest rank (no interpolation). Low: at or below the 20th percentile and below the median. High: at or above the 80th and above the median. Middle: between the 40th and 60th percentile. |
| Ranking | Low from the lowest up. High from the highest down. Middle by distance from the **median**, not the mean. Equal values go to the earlier reading. |
| Limited variation | If the range is under 0.20 ft, no group is filled. |
| Spacing | A group never takes two readings fewer than 3 local calendar days apart. This is a spacing rule, not a claim of independent events. |
| Image match | The image nearest the reading within 15 minutes, an equal distance going to the earlier image. |
| Re-check | The image's **own** nearest reading must also fall in the group. Both readings are saved when they differ, and the group reflects the image's own reading. |
| Time of day | **Any time** (default) changes nothing. **Daytime only** keeps a candidate only if its gauge reading and its image are both within 10:00 to 14:00 on the camera's local clock (ends included, daylight saving handled). The group bands are still set by all readings in the range, so a night-time peak still shapes what "high" means; it just is not sampled. If no reading in a group is in the window, the group is a shortfall, not a night-time pick. The choice is saved with the request. |
| Uniqueness | An image is chosen once and never fills two groups. Groups fill in the order low, middle, high. |
| Shortfall | A group that cannot reach its count is reported, never padded with unsuitable duplicates. |
| Archive checks | Only days around candidate readings are listed (at most 300 separate days per search). If many top readings have no usable image, the search stops and says so. |

## After the download

The sample set is saved as an ordinary image sequence (mode `water_level`) with
`water-level-selection.json` beside it. It records the camera/station association
and its source, the date range and groups requested, the policy version and
selection time, the gauge parameter and units, every approved image with its
motivating reading and its own nearest reading and both gaps, the images you
declined, and the reasons candidates were skipped. That file is never rewritten by
a later download. Each sample set is saved under its own name, ending in a short
fingerprint of its approved images (for example `...-water_level-3f91d374`), so a
different selection for the same camera and dates is a new sequence and never
replaces an earlier one that runs and reviews may already use. Downloading the
exact same approved images again simply reuses what is saved.

Then use the normal flow:

1. **Choose a baseline.** A water-level sample set has no assumed "normal" first
   image, so a run requires you to pick the baseline explicitly.
2. Reuse the site's watched area and riverbank guides, run the analysis, then
   review and label as usual. If the camera view changed, set the area and
   guides up again instead of reusing them.
3. In **Review**, the selected image shows its collection group, the reading that
   motivated it, and its own nearest reading. Each run keeps its own frozen copy of
   this record.

## Overlay comparison

Review also has an **overlay comparison** next to the side-by-side view. Slide
to blend the selected image over the baseline, and toggle the watched area and
guides, which are the ones saved with that run. It assumes the camera did not
move: if the two images differ in size, or the landmarks do not line up, treat
the overlay as not aligned. It never changes the baseline, a guide, or a past
run, and it is not a measured water height.

## Limits

- Pixel change and overlays are not proof of rising or falling water, and image
  comparison is not a calibrated height measurement.
- Before/during/after sampling around one event is not part of this version.
- Weather, lighting, and other hard-case sampling are separate future work.

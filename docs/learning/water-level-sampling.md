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
8. Choose the **destination** (see below), read the summary of what will happen,
   tick the confirmation, and select the button. Only the approved rows are
   downloaded. The server checks them against what you asked for (groups, and no
   more than the requested images per group) before it fetches anything.

If you ask for more than can be found, the preview shows how many it found and
why. Requested counts are maximums, not guarantees.

## What it needs

- Images and the gauge station both come from the camera in the URL (the USGS camera id),
  so they always belong together. A site's own camera id is an internal label and does
  not have to equal it: if it differs, the preview notes that the images will be saved as
  the URL's USGS camera. A site that already holds images from one USGS camera refuses
  images from another, so one site never mixes cameras.
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
| Date edges | Group bands and ranking use only the readings inside your date range. Finding an image's own nearest reading also uses the readings just outside the range, so an image at 00:01 is matched to the 23:59 reading the night before, not to a farther reading inside the range. An image outside the date range is never chosen. |
| Re-check | The image's **own** nearest reading must also fall in the group. Both readings are saved when they differ, and the group reflects the image's own reading. |
| Time of day | **Any time** (default) changes nothing. **Daytime only** keeps a candidate only if its gauge reading and its image are both within 10:00 to 14:00 on the camera's local clock (ends included, daylight saving handled). The group bands are still set by all readings in the range, so a night-time peak still shapes what "high" means; it just is not sampled. If no reading in a group is in the window, the group is a shortfall, not a night-time pick. The choice is saved with the request. |
| Uniqueness | An image is chosen once and never fills two groups. Groups fill in the order low, middle, high. |
| Shortfall | A group that cannot reach its count is reported, never padded with unsuitable duplicates. |
| Archive checks | Only days around candidate readings are listed (at most 300 separate days per search). If many top readings have no usable image, the search stops and says so. |

## Destination: a new sequence, or add to an existing one

**Create new sequence** (the default) makes a fresh sequence from the approved images.
Every request gets its own generated ID, such as `...-water_level-3f91d374`, even if
you repeat exactly the same request, so nothing is ever replaced or overwritten.

- **Sequence name (optional).** The generated name is shown. Leave the box blank to
  keep it. A name you type is only a display label: it is shown in the sequence list,
  the destination picker, and the review header, with the generated ID underneath.
  It is never a file or folder name and never replaces the ID, so two sequences with
  the same name stay distinguishable. Names can be up to 80 characters, without
  control characters. Older sequences have no name and keep showing their ID.

**Add to existing sequence** appends the approved images to a sequence you already
have, without making a separate one.

- Only sequences from the same site and the same camera are offered. The server checks
  this again: the camera, the time zone, the source, the gauge station and parameter,
  and that every saved local time matches the time zone. A sequence that cannot take
  the images is listed under "Not available" with the reason, and is never mixed in.
- Before anything changes, you see the plan, for example: "Add 8 new images to Windy
  Gap 2026. Skip 3 already present. Existing images and previous runs will remain
  unchanged." You confirm those exact numbers; if they change before you press the
  button, the request is refused and you review again.
- **Duplicates** (the same archive image, already saved with the same size) are
  skipped. If every image is already there, nothing at all is written: no new batch,
  no manifest entry.
- **Conflicts** are reported, never overwritten or renamed: another image with the
  same capture time from a different source, or a saved file with the same name but
  different content. Conflicting images are not added; the rest of the batch is.
- Images with different times on the same day stay separate.
- Changing the destination, the groups, the count, the time of day, the dates, or the
  camera clears the preview and your confirmation.
- A failed add changes nothing: its gauge readings, summary and saved matches are staged
  and only applied after the image list is committed, so a run made after a failed add
  sees exactly the gauge data it had before.
- Retrying is safe. If an add is interrupted, the sequence's list of images is never
  left pointing at a missing file, and the retry reuses files already downloaded
  instead of duplicating them. If another add or a validation run is using the
  sequence at that moment, the add waits briefly for it.

New images start **unreviewed**. Nothing is run, labeled, or re-matched automatically.
After the add, the page shows the result and a link to Sequences & runs, where you can
run validation when you are ready.

## What is saved

A sequence keeps one saved record per download batch in `sampling-batches/`
(`batch-0001.json`, `batch-0002.json`, ...). Each batch records the camera and station
association and its source, the date range and groups requested, the policy version
and selection time, the thresholds, the gauge parameter and units, every image it
added with its motivating reading, its own nearest reading and both gaps, the images
you declined, the reasons candidates were skipped, and the duplicates, conflicts and
failed downloads of that batch. A batch file is never rewritten.

- **Low, middle, and high are relative to that batch's date range**, not to the whole
  sequence. A later batch does not change an earlier batch's thresholds, and an image
  stays in the category of the batch that first added it, even if a later batch picks
  the same image again.
- **Gauge readings:** each batch's readings are added to the sequence's gauge data
  without changing any reading already saved, even if USGS has since revised it. An
  earlier image's matched gauge evidence therefore does not change when you append.
- Each new image keeps its own capture time and its own nearest reading within 15
  minutes, with the station association, units and quality flags.
- **Each image's gauge match is saved once**, in `gauge-matches.json`, when the image is
  added: a new image keeps exactly the reading its preview showed, and images already
  in the sequence are frozen at the match they have just before the first append.
  Later runs reuse these saved matches instead of matching again, so a closer reading
  brought in by a later batch can never change an earlier image's match. Saved matches
  are only ever added to.

## Runs and history

A validation run first holds the sequence while it reads it, so it never sees an add
half finished. If an earlier add was interrupted, the run first repairs it under that
same hold: a batch record whose images were committed is finalized (otherwise it is
discarded) and the sequence summary is refreshed, so the run never freezes an image
without its sampling history. It then freezes everything it used in its own folder: the image list,
the gauge data and matches, the sampling batches, the watched area and guides, and the
sequence's display name.

- A run made **before** an add keeps showing exactly its original images, gauge
  matches, categories and results. New images never appear in an older run.
- A run made **after** an add gets a new run ID and includes the new images. Earlier
  images keep the same gauge matches they had.
- Because a water-level sequence has no assumed "normal" first image, a run always
  needs you to choose the baseline, including after an add. Your earlier choice, the
  watched area, the guides and any labels are not changed by an add.

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

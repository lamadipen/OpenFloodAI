# Sample Images By Water Level

Reviewing every image in a month or a year is slow. **Sample by water level** uses a
camera's linked USGS gauge to propose a small set of low, middle, and high water
images, so a reviewer can start with useful variety. It builds on the existing image
download, analysis, and review workflow. Regular sampling is unchanged.

The full, current guide is `docs/learning/water-level-sampling.md`. This page keeps the
same workflow and rules for the classic documentation.

## What the groups mean

Low, middle, and high are **collection groups, relative to one station and the date
range you chose**. They are not flood thresholds, human labels, or machine
observations. High does not mean flooding, low does not mean a dry river, and middle
does not mean normal or safe. A nearly flat period has no meaningful groups, and the
tool says so instead of inventing them.

## Use it

1. Open **Add media** for a site, choose **Images**, and set the dates and camera.
2. Choose **Sample by water level**.
3. Tick Low, Middle, and/or High, set **Images per group** (default 3, at most 10), and
   choose **Any time of day** or **Daytime only** (10:00 to 14:00 local).
4. Select **Find samples**. This reads the gauge data and checks the camera archive
   only around the readings it considers. It downloads no images.
5. Review the preview: group, gauge reading time, height, unit, USGS quality
   (provisional is marked), image time, and the exact gap (within 15 minutes). Untick
   a row or select **Replace** for another candidate.
6. Choose the destination, read the summary, tick the confirmation, and select the
   button. Only approved rows are downloaded, after the server re-checks them.

## Destination: a new sequence, or add to an existing one

- **Create new sequence** (default) always makes a new, uniquely generated ID, even for
  a repeated request. You may add an optional **Sequence name**. It is only a display
  label shown in lists, the destination picker and review, with the ID underneath. It
  is never a path and never replaces the ID. Blank keeps the generated name.
- **Add to existing sequence** appends only new images to a sequence from the same site
  and camera. The server checks camera, time zone, source, gauge station and
  parameter, and timestamp consistency, and lists any sequence it excludes with the
  reason. You see and confirm the plan first, such as "Add 8 new images to Windy Gap
  2026. Skip 3 already present."
- Exact duplicates are skipped. If everything is a duplicate, nothing is written.
  Conflicts (same capture time from another source, or the same file name with
  different content) are reported and never overwritten or renamed.
- New images start unreviewed. Nothing is run or labeled automatically.

## What is saved, and history

- Each download batch is saved in `sampling-batches/` and never rewritten. Low, middle
  and high are relative to that batch's date range; a later batch does not change an
  earlier batch's thresholds or categories.
- Gauge readings are only added for new timestamps. Readings already saved, and the
  matches for earlier images, are not changed.
- A validation run reads the sequence under a lock and freezes its images, gauge
  matches, sampling batches, watched area, guides and the sequence name. An older run
  never shows newly added images. A new run after an add includes them.
- A water-level sequence needs you to choose the baseline for each run.

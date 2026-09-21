# Colorado River Validation Sample Pilot

This page explains how the Colorado River pilot dataset (issue #152) is built and tracked. It covers the tools, the files they produce, and how the data moves from a first download to something we trust for validation.

Simple meaning: we download real river-camera images and matching water-level data, a person reviews and confirms what they show, and only reviewed data is trusted for validation.

## Why This Exists

Video samples for validation are hard to find. USGS already runs public, timestamped river cameras with matching water-gage data. This pilot checks whether that combination can become a second, steady source of validation data alongside videos, without slowing down or changing the existing video workflow.

## Scope Of The Pilot

The pilot starts small on purpose:

- Three cameras: Windy Gap, Cameo, and Cisco.
- One selected image per local day, nearest local noon, inside a daylight window (default 10:00 AM-2:00 PM).
- A few months of data, not years, until the pilot proves useful.

Simple example: for one camera, one day might have images at 9:45 AM, 11:45 AM, 12:15 PM, and 4:00 PM. Only 12:15 PM is selected, because it is closest to noon and inside the daylight window. A day with no image inside the window is recorded as missing, never replaced with a nighttime image.

More cameras and longer date ranges come later, only after this pilot passes its review (see "Pilot Success Gate" below), and only after the plan's already-approved decisions on it.

## Camera Registry

```text
data/reference/rivers/colorado-river.json
```

This file is the list of Colorado River cameras and the single source of truth for grouping sites by river. It only includes cameras USGS marks visible (`hideCam` is not true). Each camera record includes:

```json
{
  "camera_id": "CO_Colorado_River_near_Cameo",
  "nwis_id": "09095500",
  "folder_name": "colorado-river-cameo",
  "timezone": "America/Denver",
  "gage_relationship": "same_site"
}
```

Simple meaning: `folder_name` says where the site lives under `data/sites/`, `nwis_id` says which USGS water-gage to read, and `gage_relationship` says how directly that gage applies to this exact camera (`same_site`, `nearby`, or `unavailable`; a `nearby` gage always includes a short explanation).

This file is committed to the repository, because it is small, reusable, and has no images in it.

## Running A Bootstrap

```bash
python3 scripts/bootstrap_river_sites.py \
  --river colorado-river \
  --start-date 2026-06-18 \
  --end-date 2026-09-16 \
  --sampling-mode one_daylight_image_per_day \
  --camera CO_Colorado_River_at_Windy_Gap_near_Granby \
  --camera CO_Colorado_River_near_Cameo \
  --camera UT_Colorado_River_near_Cisco \
  --preview
```

Always run with `--preview` first. It reports what a real run would do (cameras included, timezone, image counts, missing days, estimated download size, gage relationship, and any existing-site conflict) without downloading anything.

Drop `--preview` to run for real. Each camera then gets:

1. A validation site under `data/sites/<folder_name>/`, created only if it does not already exist. If a site with that folder name already exists with the *same* camera ID, it is reused as-is; nothing manual is overwritten. If it exists with a *different* camera ID, that one camera is skipped and reported as a conflict, and the rest of the batch continues.
2. A downloaded, sampled image sequence under that site's `inputs/image-sequences/` folder.
3. A `gauge-readings-summary.json` next to the images, built from the matching USGS gage.

Camera archive coverage is not always continuous. Some cameras have real gaps of months, where USGS has no recorded images at all. Always check `--preview` before picking a date range, rather than assuming a range has data.

Re-running the same camera and date range reuses already-downloaded images and only fetches what is missing or previously failed, instead of starting over. Use `--replace-sequence` to force a full re-download instead. `--replace-site-config` is intentionally not part of the normal workflow; edit a site's config file directly if you are sure you want to replace it.

## What Gets Downloaded Per Camera

Inside `data/sites/<folder_name>/inputs/image-sequences/<sequence_id>/`:

- `images/`: the selected JPEG images.
- `sequence-manifest.jsonl`: one row per selected day, with its filename, capture time, and download status (`downloaded`, `missing`, or `failed`).
- `download-summary.json`: totals for the run (how many downloaded, missing, failed).
- `gauge-readings-summary.json`: the matching USGS gage data for the same date range, including the highest and lowest readings, the largest 6/12/24-hour rises and falls, and the image nearest each of those moments. If gage data is not available, this file still gets written with `available: false` and a plain reason; a gage problem never blocks the image download.

None of this is committed to the repository. Raw images, per-sequence manifests, and gage summaries stay local. Share a reviewed dataset through an external drive, not through Git.

## Manual Site Setup

Bootstrapping only creates the site and downloads images. Someone still needs to, once images are downloaded:

1. Draw a watched area (`reference_region`) for the site.
2. Trace the normal riverbank guide (`normal_waterline_guides`).
3. Pick a clear normal-condition baseline image.

These are saved in the site's own config file, e.g. `data/sites/colorado-river-cameo/configs/colorado-river-cameo.json`, and are never touched by re-running the bootstrap script.

## Dataset Groups

Every image starts in `development_candidate`. After a period of a site's data is reviewed, it can move into one of:

- `practice`: safe to use for trying out validation, not locked for scoring.
- `locked_validation`: trusted, and not expected to change.
- `excluded`: reviewed and found unsuitable (e.g. camera moved, chronic glare).

Assignments cover a date range for one site, not individual images, and two assignments for the same site can never cover overlapping dates. Never split neighboring days from the same event between `practice` and `locked_validation`; prefer keeping a whole camera or period in one group when there are enough sites to choose from.

Simple example:

```text
Cameo, January-February 2025 -> practice
Cameo, March 2025            -> excluded (same camera already in practice)
Cisco, January-March 2025    -> locked_validation
```

Assignments live in `data/sites/<folder_name>/dataset-groups.jsonl`, one line per assignment, and are set with `assign_dataset_group()` in `src/openfloodai/review/dataset_groups.py`.

## Pilot Success Gate

Before expanding to more cameras or a longer date range, check that:

- Most selected images are daylight and readable.
- Camera framing stays stable across the period.
- The watched area and riverbank guide stay meaningful the whole time.
- Image and gage timestamps line up.
- Download resume and retry actually work.
- Storage size is reasonable.
- A human reviewer can understand the machine's results.
- The dataset has useful normal, changed, and difficult examples.

## Expansion Plan

Only after the pilot passes:

1. Expand the three pilot cameras to a full year.
2. Review storage, missing days, and seasonal quality.
3. Expand to all ten visible Colorado River cameras.
4. Keep using user-provided dates for each run.
5. Lock suitable sites or periods for validation.
6. Keep adding approved videos independently, unaffected by any of this.
7. Publishing this dataset publicly (e.g. Hugging Face or Kaggle) is a separate future issue, with its own review for attribution, license, privacy, and hosting cost, once the local dataset is stable.

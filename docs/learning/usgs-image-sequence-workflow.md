# USGS Image-Sequence Workflow

Use this workflow to download a sampled, timestamped sequence of public USGS
HIVIS/NIMS still images into one site, for reviewing river conditions across
days, weeks, or seasons.

**This is not the video validation flow.** It is a separate, parallel path
for timestamped observation and future image validation. It does not change
video intake, labels, the manifest, or `Run validation` — none of those read
or depend on anything downloaded here.

## Use The Home UI

1. Start the existing server with `python3 scripts/run_openfloodai_home_ui.py`,
   or open the desktop app.
2. Open Home, switch to **Guided workflow**, select a site, and start the
   **USGS image sequence** step.
3. Paste a USGS HIVIS camera page URL, such as
   `https://apps.usgs.gov/hivis/camera/CO_Colorado_River_near_Cameo`.
4. Enter a start date and end date, both in the camera's local time. Leave
   timezone blank to let the camera's known zone be discovered automatically.
5. Choose a sampling mode:
   - **One image per day** — the first archived image found each local day.
   - **One image per hour** — the first archived image found each local hour.
   - **All images** — every archived image in the range, unsampled.
6. Select **Preview**. This only lists what the archive has — it downloads
   nothing. It reports how many images exist in the range, how many the
   chosen sampling mode will actually save, and their total size, so a
   full-year request is never downloaded blind.
7. Select **Download**. Only the previewed request can be downloaded; change
   any field and preview again first.

## What Gets Saved

Each request creates its own folder under the site:

```text
site/
  inputs/
    image-sequences/
      usgs-<camera>-<start-date>-<end-date>/
        images/
        sequence-manifest.jsonl
        download-summary.json
```

`sequence-manifest.jsonl` has one row per sampled time slot, with `site_id`,
`camera_id`, `source_url`, `captured_at_utc`, `local_time`, `filename`,
`file_size_bytes`, `download_status`, and `source_system: usgs_nims`.
`download_status` is `downloaded`, `failed`, or `missing` — a time slot with
no archived image at all is recorded as `missing`, never silently dropped
and never treated as a normal-water observation. `download-summary.json`
holds the request's camera, timezone, sampling mode, date range, and counts.

Requesting the same camera and date range again is refused unless
`overwrite` is set, so a request never silently merges into or replaces an
earlier download.

## Reviewing A Sequence

Open a site's **Image sequences** tab on the site-details page
(`/site-details.html?site=<name>`) to see every saved sequence for that
site, its downloaded/missing/failed counts, and a thumbnail grid of its
successfully downloaded images — a simple way to spot-check representative
images before any future validation work uses them.

## Using A Saved Image As A Visual Reference

Any saved image can stand in for a video frame when drawing the site's
**watched area** — select **Use as watched-area reference** under a
thumbnail. It opens the same watched-area selector used for videos, pointed
at that still image instead of a video frame; the watched area itself is a
percentage rectangle with no video or image linkage, so it works exactly the
same either way. Saving stores a `sequence_id`/`filename` reference instead
of a `video_id`.

## Out Of Scope (For Now)

- `Run validation` does not read, sample, or score image sequences.
- No video is fabricated from a sequence's images.
- Image sequences are not treated as, or published as, flood warnings.
- No ML training happens on this data in this workflow.

## Code Location

The date-range listing, sampling, and download logic extends the existing
USGS/NIMS downloader in `src/openfloodai/ingestion/river_images.py` (see
also [Download River Images And Video](river-image-downloader.md), which
covers that module's original single-hour download and live-camera-clip
features). The Home UI server exposes
`/api/preview-image-sequence`, `/api/download-image-sequence`,
`/api/site-image-sequences`, and `/api/image-sequence-image` in
`src/openfloodai/ui/home_server.py`. The intake form lives in
`tools/openfloodai-home-ui.html`; the review tab lives in
`tools/openfloodai-site-details.html`.

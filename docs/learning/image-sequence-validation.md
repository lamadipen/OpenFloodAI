# Image-Sequence Validation Runs

Use this workflow to run local validation against a saved
[USGS image sequence](usgs-image-sequence-workflow.md) and capture reviewable
results — a machine observation per compared image, review images a human
can inspect, and a report that clearly separates "no change" from "cannot
judge."

**This is not the video validation flow.** It is a separate, parallel path.
It does not change video intake, labels, the manifest, or `Run validation`,
and it does not read anything those write. It lives entirely on the
site-details page's Image sequences tab, next to the sequence it runs
against.

## Result States

Every compared image gets exactly one of four results:

- `possible_water_level_change` — the watched area changed in a pattern
  consistent with a water-level change (for example, a change concentrated
  in the lower part of the watched area, with the upper part unchanged).
  This is not proof of flooding.
- `no_water_level_change` — no meaningful change was detected compared to
  the baseline image.
- `cannot_judge_water_level` — the watched area is too small to judge
  safely (a site-configuration issue, not an image quality issue).
- `camera_or_image_problem` — the image is missing, failed to download, is
  very dark, or the *whole* watched area changed uniformly at once (which
  usually means lighting, weather, or camera movement rather than a real
  water-level change).

None of these are public flood warnings. See the Safety Boundary section of
every generated report.

## Test It With A Small Sample First

1. Download a small image sequence for one site — a couple of days,
   sampled `one_per_hour`, is plenty to try this with. See
   [USGS Image-Sequence Workflow](usgs-image-sequence-workflow.md).
2. Set the site's watched area (required). A confirmed riverbank guide is
   optional — it's drawn on the review images if present but is not
   required to run.
3. Open the site's details page, go to **Image sequences**, and select
   **Run image-sequence validation** on that sequence's card.
4. The run appears under **Past runs** on the same card. Select it to
   expand the report, the review images (baseline, current, comparison,
   and overlay versions with the watched area and any confirmed riverbank
   guide burned in), and the per-image results.

The baseline is the earliest successfully downloaded image in the sequence
by default. Every other downloaded image is compared against it. Missing or
failed images are recorded as `camera_or_image_problem`, never silently
skipped.

## What Gets Saved

Each run creates its own folder:

```text
site/
  outputs/
    image-sequence-runs/
      <run-id>/
        run-summary.json
        image-sequence-report.md
        image-sequence-records.jsonl
        review-images/
        inputs-used/
```

`image-sequence-records.jsonl` has one row per compared image (excluding the
baseline), with its filename, capture time, download status, result, reason,
and change/brightness scores where a comparison was possible.
`run-summary.json` records the baseline image, per-result counts, the
watched area used, and which confirmed riverbank guides (if any) were used.
`review-images/` holds one illustrative before/after/comparison set — the
single compared image with the largest measured change, the same
"biggest change" convention the video flow already uses — plus overlay
versions with the watched area and any confirmed riverbank guides drawn on.
`inputs-used/` snapshots the exact `sequence-manifest.jsonl` and site-config
fields (watched area, riverbank guides) the run used.

Requesting a run for a sequence that has fewer than two downloaded images,
or for a site with no watched area set, is refused with a clear message.

## Code Location

The runner lives in `src/openfloodai/validation/image_sequence_runner.py` —
a module fully separate from `src/openfloodai/validation/site_runner.py`
(the video flow). It reuses two already-tested, video-agnostic building
blocks rather than inventing new detection logic:
`openfloodai.vision.simple_signals.compare_region_signals` for the
machine-observation heuristic, and
`openfloodai.review.review_images.generate_biggest_change_review_images` for
the review images. The Home UI server exposes
`/api/run-image-sequence-validation`, `/api/image-sequence-runs`,
`/api/image-sequence-run-detail`, and `/api/image-sequence-run-image` in
`src/openfloodai/ui/home_server.py`. The button and run list live in
`tools/openfloodai-site-details.html`; `tools/openfloodai-home-ui.html` is
untouched by this feature.

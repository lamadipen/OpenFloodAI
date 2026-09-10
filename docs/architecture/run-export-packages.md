# Exporting one run as a review package

Export one run only. Later site changes are not included.

`export_run(site_dir, run_id, ...)` in `openfloodai.validation.run_export`
builds a shareable, local-only review package for one saved run under
`<site_dir>/exports/<site-name>_<run-id>_review-package/`. It is also
available in the Home UI as **Export Run Results**, next to that run in the
site's run history.

The package is built only from that run's own saved outputs and its
`inputs-used` snapshot (see [Validation input snapshots](validation-input-snapshots.md)).
It never reads the site's current live config, manifest, labels, or watched
area, so a later site edit cannot change what an already-exported package
says a run used.

| File | Source |
| --- | --- |
| `report.md` | The run's `validation-report.md` |
| `scorecard.json` | The run's `scorecard.json` |
| `records.jsonl` | All of the run's per-video records files, combined |
| `run-metadata.json` | The run's `run-metadata.json` |
| `site-summary.json` | A small summary built from the run's own receipt, not the live site config |
| `review-images/` | The run's evidence images, copied as-is |
| `inputs-used/` | The run's full input snapshot, copied as-is |
| `README.md` | Generated; explains what is inside and whether raw video is included |

## Raw video

Raw video is excluded by default. It is only ever added when the caller
explicitly opts in (`include_raw_video=True`, or the Home UI's **Include raw
video only if this video is approved to share** checkbox), and even then only
for a video whose current file under `inputs/videos/` still has the exact
SHA-256 checksum saved for that run in `video-list.snapshot.json`. A video
that is missing or has changed since the run is left out and named in the
README instead of being silently substituted or silently dropped.

## Safety

- The export path is checked to stay inside `<site_dir>/exports/`; an invalid
  or path-traversing `run_id` is refused.
- A `run_id` that does not exist, or a run folder missing its report,
  scorecard, run metadata, or input snapshot, is refused with a clear message
  instead of producing a partial package.
- Re-exporting the same run replaces its existing package; exports are a
  regenerable byproduct, not a permanent historical record like a run folder.
- Nothing is uploaded or published by this export. It stays local.

## Zip output

Passing `as_zip=True` archives the package as
`<site_dir>/exports/<site-name>_<run-id>_review-package.zip` and removes the
loose folder, so a run has either the folder or the zip, not both.

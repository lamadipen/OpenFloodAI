# Exporting runs and sites for teammates

Exports are portable copies, built from a run's own saved outputs, meant to
be dropped straight into another OpenFloodAI checkout with no translation
step.

`openfloodai.validation.run_export` has two builders:

- `build_run_export(site_dir, run_id, destination_dir, ...)` copies one
  saved run.
- `build_export_all(sites_dir, destination_dir, ...)` copies every site.

Both are available in the Home UI: **Export Run Results** next to a run in
that site's run history, and **Export All Reports** on the main page, right
before **Refresh**. Both download a `.zip` through the browser, so where the
file lands is controlled by the browser's own downloads location or "ask
where to save" setting, not by this app.

Both read only a run's own saved outputs and its `inputs-used` snapshot (see
[Validation input snapshots](validation-input-snapshots.md)) for anything
run-specific. Neither reads the site's current live config, manifest, or
labels for that purpose, so a later site edit cannot change what an
already-exported run says it used.

## Single-run export

`build_run_export` copies `<site_dir>/outputs/runs/<run-id>/` into
`<destination_dir>/<run-id>/`, keeping the run's own filenames and layout
unchanged: `validation-report.md`, `scorecard.json`, `records/` (one file per
video), `review-images/`, `inputs-used/`, and `run-metadata.json`. A
`README.md` is added alongside them.

This is the whole point of the layout: because the folder name and every
file inside it match what a live run folder already looks like, a teammate
can copy `<run-id>/` straight into their own
`data/sites/<site-name>/outputs/runs/` and that site's run history picks it
up the next time its Home UI loads — no separate import step, no renaming.

To make that copy-paste actually resolve correctly wherever it lands,
`run-metadata.json`'s path fields (`report_path`, `scorecard_path`,
`records_path`, `review_images_path`, `inputs_used_path`) are rewritten to
plain relative filenames before copying. `site_status._read_saved_run_history`
resolves a relative path against the run folder it was found in (an existing
absolute path, from a run produced on this machine, is still used as-is) —
see `_resolve_run_metadata_path` in `openfloodai/validation/site_status.py`.

## Export All

`build_export_all` copies every direct subfolder of `sites_dir` into
`<destination_dir>/<site-name>/`, including `configs/`, `labels/`,
`manifest.jsonl`, and every run under `outputs/runs/` (each built the same
portable way as a single-run export). A top-level `README.md` lists the
sites included.

This is for a teammate who does not have the site set up locally at all:
copying one of these site folders into their own `data/sites/` gives them
the full site — config, labels, manifest, and run history — ready to open in
their own Home UI and start reviewing, not just a read-only report.

## Raw video

Raw video is excluded by default in both exports.

- Single-run export only ever adds a video when the caller opts in
  (`include_raw_video=True`, or the Home UI's **Include raw video only if
  this video is approved to share** checkbox), and even then only for a
  video whose current file under `inputs/videos/` still has the exact
  SHA-256 checksum saved for that run in `video-list.snapshot.json`. A video
  that is missing or has changed since the run is left out and named in the
  README instead of being silently substituted or silently dropped.
- Export All, when its own raw-video checkbox is checked, copies each site's
  whole `inputs/videos/` folder as-is (it is bundling the live site to be
  reusable, not verifying one run's historical inputs).

## Safety

- A `run_id` must match `[A-Za-z0-9_-]+` and stay inside
  `outputs/runs/`; a path-traversing or unknown `run_id` is refused.
- A run missing its report, scorecard, run metadata, or input snapshot is
  refused with a clear message instead of producing a partial package.
- `build_export_all` refuses when `sites_dir` does not exist or has no
  sites to export.
- Nothing is uploaded or published by either export. Both build into a
  server-side temporary directory that is deleted once the zip has been
  streamed to the browser.

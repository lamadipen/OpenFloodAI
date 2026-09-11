# Inputs saved for each validation run

Changes affect the next run only. Old runs keep their original inputs.

Each new site validation run keeps a receipt under
`outputs/runs/<run-id>/inputs-used/`. Existing reports, records, scorecards,
and images keep their current names and locations.

| File | What it records |
| --- | --- |
| `receipt.json` | Run ID, site and camera IDs, site folder name, capture time, label count, requested comparison mode, and final status |
| `site-config.snapshot.json` | Exact selected config file, including site metadata |
| `watched-area.snapshot.json` | The reference region used by this run |
| `manifest.snapshot.jsonl` | The manifest bytes available at capture, including notes and sharing flags |
| `labels.snapshot.jsonl` | All loaded human label records, including duplicates, in comparison order |
| `video-list.snapshot.json` | Captured video IDs, filenames, byte sizes, and SHA-256 checksums |

Missing labels produce an empty labels snapshot. A missing manifest produces an
empty manifest snapshot and `manifest_present: false` in the receipt. Manifest
rows are captured as context; the runner still discovers videos from the site's
local video folder. This change does not make a manifest or human labels required.

The runner processes the saved config and loaded label records. It makes temporary
local copies of the discovered videos before processing and computes checksums as
it copies. The temporary copies are removed when the run ends, including ordinary
error exits. Allow temporary disk space for one extra copy of the site's videos.
There are no permanent extra video copies. A checksum identifies the bytes used;
it cannot restore a video deleted later. Retain source media separately if you
need to replay an old run.

Files are captured in order, not as an atomic filesystem transaction. Avoid editing
inputs while capture is in progress. A detected video change during copying stops
the run with an error. Once captured, subsequent site edits cannot alter the inputs
being processed. Abrupt process termination can leave a `running` receipt and
possibly temporary files; it must not be interpreted as a completed run.

## Example

1. Run without a label: the receipt contains no labels, the machine finding remains
   visible, and the report says no human label was found for comparison.
2. Add a label and run again: the new receipt contains it. Run 1 stays unchanged.
3. Change the watched area, notes, or add a video: only the next receipt reflects it.
4. Add another label for the same video and exact time window: both records remain
   in the snapshot. Both comparison entries say `cannot_compare` with a duplicate
   label explanation. No reviewer or last-written label is silently preferred.

Duplicate detection also applies to identical repeated labels. Different time
windows remain separate comparisons. Invalid time windows keep their existing
invalid-window behavior. Missing or unreadable videos still report their processing
problem; the snapshot preserves any labels available for them.

## Reading one run for a future export

Use `read_input_snapshot(Path(run_directory))` from
`openfloodai.validation.input_snapshot`. It reads only files inside that run's
`inputs-used` folder. It never substitutes the current site's config, labels, or
manifest. For an older run with no snapshot, it raises `FileNotFoundError`.

This reader is the local input source for run export packages; see
[Run export packages](run-export-packages.md). Do not infer permission to share
from the existence of a receipt: labels, metadata, and paths can still contain
private data.

Run history in the Home UI displays the inputs-used path and identifies older runs
without receipts. New reports remind users that changes affect the next run only.
Snapshots do not establish flood accuracy, train a model, or send warnings.

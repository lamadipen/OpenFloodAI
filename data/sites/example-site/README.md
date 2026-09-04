# Example Validation Site

This is a placeholder site folder that shows how one site should be organized.

Simple meaning: each site gets its own videos, labels, configs, human evidence, and system outputs.

## Folders

```text
configs/                  Safe site/camera configs for this site
manifest.jsonl            List of validation videos and their review status
inputs/
  videos/                 Local validation videos
  other/                  Other local inputs, such as reference frames
labels/                   Human labels for frames or time windows
expected-behavior/        Expected safe behavior for hard validation cases
human-evidence/
  flood-images/           Images a person selected as possible flood evidence
  notes/                  Human review notes
outputs/
  records.jsonl           JSONL records from a local POC run
  summary.md              Markdown summary from a local POC run
  operator-notes.txt      Plain-language notes from a local POC run
  label-comparison.md     Optional human-label comparison report
  threshold-tuning.md     Optional prototype threshold tuning report
  review-images/          System-generated review images
```

## Example

A future real site might look like:

```text
data/sites/colorado-river-windy-gap/
  configs/site-config.json
  inputs/videos/local-sample.mp4
  inputs/other/reference-frame.png
  labels/labels.jsonl
  human-evidence/flood-images/high-water-frame.png
  outputs/records.jsonl
  outputs/summary.md
  outputs/operator-notes.txt
  outputs/review-images/
```

Real videos and real images should stay local unless they are approved for public sharing.

The safe demo manifest file is:

```text
manifest.jsonl
```

Simple meaning: this file explains what a validation video is for, whether it has a human label, and whether it is safe to commit.

The safe demo label file is:

```text
labels/example-labels.jsonl
```

Simple meaning: this file shows the label format without using private video or private camera images.

The safe hard-case expectation file is:

```text
expected-behavior/hard-cases.jsonl
```

Simple meaning: this file lists confusing cases, like missing video or glare, and says they should stay visible as `UNKNOWN`, `DEGRADED`, or `cannot_compare`.

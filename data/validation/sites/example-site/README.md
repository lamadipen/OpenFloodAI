# Example Validation Site

This is a placeholder site folder that shows how one validation site should be organized.

Simple meaning: each site gets its own videos, labels, configs, human evidence, and system outputs.

## Folders

```text
configs/                  Safe site/camera configs for this site
videos/                   Local validation videos
labels/                   Human labels for frames or time windows
human-evidence/
  flood-images/           Images a person selected as possible flood evidence
  notes/                  Human review notes
outputs/
  records/                JSONL records from local POC runs
  summaries/              Markdown summaries from local POC runs
  operator-notes/         Plain-language notes from local POC runs
  review-images/          System-generated review images
```

## Example

A future real site might look like:

```text
data/validation/sites/colorado-river-windy-gap/
  configs/site-config.json
  videos/local-sample.mp4
  labels/labels.jsonl
  human-evidence/flood-images/high-water-frame.png
  outputs/records/run-001.jsonl
  outputs/summaries/run-001.md
  outputs/operator-notes/run-001.txt
  outputs/review-images/run-001/
```

Real videos and real images should stay local unless they are approved for public sharing.

The safe demo label file is:

```text
labels/example-labels.jsonl
```

Simple meaning: this file shows the label format without using private video or private camera images.

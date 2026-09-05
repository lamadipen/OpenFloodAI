# Validation Dataset Manifest

A validation dataset manifest is a simple list of videos for one site.

Simple meaning: before someone uses a video, they can see what it is for, whether it has labels, and whether it is safe to share.

## File Location

Put one manifest file in each site folder:

```text
data/sites/<site-name>/manifest.jsonl
```

Simple example:

```text
data/sites/example-site/manifest.jsonl
```

Use JSON Lines format. That means each line is one JSON record.

## Required Fields

Each manifest row must include:

- `video_id`: a short ID used by labels and reports
- `filename`: the video filename inside the site video folder
- `purpose`: why this video exists
- `split`: either `practice` or `locked_validation`
- `approved_for_repo`: `true` or `false`
- `has_human_label`: `true` or `false`
- `notes`: short plain-language notes

Optional field:

- `hard_case_type`: the confusing condition, when relevant

## Example Record

```json
{"video_id":"glare-001","filename":"glare-001.mp4","purpose":"hard_case_glare","split":"practice","approved_for_repo":false,"has_human_label":true,"hard_case_type":"heavy_glare","notes":"Bright sunlight blocks the watched water area."}
```

Simple meaning: this video is useful for testing glare, but it should not be committed to GitHub.

## Practice Vs Locked Validation

Use `practice` for videos we are allowed to learn from while changing code.

Simple example: a developer tries three visual-change thresholds on a practice video to understand what happens.

Use `locked_validation` for videos kept aside for fair checking.

Simple example: after tuning on practice videos, run the system on locked-validation videos to see if it still works. Do not keep changing thresholds just to make locked-validation results look better.

## Privacy And Sharing

Set `approved_for_repo` to `false` unless the video is clearly safe to commit.

Good reasons to keep it `false`:

- it came from a real camera
- it shows a private or sensitive place
- its license is unclear
- it includes people, homes, vehicles, or exact site details

Set `has_human_label` to `true` only when a human label file exists for that `video_id`.

Simple example: if `labels/example-labels.jsonl` has labels for `demo-river-001`, then the manifest row for `demo-river-001` can use `has_human_label: true`.

## Manual Check

Run this from the repository root:

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.review import load_manifest_records

records = load_manifest_records(Path("data/sites/example-site/manifest.jsonl"))

print(f"Manifest records: {len(records)}")
print(records[0])
PY
```

This only checks the manifest text. It does not open videos, train a model, detect floods, or send alerts.

## Add A Video With The Helper

You do not have to edit `manifest.jsonl` by hand.

From the local Home UI, open **Add Video**, choose a site, and enter a local video path plus metadata.

Or use the command-line helper:

```bash
python3 scripts/intake_validation_video.py \
  --folder-name "example-site" \
  --video-path "/local/path/rising-001.mp4" \
  --video-id "rising-001" \
  --purpose "possible_rising_water" \
  --split "practice" \
  --notes "Local practice clip. Not approved for the public repo."
```

Simple meaning: the helper copies the video into `data/sites/<site-name>/inputs/videos/` and adds one manifest row.

`approved_for_repo` stays `false` unless you explicitly set it. The helper does not upload video, commit files, or overwrite an existing video or row unless you ask it to.

# Prototype Threshold Tuning

This page explains how to try simple visual-change thresholds against human labels.

Simple meaning: test a few numbers and see which one agrees better with human review.

This is only a learning tool. It does not prove flood detection accuracy and does not create public warnings.

## What It Uses

The tuning helper reads:

- local system records from a POC run
- local human labels
- one `video_id`
- one or more candidate thresholds

Simple example:

```text
Threshold 0.050 says: visual change of 0.10 counts as change.
Threshold 0.200 says: visual change of 0.10 does not count as change.
```

## Run It

```bash
python3 scripts/tune_thresholds.py \
  --records-path data/local-runs/video-review/records.jsonl \
  --labels-path data/validation/sites/example-site/labels/example-labels.jsonl \
  --video-id demo-river-001 \
  --threshold 0.02 \
  --threshold 0.05 \
  --threshold 0.10
```

To save the report:

```bash
python3 scripts/tune_thresholds.py \
  --records-path data/local-runs/video-review/records.jsonl \
  --labels-path data/validation/sites/example-site/labels/example-labels.jsonl \
  --video-id demo-river-001 \
  --output-path data/local-runs/video-review/threshold-tuning.md
```

## Report Meaning

The report shows:

| Field | Simple Meaning |
| --- | --- |
| `Agree` | Human label and system output pointed in the same broad direction. |
| `Disagree` | Human label and system output did not match. |
| `Cannot Compare` | Human label or system output was missing, unclear, or unknown. |
| `Compared` | Only agree plus disagree. Cannot-compare cases are not counted as success. |

Simple example:

```text
Threshold 0.050 -> agree: 1, disagree: 0
Threshold 0.200 -> agree: 0, disagree: 1
```

This means the lower threshold matched this one human label better. It does not mean the lower threshold is safe for real flood detection.

## Current Default Candidates

The current prototype candidates are:

- `0.02`
- `0.05`
- `0.10`
- `0.20`

These are starting points for review, not final defaults.

## Current Boundary

This tool does not train ML, change production settings, send alerts, upload files, or claim real flood accuracy.

It only helps the project choose better prototype thresholds using validation evidence instead of guessing.

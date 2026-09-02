# Human Label Comparison

This page explains how to compare human labels with OpenFloodAI local POC output.

Simple meaning: a person says what they saw, the system says what it measured, and this report shows whether they match.

This is validation evidence only. It does not prove flood detection accuracy and does not create public warnings.

## What It Compares

The comparison uses two local files:

- system output records from a local POC run
- human labels from a validation label file

Simple example:

```text
System output: region_change_score = 0.42
Human label: water_rising
Report: agree
```

The current simple visual signal can say that the watched area changed. It cannot safely say whether water is rising or falling yet.

## Video Matching

The command uses `--video-id` to choose which human labels to compare.

If system records also include `video_id`, only records with the same `video_id` are used.

Simple example:

```text
--video-id demo-river-001
```

This will use:

```text
system record video_id = demo-river-001
```

It will ignore:

```text
system record video_id = demo-river-999
```

If old system records do not include `video_id`, the comparison treats the records file as one video run. Do not mix multiple videos in one records file unless each system record includes `video_id`.

So, for now:

- `water_rising` can agree with a strong visual-change signal
- `water_falling` can agree with a strong visual-change signal
- `no_clear_change` can agree with a low visual-change signal
- `cannot_judge` means the report should not compare the case
- `camera_video_problem` means the report should not compare the case

## Run A Comparison

Use the demo label file and a local POC records file:

```bash
python3 scripts/compare_human_labels.py \
  --records-path data/local-runs/video-review/records.jsonl \
  --labels-path data/validation/sites/example-site/labels/example-labels.jsonl \
  --video-id demo-river-001
```

To save the report:

```bash
python3 scripts/compare_human_labels.py \
  --records-path data/local-runs/video-review/records.jsonl \
  --labels-path data/validation/sites/example-site/labels/example-labels.jsonl \
  --video-id demo-river-001 \
  --output-path data/local-runs/video-review/label-comparison.md
```

## Result Values

| Result | Simple Meaning |
| --- | --- |
| `agree` | Human label and system output point in the same broad direction. |
| `disagree` | Human label and system output do not match. |
| `cannot_compare` | A label or system output is missing or unclear. |

## Example Output

```text
Video: demo-river-001
Human label: water_rising
System result: water_change_seen
Result: agree
Note: The human saw water change, and the system measured visual change.
```

## Current Boundary

This report does not train a model, send alerts, upload data, or publish warnings.

It only helps developers and reviewers see where the current POC agrees or disagrees with human review.

To try different visual-change thresholds, see [Prototype Threshold Tuning](threshold-tuning.md).

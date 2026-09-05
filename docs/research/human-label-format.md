# Human Label Format

This page explains the small JSON Lines format for human video review labels.

Simple meaning: a person watches a video or review images and writes down what they saw in a consistent way.

These labels are review evidence only. They do not create alerts or public warnings.

## File Type

Use JSON Lines, with one label record per line.

Simple example:

```json
{"video_id":"demo-river-001","time_window_seconds":[0,30],"human_label":"water_rising","confidence":"medium","note":"Water appears to move higher against the bridge pillar."}
```

## Required Fields

| Field | Meaning |
| --- | --- |
| `video_id` | A safe name for the video or input being reviewed. |
| `time_window_seconds` | Start and end seconds for the reviewed part of the video. |
| `human_label` | What the reviewer saw. |

Simple example: `[0, 30]` means the reviewer watched from second 0 to second 30.

## Optional Fields

| Field | Meaning |
| --- | --- |
| `site_id` | Site name or ID, if known. |
| `camera_id` | Camera name or ID, if known. |
| `confidence` | How sure the reviewer is. |
| `note` | Short human explanation. |
| `reviewer_id` | Safe reviewer ID, if the project uses one. |

Do not put personal phone numbers, emails, passwords, or private camera URLs in label files.

## Allowed Human Labels

Use one of these values:

| Label | Simple Meaning |
| --- | --- |
| `water_rising` | Water appears to move higher or cover more of the watched area. |
| `water_falling` | Water appears to move lower or cover less of the watched area. |
| `no_clear_change` | The reviewer does not see a clear water change. |
| `camera_video_problem` | The video, camera view, or file has a problem. |
| `cannot_judge` | The reviewer cannot safely decide from the image or video. |

Simple example: use `cannot_judge` when the image is too dark, blurry, blocked, or confusing.

## Allowed Confidence Values

Use one of these values:

- `low`
- `medium`
- `high`

Simple example: if water may be rising but glare makes it hard to see, use `confidence: "low"` and explain why in `note`.

## Where To Put Labels

Put labels in the validation dataset structure:

```text
data/sites/<site-name>/labels/
```

Safe demo example:

```text
data/sites/example-site/labels/example-labels.jsonl
```

Real label files may contain sensitive notes. Keep them local unless they are approved for public sharing.

## Creating Labels

Instead of manually editing JSON Lines files, use the labeling helper:

### From the Home UI

Start the local UI:

```bash
python3 scripts/run_openfloodai_home_ui.py
```

Open `http://127.0.0.1:8765/openfloodai-home-ui.html` in your browser.
Click **Add Label** in the top toolbar (or **+ Add Label** on a site card).
Choose the site, enter the `video_id`, start and end seconds, select the human label, and optionally add confidence and reviewer notes.
Click **Save Label Record**.

### From the Command Line

Run:

```bash
python3 scripts/create_human_label.py \
  --site-dir data/sites/example-site \
  --video-id rising-001 \
  --start 30 \
  --end 60 \
  --label water_rising \
  --confidence medium \
  --note "water appears higher near the bridge pillar"
```

Simple meaning: this helper validates the time window and label value, prevents accidental overwrites, and appends the record into the site's `labels/` directory.

To replace an existing record for the same video and time window, add `--overwrite`.

## Validation

OpenFloodAI can validate a label file:

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.review import load_human_label_records

records = load_human_label_records(
    Path("data/sites/example-site/labels/example-labels.jsonl")
)

print(f"Valid labels: {len(records)}")
print(records[0])
PY
```

Simple meaning: this checks that each label has the required fields, uses an allowed label value, and has a valid time window.

After labels are valid, compare them with system output using the [Human Label Comparison](human-label-comparison.md) guide.

## Current Boundary

This format does not train a model, score flood risk, send alerts, upload data, or create public warnings.

It only lets humans write review labels in a format the project can check later.

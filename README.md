# OpenFloodAI

OpenFloodAI is an open-source, low-cost, edge-first camera-based river flood detection and warning-support system.

This repository is in its foundation phase. The current scope is project structure, contribution standards, and development tooling. Flood detection logic, machine learning models, APIs, and application business logic are intentionally not implemented yet.

OpenFloodAI is moving toward an edge-first camera system that watches a configured river area, measures simple water-level or water-coverage changes over time, saves clear metadata, and supports human review before any public warning action.

## Goals

- Support affordable river monitoring with edge-first deployment.
- Keep the system auditable, testable, and suitable for public-interest use.
- Prefer minimal dependencies and clear operational boundaries.
- Build toward warning-support workflows, not autonomous emergency decision-making.

## Repository Layout

```text
.github/              GitHub templates and CI workflows
docs/                 Project documentation
  architecture/       Architecture notes and diagrams
  adr/                Architecture Decision Records
  research/           Research notes and references
src/openfloodai/      Python package source
  common/             Shared utilities and types
  edge/               Edge deployment components
  risk_engine/        Risk evaluation components
  vision/             Camera and vision components
tests/                Automated tests
data/                 Local data placeholders; raw datasets are not committed
models/               Local model placeholders; trained models are not committed
scripts/              Development and operational scripts
configs/              Configuration examples and templates
```

## Development

OpenFloodAI targets Python 3.12 or newer.

On macOS and many Linux systems, use `python3`. On Windows, `py -3` is often the closest equivalent.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

Run checks:

```bash
ruff check .
ruff format --check .
mypy src tests
pytest
mkdocs build --strict
```

## Documentation Site

OpenFloodAI has a small MkDocs documentation site in `docs/`.

The documentation includes a [Privacy And Retention](docs/privacy-retention.md) page for safe local POC data handling.

Build it locally:

```bash
mkdocs build --strict
```

Preview it locally:

```bash
mkdocs serve
```

The GitHub Pages workflow builds the site from the repository and publishes it from the `main` branch.

For deployment, GitHub Pages should use **GitHub Actions** as the source. If Pages is set to deploy from the repository root or the `docs/` folder directly, it may show only raw Markdown pages instead of the full MkDocs site.

## Real Run Guide

The project can now do a few small real things:

- Validate an event/audit JSON record.
- Load a safe site and camera config.
- Read a local video file and create basic frame metadata.
- Summarize local POC records for review.

It does not detect floods, run ML, score risk, send alerts, or store data in a database yet.

### 1. Set Up The Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

### 2. Validate An Example Event Record

Run this from the repository root:

```bash
python3 - <<'PY'
import json
from pathlib import Path

from openfloodai.contracts import validate_event_record

record_path = Path("examples/events/valid-high-event-audit-record.json")
record = json.loads(record_path.read_text())

errors = validate_event_record(record)

if errors:
    print("Invalid record:")
    for error in errors:
        print(f"- {error}")
else:
    print("Valid event record")
PY
```

Simple meaning: this checks whether the JSON file has the required fields, valid timestamps, valid risk state, and valid reason codes.

### 3. Load A Site And Camera Config

This reads a safe public config from `configs/example-site.json`.

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.config import load_site_config

config = load_site_config(Path("configs/example-site.json"))

print(config)
print(f"Site: {config.site_id}")
print(f"Camera: {config.camera_id}")
print(f"Public location: {config.public_location}")
PY
```

Simple meaning: instead of typing the same camera details in many places, we keep them in one small file. The example uses a broad public location only, like "Demo River near Example Town". It does not include exact GPS, real camera URLs, passwords, or contact details.

### 4. Try An Invalid Event Record

```bash
python3 - <<'PY'
import json
from pathlib import Path

from openfloodai.contracts import validate_event_record

record_path = Path("examples/events/invalid-normal-with-camera-offline.json")
record = json.loads(record_path.read_text())

for error in validate_event_record(record):
    print(f"- {error}")
PY
```

Simple meaning: this should fail because a camera-offline record must not look like `NORMAL`.

### 5. Check Local Video Health

Use this before reading frame metadata. It checks whether the video exists, opens, and has at least one readable frame.

Replace `data/sample-video.mp4` with your video path:

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.ingestion import check_video_file_health

record = check_video_file_health(
    Path("data/sample-video.mp4"),
    site_id="site-demo-01",
    camera_id="camera-demo-01",
)

print(record)
PY
```

Simple meaning: this tells you whether the input video is usable. If the file is missing or unreadable, it returns a non-OK health record instead of pretending the river is normal.

### 6. Read Metadata From A Local Video

Use your own small local video file. Do not use private camera footage unless you are allowed to process it.

Replace `data/sample-video.mp4` with your video path:

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.ingestion import read_video_metadata

records = read_video_metadata(
    Path("data/sample-video.mp4"),
    site_id="site-demo-01",
    camera_id="camera-demo-01",
)

print(f"Frames read: {len(records)}")
print(records[0])
PY
```

Simple meaning: this opens the video and returns records about frames, such as frame ID, timestamp, size, frame rate, and frame hash. It does not inspect the river or decide flood risk.

### 7. Save Video Metadata To A Local File

This is useful for manual validation. It lets you check that the video was read and that frame metadata was saved.

Replace `data/sample-video.mp4` with your local video path:

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.contracts import read_jsonl_records, write_jsonl_records
from openfloodai.ingestion import read_video_metadata

records = read_video_metadata(
    Path("data/sample-video.mp4"),
    site_id="site-demo-01",
    camera_id="camera-demo-01",
)

output_path = Path("data/local-runs/frame-metadata.jsonl")
write_jsonl_records(output_path, records)

saved_records = read_jsonl_records(output_path)

print(f"Frames read: {len(records)}")
print(f"Records saved: {len(saved_records)}")
print(f"Saved to: {output_path}")
print(saved_records[0])
PY
```

Simple meaning: this reads a local video, creates one metadata record for each frame, saves those records to a `.jsonl` file, and reads the file back to confirm it worked.

### 8. Test Simple Visual Signals

This uses tiny synthetic frames. It does not need a real video, internet, or a live camera.

```bash
python3 - <<'PY'
import numpy as np

from openfloodai.vision import compare_frames, extract_frame_signals

dark_frame = np.zeros((8, 8, 3), dtype=np.uint8)
bright_frame = np.full((8, 8, 3), 220, dtype=np.uint8)

dark_result = extract_frame_signals(
    dark_frame,
    site_id="site-demo-01",
    camera_id="camera-demo-01",
)

bright_result = extract_frame_signals(
    bright_frame,
    site_id="site-demo-01",
    camera_id="camera-demo-01",
)

change_result = compare_frames(
    dark_frame,
    bright_frame,
    site_id="site-demo-01",
    camera_id="camera-demo-01",
)

print("Dark frame:")
print(dark_result)

print("\nBright frame:")
print(bright_result)

print("\nFrame comparison:")
print(change_result)
PY
```

Simple meaning: `extract_frame_signals()` looks at one frame. `compare_frames()` compares two frames. The bright frame should have a higher `brightness_score`, and the changed pair should have a `frame_change_score` greater than `0`.

These are only simple visual numbers. They do not detect floods or send warnings.

### 9. Run The Local POC Pipeline

This connects the local pieces together and saves records to one JSON Lines file.

Replace `data/sample-video.mp4` with your local video path:

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.pipeline import run_local_poc_pipeline

summary = run_local_poc_pipeline(
    video_path=Path("data/sample-video.mp4"),
    site_id="site-demo-01",
    camera_id="camera-demo-01",
    output_path=Path("data/local-runs/poc-records.jsonl"),
)

print(summary)
PY
```

Simple meaning: this checks video health, reads frame metadata, creates simple visual signals, evaluates a test risk state, and saves the records locally.

This is still a prototype. It does not detect real floods, send alerts, create public warnings, or write to a database.

### 10. Summarize A Local POC Run

Run this after the local POC pipeline creates `data/local-runs/poc-records.jsonl`.

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.replay import render_summary_markdown, summarize_jsonl_records

summary = summarize_jsonl_records(Path("data/local-runs/poc-records.jsonl"))

print(render_summary_markdown(summary))
PY
```

Simple meaning: this reads the saved JSON Lines file and prints a short report. For example, it can say how many records were created, what record types appeared, whether any `UNKNOWN` or degraded records appeared, and what the highest simple visual scores were.

This report is only for local review and debugging. It does not create a public warning, publish anything, send alerts, or show private camera details.

## Project Status

Initial repository foundation only. See `CONTRIBUTING.md` and `SECURITY.md` before proposing functional changes.

## JOIN DISCORD FOR DISCUSSION
[OPENFLOODAI DISCORD](https://discord.gg/2VzpADTZ3)

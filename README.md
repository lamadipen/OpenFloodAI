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
  validation/         Validation dataset structure and local review folders
models/               Local model placeholders; trained models are not committed
scripts/              Development and operational scripts
configs/              Configuration examples and templates
tools/                Small local-only helper tools
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

Validation videos, labels, human evidence, and review outputs should use the structure in [data/validation/README.md](data/validation/README.md).

Human video review labels should use the format in [docs/research/human-label-format.md](docs/research/human-label-format.md).

Human labels can be compared with local system output using [docs/research/human-label-comparison.md](docs/research/human-label-comparison.md).

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
- Run one safe end-to-end local POC smoke test.
- Run one local review workflow for your own video.
- Compare local system output against human labels.
- Summarize local POC records for review.
- Turn POC output records into plain-language operator notes.
- Choose a watched reference region from a local image.
- Measure simple visual signals inside a selected reference region.
- Generate a few local review images for the biggest visual change.

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

### 10. Choose A Reference Region From An Image

Use the local selector when you want to mark the part of the camera view that OpenFloodAI should watch.

Open this file in your browser:

```text
tools/reference-region-selector.html
```

Then:

1. Click `Choose Image` and select a local frame, or click `Demo Frame`.
2. Drag a box around the area you want to watch.
3. Copy the JSON output.
4. Paste the values into `configs/example-site.json` under `reference_region`.

Simple example: if the camera sees a bridge pillar, draw a box around the lower part of the pillar. The tool may output something like this:

```json
{
  "reference_region": {
    "x": 43.333333,
    "y": 32.692308,
    "width": 7.777778,
    "height": 48.076923
  }
}
```

Simple meaning: `x` and `y` say where the box starts. `width` and `height` say how big the box is. The numbers are percentages, so the same config still makes sense if the image is opened at a different display size.

This tool runs locally in your browser. It does not upload images, detect floods, save alerts, or commit files.

### 11. Run The Local Region POC Pipeline

This is a separate pipeline that uses `reference_region` from `configs/example-site.json`.

Replace `data/sample-video.mp4` with your local video path:

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.pipeline import run_local_region_poc_pipeline

summary = run_local_region_poc_pipeline(
    video_path=Path("data/sample-video.mp4"),
    config_path=Path("configs/example-site.json"),
    output_path=Path("data/local-runs/region-poc-records.jsonl"),
)

print(summary)
PY
```

Simple meaning: this checks video health, loads the site/camera config, reads frame metadata, measures simple visual signals only inside the configured reference region, evaluates a test risk state, and saves the records locally.

The old `run_local_poc_pipeline(...)` still works without region config.

This is still not flood detection. It only helps test the future virtual-ruler flow.

### 12. Run The End-To-End Local Smoke Test

This creates a safe synthetic video and runs the current local POC pieces together.

```bash
python3 scripts/run_local_poc_smoke.py
```

After it runs, check these local files:

```text
data/local-runs/smoke-test/records.jsonl
data/local-runs/smoke-test/summary.md
data/local-runs/smoke-test/operator-notes.txt
data/local-runs/smoke-test/review-images/
```

Simple meaning: this is like a practice run. It creates a fake tiny river video, loads a fake safe config, uses the selected `reference_region`, saves records, creates a summary, creates review images, and writes plain-language notes.

This does not use real footage. It does not detect floods, send alerts, upload files, connect to cameras, or write to a database.

### 13. Run A Local Review Workflow For Your Own Video

This creates the same kind of review outputs as the smoke test, but it uses your local video file.

Replace `data/sample-video.mp4` with your local video path:

```bash
python3 scripts/run_local_video_review.py \
  --video-path data/sample-video.mp4 \
  --config-path configs/example-site.json \
  --output-dir data/local-runs/video-review
```

After it runs, check these local files:

```text
data/local-runs/video-review/records.jsonl
data/local-runs/video-review/summary.md
data/local-runs/video-review/operator-notes.txt
data/local-runs/video-review/review-images/
```

Simple meaning: this reads your video, uses the `reference_region` from the config, saves records, creates a summary, writes plain-language notes, and saves review images.

This still does not detect floods, send alerts, upload files, connect to live cameras, or write to a database.

### 14. Compare Human Labels With System Output

Run this after you have a local records file and a human label file.

```bash
python3 scripts/compare_human_labels.py \
  --records-path data/local-runs/video-review/records.jsonl \
  --labels-path data/validation/sites/example-site/labels/example-labels.jsonl \
  --video-id demo-river-001
```

Simple meaning: this compares what a person wrote with what the system measured. It reports `agree`, `disagree`, or `cannot_compare`.

This does not prove flood detection accuracy. It only helps reviewers find where the POC output seems to match or miss human review.

### 15. Summarize A Local POC Run

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

### 16. Explain A POC Output For A Human Reviewer

This turns one output record into a short plain-language note.

```bash
python3 - <<'PY'
from openfloodai.review import build_operator_note

record = {
    "risk_state": "WARNING_CANDIDATE",
    "reason_codes": ["HIGH_WATER_COVERAGE", "HUMAN_REVIEW_NEEDED"],
}

print(build_operator_note(record))
PY
```

Simple meaning: instead of only showing technical fields, the helper explains what the output means. For example, it can say that stronger visual evidence needs human review.

This note is not an official public warning. It does not send alerts or decide emergency action.

### 17. Test Visual Signals Inside A Reference Region

This checks only the selected part of the image, like a virtual ruler.

```bash
python3 - <<'PY'
import numpy as np

from openfloodai.vision import compare_region_signals

previous_frame = np.zeros((10, 10), dtype=np.uint8)
current_frame = np.zeros((10, 10), dtype=np.uint8)
current_frame[:5, :] = 255

lower_half_region = {
    "x": 0,
    "y": 50,
    "width": 100,
    "height": 50,
}

upper_half_region = {
    "x": 0,
    "y": 0,
    "width": 100,
    "height": 50,
}

print("Lower half:")
print(compare_region_signals(
    previous_frame,
    current_frame,
    lower_half_region,
    "site-demo-01",
    "camera-demo-01",
))

print("\nUpper half:")
print(compare_region_signals(
    previous_frame,
    current_frame,
    upper_half_region,
    "site-demo-01",
    "camera-demo-01",
))
PY
```

Simple meaning: the top half changed, but the lower half did not. The selected region changes the result, which is what we need for a future virtual-ruler flow.

This still does not detect floods. It only measures simple image change inside the selected area.

### 18. Generate Local Review Images

This saves a few images so a person can review the biggest visual change.

```bash
python3 - <<'PY'
from pathlib import Path

import numpy as np

from openfloodai.review import generate_biggest_change_review_images

baseline_frame = np.zeros((10, 10), dtype=np.uint8)
small_change_frame = np.full((10, 10), 30, dtype=np.uint8)
biggest_change_frame = np.full((10, 10), 200, dtype=np.uint8)

result = generate_biggest_change_review_images(
    [baseline_frame, small_change_frame, biggest_change_frame],
    Path("data/local-runs/review-images"),
    reference_region={
        "x": 0,
        "y": 50,
        "width": 100,
        "height": 50,
    },
)

print(result)
PY
```

Simple meaning: this creates `review-baseline.png`, `review-changed.png`, and `review-comparison.png`. The green box shows the watched reference region.

These images are local review files only. Do not commit real review images to GitHub.

## Project Status

OpenFloodAI is in local proof-of-concept preparation.

Current local helpers can read test videos, check video health, save records, load site/camera config, choose a watched reference region from a local image, run one safe end-to-end local smoke test, run a local review workflow for your own video, compare system output with human labels, measure simple full-frame and reference-region signals, summarize saved records, generate local review images, and create plain-language operator notes.

OpenFloodAI still does not detect real floods, train ML models, connect to live cameras, send alerts, publish public warnings, provide a dashboard, or replace local emergency decision-making.

Next direction:

```text
reference region -> region-based visual signals -> review images -> human labels -> later ML
```

See the documentation site, `CONTRIBUTING.md`, and `SECURITY.md` before proposing functional changes.

## JOIN DISCORD FOR DISCUSSION
[OPENFLOODAI DISCORD](https://discord.gg/2VzpADTZ3)

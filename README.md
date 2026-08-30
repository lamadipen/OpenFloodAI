# OpenFloodAI

OpenFloodAI is an open-source, low-cost, edge-first camera-based river flood detection and warning-support system.

This repository is in its foundation phase. The current scope is project structure, contribution standards, and development tooling. Flood detection logic, machine learning models, APIs, and application business logic are intentionally not implemented yet.

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
```

## Real Run Guide

The project can now do two small real things:

- Validate an event/audit JSON record.
- Read a local video file and create basic frame metadata.

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

### 3. Try An Invalid Event Record

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

### 4. Read Metadata From A Local Video

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

## Project Status

Initial repository foundation only. See `CONTRIBUTING.md` and `SECURITY.md` before proposing functional changes.

## JOIN DISCORD FOR DISCUSSION
[OPENFLOODAI DISCORD](https://discord.gg/2VzpADTZ3)

# OpenFloodAI

OpenFloodAI is an open-source, low-cost, edge-first camera-based river flood detection and warning-support system.

The foundation and first validation-prep phase is now in place. The project has local proof-of-concept tools for video review, reference-region signals, human labels, comparison reports, threshold tuning, hard-case expectations, and validation tracking.

OpenFloodAI is moving toward an edge-first camera system that watches a configured river area, measures simple water-level or water-coverage changes over time, saves clear metadata, and supports human review before any public warning action.

## Current MVP Status

The current MVP is a local validation and review workflow, not a production flood
detection service. It can read local videos, keep frame-quality metadata, sample
labelled time windows, create simple visual evidence, compare machine output with
human labels, write scorecards, and show reports and run history in the local Home
UI. It does not use a trained ML model, live cameras, cloud services, or public
warning delivery.

The runtime footprint is intentionally small: Python 3.12+, `jsonschema`, `numpy`,
and `opencv-python-headless`. Development tools add pytest, Ruff, mypy, MkDocs,
and package-build support. See the [dependency map](docs/architecture/dependencies.md)
for the current boundary.

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
  sites/              Per-site configs, inputs, labels, evidence, and outputs
models/               Local model placeholders; trained models are not committed
scripts/              Development and operational scripts
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

The Home UI also has a few JavaScript tests. They need Node 20 or newer, and they use only built-in Node modules, so there is nothing to install:

```bash
node --test "tests/ui/*.cjs"
```

Quote the pattern. `node --test tests/ui/` does not work, because Node only looks for file names such as `name.test.cjs`, and these files are named `test_name.cjs` to match the Python tests beside them.

## Documentation Site

OpenFloodAI has a small MkDocs documentation site in `docs/`.

The docs site now includes a completed-phase summary and next validation priorities in [docs/index.md](docs/index.md), [docs/project-overview.md](docs/project-overview.md), and [docs/roadmap.md](docs/roadmap.md).

The documentation includes a [Privacy And Retention](docs/privacy-retention.md) page for safe local POC data handling.

Site configs, input videos, labels, human evidence, and review outputs should use the structure in [data/sites/README.md](data/sites/README.md).

Human video review labels should use the format in [docs/research/human-label-format.md](docs/research/human-label-format.md).

Human labels can be compared with local system output using [docs/research/human-label-comparison.md](docs/research/human-label-comparison.md).

Prototype thresholds can be reviewed using [docs/research/threshold-tuning.md](docs/research/threshold-tuning.md).

Current validation progress and known limits are tracked in [docs/research/validation-results.md](docs/research/validation-results.md).

Hard cases like missing video, glare, darkness, camera shake, and blocked views are listed in [docs/research/hard-case-validation.md](docs/research/hard-case-validation.md).

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
- Run one multi-video validation report for a site folder.
- Create a simple validation scorecard with counts and review reasons.
- Show selected-site details, latest report previews, and recent validation run history in the Home UI.
- Generate deterministic synthetic rising, falling, no-change, and unreadable-video checks in CI.
- Review hard-case expected behavior for missing, unreadable, dark, glare, shaky, and blocked-view inputs.
- Compare local system output against human labels.
- Try prototype visual-change thresholds against human labels.
- Summarize local POC records for review.
- Turn POC output records into plain-language operator notes.
- Choose a watched reference region from a local image.
- Measure simple visual signals inside a selected reference region.
- Generate a few local review images for the biggest visual change.

It does not prove real flood detection accuracy, train ML, send alerts, publish warnings, connect to live cameras, or store data in a database yet.

Current output means "please review this evidence," not "there is a confirmed flood."

Current local validation can now:

1. run one or more local videos for a site
2. save system records and review images
3. compare system output with human labels
4. summarize the result in plain language
5. keep unclear cases visible as `cannot_compare`

The local Home UI at `tools/openfloodai-home-ui.html` brings this workflow together.
It shows site readiness, gives simple next-step messages for missing config, videos,
labels, manifests, or reports, and can run validation from a ready site. Validation
results and review-image paths remain local to the selected site folder.

Each validation run is preserved under `data/sites/<site-name>/outputs/runs/<run-id>/`
with its own report, scorecard, metadata, records, and review images. Older output
files remain legacy evidence and are labeled separately in history.

Next goals:

1. Add more approved validation clips for different rivers, lighting, weather, and camera quality.
2. Build a small locked validation set and keep practice data separate from final checks.
3. Add approved real hard-case examples and review the synthetic known-answer checks.
4. Improve reference-region evidence and threshold evaluation without claiming confirmed flooding.
5. Define ML-readiness gates before selecting or training a model.

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

This reads a safe public config from `data/sites/example-site/configs/example-site.json`.

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.config import load_site_config

config = load_site_config(Path("data/sites/example-site/configs/example-site.json"))

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

output_path = Path("data/sites/example-site/outputs/frame-metadata.jsonl")
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
    output_path=Path("data/sites/example-site/outputs/poc-records.jsonl"),
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
4. Paste the values into `data/sites/example-site/configs/example-site.json` under `reference_region`.

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

This is a separate pipeline that uses `reference_region` from `data/sites/example-site/configs/example-site.json`.

Replace `data/sample-video.mp4` with your local video path:

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.pipeline import run_local_region_poc_pipeline

summary = run_local_region_poc_pipeline(
    video_path=Path("data/sample-video.mp4"),
    config_path=Path("data/sites/example-site/configs/example-site.json"),
    output_path=Path("data/sites/example-site/outputs/region-poc-records.jsonl"),
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
data/sites/example-site/outputs/smoke-test/records.jsonl
data/sites/example-site/outputs/smoke-test/summary.md
data/sites/example-site/outputs/smoke-test/operator-notes.txt
data/sites/example-site/outputs/smoke-test/review-images/
```

Simple meaning: this is like a practice run. It creates a fake tiny river video, loads a fake safe config, uses the selected `reference_region`, saves records, creates a summary, creates review images, and writes plain-language notes.

This does not use real footage. It does not detect floods, send alerts, upload files, connect to cameras, or write to a database.

### 13. Run A Local Review Workflow For Your Own Video

This creates the same kind of review outputs as the smoke test, but it uses your local video file.

Replace `data/sample-video.mp4` with your local video path:

```bash
python3 scripts/run_local_video_review.py \
  --video-path data/sample-video.mp4 \
  --config-path data/sites/example-site/configs/example-site.json \
  --output-dir data/sites/example-site/outputs
```

After it runs, check these local files:

```text
data/sites/example-site/outputs/records.jsonl
data/sites/example-site/outputs/summary.md
data/sites/example-site/outputs/operator-notes.txt
data/sites/example-site/outputs/review-images/
```

Simple meaning: this reads your video, uses the `reference_region` from the config, saves records, creates a summary, writes plain-language notes, and saves review images.

This still does not detect floods, send alerts, upload files, connect to live cameras, or write to a database.

### 14. Compare Human Labels With System Output

Run this after you have a local records file and a human label file.

To create or add a human label without writing JSON Lines manually, use the helper:

```bash
python3 scripts/create_human_label.py \
  --site-dir data/sites/example-site \
  --video-id demo-river-001 \
  --start 0 \
  --end 30 \
  --label water_rising \
  --confidence medium \
  --note "Water appears higher near the bridge pillar."
```

Then compare:

```bash
python3 scripts/compare_human_labels.py \
  --records-path data/sites/example-site/outputs/records.jsonl \
  --labels-path data/sites/example-site/labels/example-labels.jsonl \
  --video-id demo-river-001
```

Simple meaning: this compares what a person wrote with what the system measured during the same label time window. It reports `agree`, `disagree`, or `cannot_compare`.

If system records include `video_id`, only records for the requested video are compared. If old records do not include `video_id`, keep one video per records file.

If the human label says `time_window_seconds: [30, 60]`, machine records outside 30s to 60s are ignored for that label.

A machine record at exactly 30s belongs to the 30s to 60s window, not the previous 0s to 30s window.

This does not prove flood detection accuracy. It only helps reviewers find where the POC output seems to match or miss human review.

### 15. Run Multi-Video Site Validation

Use this when one site has multiple videos under `data/sites/<site-name>/inputs/videos/`.

Example site layout:

```text
data/sites/example-site/
  configs/site-config.json
  inputs/videos/rising-001.mp4
  inputs/videos/normal-001.mp4
  labels/labels.jsonl
```

Run:

```bash
python3 scripts/run_site_validation.py \
  --site-dir data/sites/example-site
```

After it runs, check:

```text
data/sites/example-site/outputs/runs/<run-id>/validation-report.md
data/sites/example-site/outputs/runs/<run-id>/records/<video-id>.jsonl
data/sites/example-site/outputs/runs/<run-id>/videos/<video-id>/summary.md
data/sites/example-site/outputs/runs/<run-id>/videos/<video-id>/operator-notes.txt
data/sites/example-site/outputs/runs/<run-id>/review-images/<video-id>/
data/sites/example-site/outputs/runs/<run-id>/videos/<video-id>/label-comparison.md
```

Simple meaning: this runs each local video, compares it with any matching human label, and creates one combined report for the site.

The combined report includes:

- totals for processed videos, failed or missing videos, `agree`, `disagree`, and `cannot_compare`
- a summary table with one row per video
- detailed per-window comparison notes
- a plain-language scorecard with video count, label-window count, result counts, and top review reasons

Missing labels, bad videos, and unclear cases stay visible as `cannot_compare`. They are not counted as success.

The scorecard is early local validation evidence, not an accuracy score and not proof of flood detection.

If one video has multiple human label time windows, the combined report lists each label window under that video. Each label window is compared with matching machine records from the same time range when possible.

If a video has no human label, the system still creates machine records, review images, notes, and report output. The comparison result stays `cannot_compare` because there is no human review to compare against.

This still does not prove flood detection accuracy, send alerts, upload files, or create public warnings.

### 16. Open The Local Home UI

Use this when you want to quickly see whether each local validation site is ready.

Run:

```bash
python3 scripts/run_openfloodai_home_ui.py
```

Then open:

```text
http://127.0.0.1:8765/openfloodai-home-ui.html
```

The launcher is a thin command wrapper; reusable Home UI server code lives in `src/openfloodai/ui/home_server.py`. Tests and other Python modules import the handler from `openfloodai.ui.home_server`.

Simple meaning: this page checks folders under `data/sites/` and shows whether each site has config, videos, labels, manifest, output reports, and a latest report.

Use the **Guided workflow** or **Classic view** switch below the page heading to
show one workspace at a time. Classic view is the default and shows site cards
and standalone actions; Guided workflow is available for step-by-step setup.

In Classic view, choose **Details View** beside **Run Validation** and **Add
Label** on a site card to open that site's details page. The page keeps the
selected-site dropdown so you can switch directly to another local site.

In Setup New Validation Site, choosing a local video first fills the site name from
the filename without its extension. The folder name uses the same filtering as the
site name: Colorado River Site becomes colorado-river-site. Names are lowercased,
extra spaces are removed or joined with one hyphen, and characters other than
letters a–z, numbers, dash, and underscore are removed. The form also fills the
site ID as `<folder-name>_sid` and camera ID as `<folder-name>_camid`; you can edit
all generated values before creating the site.

Create Site saves the initial local video, its watched area, and its manifest metadata in one local-only submission. Use **+ Add Video** on an existing site card for later clips. The Human label dropdown shows plain-language options such as “Water is rising” while saving water_rising. Its helper text explains that the label describes what a person sees during the selected time window for comparison with machine results. Video purpose and difficult-case dropdowns show plain-language labels while saving the existing manifest values. For example, “Dark video” saves night_or_dark_frame; “No difficult case” leaves the value empty. Video intake sets has_human_label to false; add human labels separately through the label form. Adding a video copies a file already on this computer into `inputs/videos/` and writes one `manifest.jsonl` row. Adding a label validates time windows and label text without manual JSON Lines editing. After you choose a site, the label form offers existing video IDs from that site’s local videos and labels already used for that site. Selecting a video fills the Video ID field; manual entry is also available. Switching sites clears the previous video selection; if the value is missing, type a short manual label like `bridge_pillar_covered`. Sharing stays off unless you explicitly mark the video as approved for the repo.

The page opens with a **Guided validation workflow** panel for the selected site. It
turns the local process into seven visible steps:

```text
1. Site setup
2. Video intake
3. Watched area
4. Human labels
5. Manifest
6. Run validation
7. Review results
```

Each step shows a simple status (`Complete`, `Missing`, or `Needs review`), a short
plain meaning, whether you need the step before a run, and its buttons. A step with
something to choose from has two buttons: `Select site` and `Create another site`,
`Select video` and `Add video`, or `Select label` and `Add label`. A step with nothing
to choose yet has only the create button. Steps 1, 2, 3, and 6 are required. Steps 4 and 5 are marked
`Needs review` when missing because machine review can still run without them, but
the result stays `cannot_compare` until a human label exists.

You need the watched area because the system only looks inside the `reference_region`
from the config. A site with no `reference_region` cannot finish a run.

The Manifest step shows whether the manifest is `Found`, `Missing`, or `Incomplete`,
along with the number of local videos it tracks. For a missing or incomplete manifest,
choose **Create manifest from local videos** or **Repair manifest from local videos**.
The action scans only `inputs/videos/`, adds rows only for untracked videos, preserves
existing metadata, keeps `approved_for_repo` false for every new row, and marks a new
row as labelled when a local `labels/*.jsonl` record already names that video. It reports
incomplete or conflicting existing rows instead of replacing them.

Step 6 shows what will happen before a run starts. It lists everything the run
needs, and says what the system will do:

```text
Ready to run. The system will compare with human labels.
Site config     Found
Videos          3 found
Watched area    Found
Human labels    1 label file(s) found
Manifest        Found
Output          Saved on this computer
```

There are three states:

- **Ready to compare** — the system checks every video and compares what it saw with
  the human labels. It saves a report, a scorecard, and review images.
- **Ready, but nothing to compare with** — there are no labels or no manifest. The
  system still checks the videos and saves what it saw, but every result stays
  `cannot_compare`.
- **Cannot run yet** — something the run needs is missing. No video is checked and no
  report is saved. The `Run Validation` button is off.

A site needs a config, videos, and a watched area before the system can check it. The
page always shows what is missing. A run with no labels is marked clearly, so nobody
reads it as a successful comparison.

Known limit: you can only pick the watched area while adding a video, so step 3 opens
the Add Video form. If a site already has videos but no `reference_region`, add the
area while adding a video, or write the region into the config file by hand.

You can start from any step that still needs work. The workflow does not force a
restart from step 1, and the separate **Create Site**, **Add Video**, **Add Label**,
and **Run Validation** actions still work on their own.

The site card also shows a **What to do next** section. It explains the next useful local action when config, videos, labels, the manifest, or a validation report is missing. When a site is ready, **Run Validation** runs the local multi-video validation flow and refreshes the report counts and review-image path.

The Home UI explains both review routes above the forms: machine-only review produces machine evidence, and human comparison review compares it with a human label. Labels are optional for running validation.

Machine review needs config, video, and a watched area. Human comparison also needs labels and a manifest.

Example:

```text
example-site
Machine review: Needs setup, video, or watched area
Human comparison: Needs labels or manifest
Config: found
Videos: 0 videos
Labels: found
Manifest: found
Latest report: not found
```

This is a local helper only. It does not upload files, connect to cameras, send alerts, train ML, publish warnings, or prove flood accuracy.

### Video Evidence Sampling

Local review now samples usable frames throughout the video. Site validation
samples each human-labelled period separately. The first two frames are no longer
the only evidence.

The defaults are a five-second interval and a maximum of 120 samples per period.
The first and last usable frames are included. Longer periods use wider spacing.
You can change the settings:

~~~bash
python3 scripts/run_site_validation.py \
  --site-dir data/sites/example-site \
  --sample-interval-seconds 5 \
  --max-samples 120 \
  --minimum-brightness 5
~~~

The same options work with scripts/run_local_video_review.py. Python callers
can pass SamplingSettings and a list of time_windows to either pipeline.

Every decoded frame keeps its metadata. Dark frames are marked unusable and are
not compared. Reports show unusable counts, reasons, sample times, and coverage.
Too little usable footage gives cannot_compare. Review images show the actual
saved comparison frames with their video times. Reruns replace derived run records
and refresh generated images.

Example: if seconds 0–4 are black, the baseline can start at 5 seconds. Compare
5→10 and 10→15, and also 5→15 to show a slow overall change. The dark opening
remains unjudged.

These are prototype settings. Visual change does not prove water direction or
flood safety. Threshold changes remain separate in issue #109. See the
[design and coverage rules](docs/architecture/windowed-video-evidence.md).

### 17. Try Prototype Thresholds Against Human Labels

Run this after you have a local records file and a human label file.

```bash
python3 scripts/tune_thresholds.py \
  --records-path data/sites/example-site/outputs/records.jsonl \
  --labels-path data/sites/example-site/labels/example-labels.jsonl \
  --video-id demo-river-001 \
  --threshold 0.02 \
  --threshold 0.05 \
  --threshold 0.10
```

Simple meaning: this tries a few visual-change cutoff numbers and shows how many labels agree, disagree, or cannot be compared.

Cannot-compare cases stay separate. They are not counted as success.

This does not choose final flood thresholds. It only helps us learn from validation examples.

### 18. Summarize A Local POC Run

Run this after the local POC pipeline creates `data/sites/example-site/outputs/poc-records.jsonl`.

```bash
python3 - <<'PY'
from pathlib import Path

from openfloodai.replay import render_summary_markdown, summarize_jsonl_records

summary = summarize_jsonl_records(Path("data/sites/example-site/outputs/poc-records.jsonl"))

print(render_summary_markdown(summary))
PY
```

Simple meaning: this reads the saved JSON Lines file and prints a short report. For example, it can say how many records were created, what record types appeared, whether any `UNKNOWN` or degraded records appeared, and what the highest simple visual scores were.

If the run has risk-state records, the summary also shows the highest prototype risk confidence.

Simple meaning: this is the confidence from the current simple rule engine. It is not flood probability and it is not proof that the system is correct.

This report is only for local review and debugging. It does not create a public warning, publish anything, send alerts, or show private camera details.

### 19. Explain A POC Output For A Human Reviewer

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

### 20. Test Visual Signals Inside A Reference Region

This checks only the selected part of the image, like a virtual ruler.

```bash
python3 - <<'PY'
import numpy as np

from openfloodai.vision import compare_region_signals

previous_frame = np.zeros((10, 10), dtype=np.uint8)
current_frame = np.zeros((10, 10), dtype=np.uint8)
current_frame[5:, :] = 180

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

Simple meaning: this compares the watched box over time. The output includes `upper_region_change_score`, `middle_region_change_score`, `lower_region_change_score`, `strongest_changed_area`, and `water_level_evidence_state`.

Layman example: if the lower part of a bridge pillar changes but the upper part stays steady, that may be useful water-level evidence. If the whole box changes, it may be rain, glare, blur, or camera movement, so the result stays cautious.

This still does not detect floods. It only measures simple image change inside the selected area.

### 21. Generate Local Review Images

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
    Path("data/sites/example-site/outputs/review-images"),
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

Simple meaning: this creates the normal review images:

```text
review-baseline.png
review-changed.png
review-comparison.png
```

When a `reference_region` is provided, it also creates overlay images:

```text
review-baseline-overlay.png
review-changed-overlay.png
review-comparison-overlay.png
```

The overlay images show the watched reference region with a high-contrast box.

Layman example: if the system watched the lower part of a bridge pillar, the overlay image draws a box around that area so a person can quickly check whether the system looked in the right place.

These images are local review files only. Do not commit real review images to GitHub.

## Project Status

OpenFloodAI is in local proof-of-concept validation.

Current local helpers can read test videos, check video health, save records, load site/camera config, choose a watched reference region from a local image, run one safe end-to-end local smoke test, run a local review workflow for your own video, run multi-video site validation, compare system output with human labels, try prototype thresholds against labels, measure simple full-frame and reference-region signals, summarize saved records, generate local review images, document hard-case expectations, and create plain-language operator notes.

OpenFloodAI still does not detect real floods, train ML models, connect to live cameras, send alerts, publish public warnings, provide a production monitoring or fleet dashboard, or replace local emergency decision-making. The existing Home UI is a local validation and review tool only.

Next direction:

```text
more reviewed clips -> time-window comparison -> hard-case evidence -> locked validation set -> later ML
```

See the documentation site, `CONTRIBUTING.md`, and `SECURITY.md` before proposing functional changes.

## JOIN DISCORD FOR DISCUSSION
[OPENFLOODAI DISCORD](https://discord.gg/2VzpADTZ3)

Site validation writes directly into each run folder. It no longer creates a shared outputs/<video-id>/ folder or a new report directly under outputs/. Existing legacy folders are left untouched.

For a complete practice run without chat history, follow the [MVP workflow rehearsal checklist](docs/research/mvp-workflow-rehearsal.md). It covers five to ten videos, both review routes, result review, and recording confusing steps.

A step-by-step [HTML how-to guide](docs/learning/end-to-end-workflow.html) explains the full local workflow with examples and checkboxes. Open it directly in a browser or from the documentation site.

Create Site includes the first video and watched area. To add more videos to an existing site, use **+ Add Video** on that site. The form selects that site and lets you choose a video, watched area, and video details.

Use **+ Add Label** on a site to open a fresh human-label form with that site selected and its video IDs available.

Under **Review images**, use **View Path** to show the evidence folder, or **View Images** to browse generated images inside the Home UI. Click an image to open it at full size in a new tab. These images are served by the local Home UI server; nothing is uploaded. Empty runs show a message directing you to the validation report.

After updating Home UI Python code, restart the local server (Ctrl+C, then `python3 scripts/run_openfloodai_home_ui.py`) and refresh the browser. Refreshing the page alone does not load new server endpoints.

Under **Latest report**, use **View Path** to reveal the report location or **View Report** to read the complete report text in the Home UI. Both controls can be toggled closed. Restart the Home UI server after this update to load the report endpoint.

Latest results separate **What the machine saw**, **What the person saw**, **Human comparison**, and **Why** for each video time window. Missing labels explicitly show **No human label for comparison**. Other reasons, such as unclear machine evidence, an uncertain human review, missing output, or inadequate time coverage, remain visible. A visual change does not establish rising or falling water. Existing reports can show these explanations after restarting the Home UI server; new reports include the plain-language explanations too.
Each result also shows a human-comparison status tag: **Agree**, **Disagree**, or **Cannot compare**. The tag describes agreement with human review, not flood risk.

In **Add Label**, selecting a video defaults the start to **0 seconds** and the end to the video's duration. Both times stay editable. If duration cannot be read, enter the end time manually. Changing videos loads a new full-video window; refreshing site information preserves your edits for the same selection. Restart the Home UI server after updating to enable duration lookup.

**Run Validation** shows a spinner and **Running validation…** while waiting for the server. The clicked button is disabled and duplicate runs for the same site are ignored until the request finishes. The spinner clears on both success and failure.

The **Two ways to review a video** note appears in both Classic and Workflow views. Click its heading to expand or collapse it; it starts collapsed.

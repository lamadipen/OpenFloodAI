# OpenFloodAI dataset walkthrough: 20 dummy observations

**All values, reviews, identities and measurements are invented. This is NOT real USGS data and NOT training-ready.**
No real images or masks are included; image/mask paths and checksums are deliberately null.
This illustrates the proposed visual-first analysis layer, not an existing OpenFloodAI export schema.

## How the data arrives

1. Camera download supplies image bytes, source, capture time, site and camera.
2. Site setup supplies the fixed watched area, baseline, bank guides and their versions.
3. Segmentation supplies draft masks and model/prompt/crop provenance.
4. A person accepts/corrects the mask and records visibility. Failed masks are not zero water.
5. Proposed measurement logic calculates mask occupancy and before/after differences.
6. A person reviews visual change independently; matched gauge data is a separate cross-check.
7. Curation groups examples into versioned, isolated datasets; training is separately approved.

The demo uses one fictional stable river camera and a 100,000-pixel watched area.
Its illustrative fixed reference has 30% water. This is not a universal normal or danger threshold.

## All examples

| ID | UTC time | Scenario | Draft / accepted coverage | Matched gauge (ft) | Review | Split |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | 2025-06-01 10:00 | Rising | 30% | 3.2 | clear / accepted | train |
| A2 | 2025-06-01 10:15 | Rising | 35% | 3.5 | clear / accepted | train |
| A3 | 2025-06-01 10:30 | Rising | 42% | 4.1 | clear / accepted | train |
| A4 | 2025-06-01 10:45 | Rising | 48% | 4.6 | clear / accepted | train |
| B1 | 2025-06-08 10:00 | Falling | 48% | 4.6 | clear / accepted | train |
| B2 | 2025-06-08 10:15 | Falling | 44% | 4.2 | clear / accepted | train |
| B3 | 2025-06-08 10:30 | Falling | 39% | 3.8 | clear / accepted | train |
| B4 | 2025-06-08 10:45 | Falling | 33% | 3.4 | clear / accepted | train |
| C1 | 2025-06-15 10:00 | High and steady | 52% | 4.9 | clear / accepted | validation |
| C2 | 2025-06-15 10:15 | High and steady | 52% | 4.91 | clear / accepted | validation |
| C3 | 2025-06-15 10:30 | High and steady | 53% | 4.91 | clear / accepted | validation |
| C4 | 2025-06-15 10:45 | High and steady | 52% | 4.9 | clear / accepted | validation |
| D1 | 2025-06-22 10:00 | Rising | 31% | 3.3 | clear / accepted | test |
| D2 | 2025-06-22 10:15 | Rising | 36% | 3.7 | clear / accepted | test |
| D3 | 2025-06-22 10:30 | Rising | 43% | No match | clear / accepted | test |
| D4 | 2025-06-22 10:45 | Rising | 49% | 4.7 | clear / accepted | test |
| E1 | 2025-06-29 10:00 | Difficult views | 44% | 4.1 | clear / accepted | test |
| E2 | 2025-06-29 10:15 | Difficult views | 61% draft; rejected | 4.1 | glare / needs_correction | test |
| E3 | 2025-06-29 10:30 | Difficult views | 47% | 4.1 | camera_moved / accepted | test |
| E4 | 2025-06-29 10:45 | Difficult views | - | 4.2 | fog / unavailable | test |

## What to notice

- A: rising coverage; B: falling coverage.
- C: high-and-steady, with a little mask jitter. No change does not mean normal or safe.
- D3: a candidate gauge reading is 21 minutes away, outside the 15-minute limit. The accepted water mask remains useful.
- E2: 61% is an unreliable draft, not a usable increase. E3: mask acceptance does not establish camera alignment. E4: no mask, not zero water.
- All flood statuses are `not_established`. High water is not automatically flooding.
- Events and time periods stay together. This tiny one-site split only explains the structure and cannot establish generalization or training readiness.

## The files and their relationships

- `observations.jsonl`: 20 image-level records, including mask review, provenance placeholders, geometry version, gauge match and quality.
- `comparisons.jsonl`: 15 consecutive within-event pairs, linked by `earlier_id` and `later_id`. Contains derived coverage change and separately invented human answers.
- `manifest.json`: demo identity, limitations and counts.
- `explore_dataset.ipynb`: executed Python notebook, with displayed query results. It neither trains a model nor calls SAM.
- `checksums.sha256`: integrity hashes for the package.

JSONL means one JSON object per line. A real dataset would also include permitted source image and mask files with actual checksums.
Image training pairs are image pixels plus mask pixels, not just a row containing a percentage.
Net percentage changes do not reveal *where* new water appeared: actual masks are needed for added/lost-water overlays.

## Open and query

**Local Jupyter / VS Code:** extract the package and open `explore_dataset.ipynb` in that folder. Python with pandas and a notebook kernel is needed. Saved outputs can be read before rerunning.

**Google Colab:** open the `.ipynb`, then upload `observations.jsonl`, `comparisons.jsonl` and `manifest.json` when the first code cell asks. This is a cloud upload. Use only this dummy package until real-data sharing has been approved.
Official guide: https://colab.research.google.com/notebooks/io.ipynb

Example:

```python
import pandas as pd
images = pd.read_json('observations.jsonl', lines=True)
pairs = pd.read_json('comparisons.jsonl', lines=True)
accepted = images[images['hypothetical_segmentation_usable']]
rising = pairs[pairs['human_visual_label'] == 'water_level_rising']
```

## Share and preserve

Share the folder or ZIP on an external drive. No upload has been performed.
For a real public dataset: resolve image rights, annotation/model-output terms, privacy and geographic disclosure; publish a version, dataset card, split manifest and hashes.
Use Hugging Face/Kaggle only after those approvals. The app's existing frozen curation/release artifacts remain authoritative; this teaching layout is a proposed analysis view.
Real source imagery, masks and gauge provenance should stay reusable when the learning task changes.

## Suggested next decision

Confirm that this layout separates what the machine saw, what the human approved, what changed, and what the gauge reported.
Then choose one real site and a small permitted sample to test the missing mask-measurement layer. Do not bulk recollect data or train from this demo.

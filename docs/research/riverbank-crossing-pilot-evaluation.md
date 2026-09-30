# Riverbank-Crossing Pilot Evaluation

This workflow compares `riverbank_crossing_v1` evidence with samples reviewed
by a person. It helps us learn where the adapter works, where it fails, and
which conditions still need testing.

It does not confirm flooding, prove that a site is safe, or create a public
warning. The adapter remains separate from the risk engine.

## Simple Example

A person reviews one baseline/current image pair and says:

> Water-like change crossed the normal guide, and the overlay correctly showed
> the changed section.

The saved evidence also says `change`. That sample is a true positive.

If the adapter says `change` but the person says `no_change`, it is a false
crossing. Glare, shadows, vegetation, or camera movement may cause this.

## Before You Start

Run image-sequence validation with the optional `riverbank_crossing_v1`
adapter enabled. The run saves:

```text
data/sites/<site>/outputs/image-sequence-runs/<run-id>/evidence-records.jsonl
```

Keep real images and local pilot output out of git unless their source,
license, privacy, and retention rules are approved.

## Review In The UI

Open an image-sequence run in the Review UI, select an image with an available
riverbank overlay, and choose **Add human label**. The existing form collects
the normal water-level label and quality answers. It then asks only:

- Did visual change cross the normal guide?
- Does the highlighted overlay match what you see?

Muddy water, glare, shadows, vegetation, snow, and low light are optional
chips. The existing camera-stability answer is reused. The server automatically
links the exact saved riverbank evidence record, so the reviewer does not copy
an ID.

The review is saved with the rest of the run observations:

```text
data/sites/<site>/outputs/image-sequence-runs/<run-id>/human-review/observations.jsonl
```

Historical or externally prepared pilot files can still use the compact format:

```json
{"observation_id":"review-001","evidence_record_id":"evidence-example-001","expected_result":"change","conditions":["muddy_water","summer","high_water"],"overlay_review":"accepted","note":"The highlighted section matches the visible change."}
```

Use the `record_id` from the `riverbank_crossing_v1` row in
`evidence-records.jsonl` as `evidence_record_id`.

### Required Fields

| Field | Allowed values | Simple meaning |
| --- | --- | --- |
| `observation_id` | unique text | A local ID for this human review. |
| `evidence_record_id` | saved evidence ID | Connects the review to the exact machine result. |
| `expected_result` | `change`, `no_change`, `unclear` | What the reviewer could safely judge. |
| `conditions` | zero or more condition names below | What was visible in this sample. |
| `overlay_review` | `accepted`, `rejected`, `not_reviewed` | Whether the overlay helped and matched the visible evidence. |

Optional fields are `note` and `false_crossing_cause`. A false-crossing cause
may be `camera_movement`, `non_water_change`, `glare`, `shadows`, `vegetation`,
or `other`.

Supported conditions are:

- `clear_water` and `muddy_water`
- `glare`, `shadows`, `vegetation`, `snow`, and `low_light`
- `camera_movement`
- `spring`, `summer`, `autumn`, and `winter`
- `high_water` and `low_water`

Do not force a change/no-change answer when the image is unclear. Use
`expected_result: "unclear"` so uncertainty stays visible.

## Run The Evaluation

From the repository root with the virtual environment active:

```bash
python3 scripts/evaluate_riverbank_pilot.py \
  --evidence-path data/sites/<site>/outputs/image-sequence-runs/<run-id>/evidence-records.jsonl \
  --reviews-path data/sites/<site>/outputs/image-sequence-runs/<run-id>/human-review/observations.jsonl \
  --output-path data/sites/<site>/outputs/image-sequence-runs/<run-id>/riverbank-pilot-evaluation.md \
  --json-output-path data/sites/<site>/outputs/image-sequence-runs/<run-id>/riverbank-pilot-evaluation.json
```

The Markdown file is for people. The JSON file contains the same result in a
machine-readable form.

When the JSON file is saved with the exact name shown above, open that run in
the Review UI. A **Riverbank-crossing pilot evaluation** card displays the main
metrics, tested conditions, false-crossing causes, processing cost, and safety
boundary. A run without this file shows that its pilot evaluation has not been
generated yet.

## What The Report Measures

- **Precision:** when the adapter showed a crossing, how often the reviewer
  also marked change.
- **Recall:** when the reviewer marked change, how often the adapter showed a
  crossing.
- **Unavailable/failure rate:** how often the adapter could not provide an
  available measurement, including missing evidence.
- **False crossings:** change reported when the reviewer marked no change.
- **Processing time:** mean and p95 adapter time from saved evidence.
- **Input-frame memory:** the baseline and current NumPy image sizes. This is a
  repeatable lower-bound estimate, not peak process memory.
- **Overlay acceptance:** accepted overlays divided by accepted plus rejected
  overlays. `not_reviewed` does not count as accepted.

The report also calculates these results separately for each supported
condition. A condition with no reviewed sample says `Not available`. It is
**not tested**, not successful.

## Safety Boundary

A strong result from a small pilot does not prove performance at another
river, camera, season, or weather condition. Review sample counts and failure
examples alongside every percentage.

Do not combine this adapter with the main risk decision until it shows a
measurable, independently reviewed improvement over the existing pixel-change
baseline. Human review and independent evidence remain required for any safety
decision.

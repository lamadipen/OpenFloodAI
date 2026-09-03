# Roadmap

This roadmap is a simple first version. It will change as the project learns from tests, datasets, and field needs.

OpenFloodAI is moving toward an edge-first camera system that watches a configured river area, measures simple water-level or water-coverage changes over time, saves clear metadata, and supports human review before any public warning action.

## Phases

| Phase | Focus | Status |
| --- | --- | --- |
| Phase 1 | Foundation and requirements | Complete |
| Phase 2 | Research and validation preparation | Complete |
| Phase 3 | Multi-video validation and reporting | Complete |
| Phase 4 | Better reference-region water-change baseline | Started |
| Phase 5 | Larger validation set and time-window comparison | Started |
| Phase 6 | Edge-device deployment | Planned |
| Phase 7 | Alert system | Planned |
| Phase 8 | Field pilot | Planned |
| Phase 9 | Production hardening | Planned |

## Current Engineering Path

The near-term backend path is:

```text
video input -> feed health -> simple visual signals -> risk state -> saved local records
```

Simple example: first we prove that a local video can be read and records can be saved. Later we add real visual signals and stronger risk logic.

The longer-term direction is:

```text
configured river area -> virtual ruler or reference region -> water-level or water-coverage change -> clear metadata -> human review before public warning
```

Simple example: a camera watches the same bridge every day. A marked part of the image works like a ruler. If water covers more of that marked area over time, OpenFloodAI should save evidence that a person can review.

## Current Progress

OpenFloodAI can now do the early local POC steps.

Completed or started:

- repository foundation, CI checks, and project structure
- V1 requirements, architecture notes, reason codes, and data contracts
- JSON schema validation for event/audit records
- local JSON Lines record writing and reading
- local video health checks
- local video frame metadata extraction
- local reference-region selector for choosing a watched image area
- simple visual signal records from frames
- rule-based test risk-state evaluation
- local POC pipeline from video to saved records
- region-based local POC pipeline using a configured reference region
- end-to-end local POC smoke workflow using safe synthetic input
- validation dataset folder structure for multiple sites
- local comparison report for system output and human labels
- multi-video local validation runner for one site folder
- combined validation summary report with totals and per-video rows
- prototype threshold tuning report for comparing visual-change settings with human labels
- hard-case expected behavior for confusing inputs
- improved reference-region signal with upper, middle, and lower band scores
- time-window comparison between human labels and matching machine records
- validation results and known-limits tracker
- local replay summary report for saved POC records
- plain-language operator notes for POC outputs
- local review images for biggest visual changes
- safe site and camera config loading
- privacy and retention policy for local POC data
- MkDocs documentation site
- research note for ML models, datasets, Google ML options, and public water-data inspiration
- human labeling guide for water-change review

Simple example: today a developer can choose a watched image area, run a local video through the POC pipeline, save records to `data/local-runs/poc-records.jsonl`, print a short summary, create plain-language notes, generate a few local review images, organize validation data by site, run multi-video site validation, compare labels with system output, try prototype thresholds against labels, update the validation status page, or run one safe smoke test that checks the full local review flow.

## Completed Phase Summary

The foundation and validation-prep work is now in place.

In simple terms, OpenFloodAI can now:

```text
take a local video
check if it is usable
look at a selected area
measure simple visual change
save records
generate review images
let a human label the video
compare human label vs system output
try different thresholds
document what worked and what did not
```

This does not prove flood detection. It gives developers and reviewers a small, repeatable way to inspect evidence.

## Next Direction

The next direction is to turn local validation from "it runs one demo" into "it helps us compare many reviewed examples honestly."

Focus on five small pieces:

1. More approved validation clips

   Add a small set of videos that are safe to use and easy to review.

   Simple example: use a few normal clips, a few possible rising-water clips, and a few unclear clips.

2. More machine outputs inside each label window

   The comparison can use matching time windows now. Next, the pipeline should create more useful machine records inside each reviewed window.

   Simple example: if the human labels `00:30 to 01:00`, create machine evidence inside that same range, not only near the video start.

3. Real hard-case evidence

   Add safe examples for glare, darkness, camera shake, blocked views, and unreadable input.

   Simple example: a dark video should stay `DEGRADED` or `cannot_compare`, not success.

4. Locked validation set

   Keep a small set of reviewed examples that are not changed every time thresholds are tuned.

   Simple example: tune on practice clips, then check against a separate fixed set.

5. Clear review outputs

   Keep reports simple enough for people who are not ML engineers.

   Simple example: "lower watched area changed, but this is not proof of flooding."

Important choice: do not jump straight into ML yet.

The safer path is:

```text
reference region -> simple water/change scores -> saved records -> human review -> labels -> later ML
```

This keeps the project understandable, testable, and safer.

## What Is Not Done Yet

OpenFloodAI does not yet:

- detect real floods accurately
- train or package ML models
- send alerts
- run a public warning workflow
- provide a dashboard
- connect to live cameras
- use real cloud ML services
- replace local emergency decision-making

## What Comes Next

Near-term work should stay small and testable:

1. Add more reviewed clips for one or two site folders.
2. Create more machine outputs inside each reviewed time window.
3. Add safe real examples for hard cases.
4. Define a small locked validation set.
5. Keep improving the reference-region signal and review report.

Simple meaning: first gather better reviewed examples, then make comparison fairer, then decide whether ML work is ready.

Also keep strengthening privacy, validation, and failure handling as the project grows.

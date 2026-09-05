# OpenFloodAI

OpenFloodAI is an open-source project for low-cost river flood detection support.

The idea is simple: use a fixed camera near a river, run checks close to the camera, and create clear records when something may need human review.

OpenFloodAI is not a finished public warning system yet. Early code must not send public warnings or make emergency decisions by itself.

## Completed Phase Summary

OpenFloodAI has a usable local validation MVP. The project is still a proof of
concept, but contributors can prepare labelled examples, run validation, inspect
scorecards and evidence, and compare recent local reports without cloud services.

In simple terms, the project can now:

```text
take a local video
check if it is usable
look at a selected area
measure simple visual change
save records
generate review images
let a human label the video
compare human label vs system output
compare matching time windows
try different thresholds
check hard-case expectations
document what worked and what did not
```

Simple example: a developer can run a short local video, mark the lower part of a bridge pillar, save records, create review images, and compare the result with a human label.

This is still not real flood detection. Current output means "please review this evidence," not "there is a confirmed flood."

## What The Project Is Building

OpenFloodAI is building toward this path:

```text
video input -> feed health -> simple visual signals -> risk state -> saved local records
```

Simple example: if a camera sees a riverbank every day, the system may later notice when water covers more of that bank. It should explain what it saw and ask for review. It should not tell the public to evacuate.

The next practical direction is:

```text
reference region -> region-based visual signals -> review images -> human labels -> later ML
```

Simple example: a marked part of a bridge pillar can act like a virtual ruler. OpenFloodAI can measure simple changes in that watched area, save records, create a few local review images, and help a person label what happened.

## Current Status

The project is still in proof-of-concept preparation.

OpenFloodAI can currently:

- define shared data contracts
- validate event/audit JSON records
- check local video health
- extract local video frame metadata
- store local JSON Lines records
- load safe site and camera config
- measure simple full-frame and reference-region visual signals
- run a small test-only risk-state evaluator
- run local POC pipelines that save review records
- create local replay summaries
- write plain-language operator notes
- generate local review images for biggest visual changes
- read human labels and compare them with system output
- compare human labels with machine records from the same time window
- try prototype thresholds against human labels
- run multi-video local validation for one site folder
- create a combined validation summary report
- use the local Home UI to check site readiness and run validation
- follow guided next-step messages when site files are missing
- inspect the latest scorecard, report preview, evidence path, and recent run history
- run deterministic synthetic known-answer validation checks
- use the labelled data quality checklist before adding examples
- document hard-case expected behavior for missing, dark, glare, shaky, and blocked-view inputs
- track validation results and known limits
- provide privacy, retention, ML research, and labeling guidance

OpenFloodAI still does not detect real floods, train ML models, send alerts, publish warnings, run live camera deployments, or replace local emergency decision-making. The Home UI is a local validation and review tool, not a production monitoring or fleet dashboard.

The current runtime uses Python, `jsonschema`, `numpy`, and OpenCV. Development
checks use pytest, Ruff, mypy, and MkDocs. See the [dependency map](architecture/dependencies.md).

Near-term work should stay focused on more reviewed clips, more machine outputs inside each label window, hard-case evidence, stronger reference-region baselines, and safer test datasets.

## Next Priorities

Next goals:

1. Add more approved validation clips.
2. Create more machine outputs inside each reviewed time window.
3. Add real hard-case examples when they are safe to share.
4. Create a small locked validation set before ML training.
5. Keep the docs honest about what is proven and what is not.

Simple meaning: test more reviewed videos, keep unclear cases visible, and improve the watched-region signal slowly.

## Follow The Project

- [GitHub repository](https://github.com/lamadipen/OpenFloodAI)
- [Discord discussion](https://discord.gg/2VzpADTZ3)

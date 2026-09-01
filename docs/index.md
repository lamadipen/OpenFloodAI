# OpenFloodAI

OpenFloodAI is an open-source project for low-cost river flood detection support.

The idea is simple: use a fixed camera near a river, run checks close to the camera, and create clear records when something may need human review.

OpenFloodAI is not a finished public warning system yet. Early code must not send public warnings or make emergency decisions by itself.

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

- shared data contracts
- event/audit validation helpers
- local video health checks
- local video frame metadata extraction
- local JSON Lines record storage
- safe site and camera config loading
- simple full-frame and reference-region visual signals
- a small test-only risk-state evaluator
- local POC pipelines that save review records
- local replay summaries
- plain-language operator notes
- local review images for biggest visual changes
- privacy and retention guidance
- ML/model research notes
- a human labeling guide

OpenFloodAI still does not detect real floods, train ML models, send alerts, publish warnings, run live camera deployments, or replace local emergency decision-making.

Near-term work should stay focused on simple reference-region baselines, review images, human labels, and safer test datasets.

## Follow The Project

- [GitHub repository](https://github.com/lamadipen/OpenFloodAI)
- [Discord discussion](https://discord.gg/2VzpADTZ3)

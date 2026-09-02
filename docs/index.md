# OpenFloodAI

OpenFloodAI is an open-source project for low-cost river flood detection support.

The idea is simple: use a fixed camera near a river, run checks close to the camera, and create clear records when something may need human review.

OpenFloodAI is not a finished public warning system yet. Early code must not send public warnings or make emergency decisions by itself.

## Completed Phase Summary

OpenFloodAI has completed the first foundation and validation-prep phase.

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
try different thresholds
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
- try prototype thresholds against human labels
- track validation results and known limits
- provide privacy, retention, ML research, and labeling guidance

OpenFloodAI still does not detect real floods, train ML models, send alerts, publish warnings, run live camera deployments, or replace local emergency decision-making.

Near-term work should stay focused on simple reference-region baselines, review images, human labels, and safer test datasets.

## Next Priorities

Recommended next issue order:

1. OF-031: add a multi-video validation runner.
2. OF-032: generate a validation summary report.
3. OF-034: add hard-case validation examples and expected behavior.
4. OF-033: improve the water-level change signal using the reference region.
5. OF-035: update documentation with current validation progress and next goals.

Simple meaning: first run more videos, then summarize the results, then test hard cases, then improve the signal.

## Follow The Project

- [GitHub repository](https://github.com/lamadipen/OpenFloodAI)
- [Discord discussion](https://discord.gg/2VzpADTZ3)

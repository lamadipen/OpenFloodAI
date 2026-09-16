# Project Overview

*This page is for developers and contributors. Looking for a non-technical
introduction? See the [Overview for Hydrologists & Disaster Management](end-user-overview.md).*

OpenFloodAI aims to help communities watch river conditions using affordable hardware.

Many places cannot install expensive river sensors everywhere. Some places may already have a camera, a small computer, and limited internet. OpenFloodAI explores whether that setup can help create useful warning-support evidence.

## Plain-Language Goal

The system should help answer:

```text
Does this camera show signs that river conditions may need human review?
```

It should not answer:

```text
Should the public evacuate right now?
```

Official public warnings must stay with approved local authorities and trusted emergency processes.

## Product Direction

OpenFloodAI is inspired by systems that use smart cameras and computer vision to watch water level changes near rivers, bridges, and flood-prone areas.

One useful reference is [Noema Flood Detection](https://noema.tech/flood/). Their page describes ideas such as edge camera processing, virtual rulers, water coverage monitoring, metadata output, and operator alarms.

OpenFloodAI's open-source goal is similar in concept, but cautious:

- run useful checks near the camera when possible
- let a user configure the part of the image to watch
- create simple records that explain what the system saw
- support human review before public warning decisions
- keep privacy, cost, and low-connectivity deployments in mind

Simple example: a camera watches a river bridge. A marked region in the image acts like a virtual ruler. If water covers more of that region over time, OpenFloodAI should save clear evidence for review. It should not automatically tell the public to evacuate.

## How The Pieces Fit

The near-term backend path is:

```text
video input
-> feed health
-> simple visual signals
-> risk state
-> saved local records
```

Simple example:

1. A video file or camera stream provides frames.
2. The system checks whether the camera/feed looks usable.
3. A future vision module creates simple numbers, such as how much water-like area is visible.
4. The risk engine turns those inputs into a test risk state.
5. The result is saved locally so people can inspect what happened.

The longer-term direction is:

```text
configured river area -> virtual ruler or reference region -> water-level or water-coverage change -> clear metadata -> human review before public warning
```

Simple example: a camera watches the same bridge every day. A marked part of the image works like a ruler. If water covers more of that marked area over time, OpenFloodAI should save evidence that a person can review.

## Phases

This roadmap is a simple first version. It will change as the project learns from tests, datasets, and field needs.

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

The phases depend on each other. The local validation workflow, scorecard, Home
UI, windowed sampling, evidence images, threshold rules, synthetic fixtures, and
label-quality checklist come before a locked dataset, ML work, field pilot, or
alert design. Passing local tests does not move the project to production readiness.

## Current Status

OpenFloodAI has a usable local validation MVP. It can currently:

- define shared data contracts and validate event/audit JSON records
- read a local video file, check whether it is usable, and extract frame metadata
- load safe site and camera config
- measure simple full-frame and reference-region visual signals, with upper, middle, and lower band scores
- write and read local JSON Lines records
- run a rule-based test risk-state evaluator
- run local POC pipelines (full-frame and region-based) that save review records
- create local replay summaries and plain-language operator notes
- generate local review images for the biggest visual changes
- read human labels and compare them with system output
- compare human label windows with matching machine records from the same time range
- try prototype visual-change thresholds against human labels
- run multi-video local validation for one site folder and create a combined summary report
- use the local Home UI to check site readiness, follow next-step guidance, run validation, and inspect scorecards, report previews, evidence paths, and recent run history
- run deterministic synthetic known-answer checks for rising, falling, no-change, and unreadable inputs
- use a labelled data quality checklist before preparing new examples
- document hard-case expected behavior for confusing inputs (missing, dark, glare, shaky, blocked-view)
- track validation results and known limits
- provide privacy, retention, ML research, and labeling guidance

Simple example: a developer can run a local video, mark the lower part of a bridge pillar as the watched area, save records, generate review images, label the video as `water_level_rising`, and compare that label with the system output.

OpenFloodAI still does not:

- detect real floods accurately
- train or package ML models
- connect to live cameras or run a live-camera adapter
- send alerts or run a public warning workflow
- use real cloud ML services
- provide a production monitoring or fleet dashboard
- replace local emergency decision-making

The current implementation is local proof-of-concept validation. The runtime is
small and does not include a trained ML framework, cloud service, live-camera
adapter, database, or alert provider. These are future engineering stages, not
missing setup steps for the current MVP.

## Next Direction

The current validation direction is:

```text
more reviewed clips -> more records inside each label window -> hard-case evidence -> locked validation set -> later ML
```

Simple meaning: first test more reviewed videos, compare the system and human labels over the same seconds, and keep confusing cases visible. ML should come later, after the project has safe labeled examples and stronger evaluation.

What is already in place: multi-video validation for one local site folder, a
combined validation summary report, comparison between human label windows and
matching machine records, an improved reference-region signal with upper,
middle, and lower band scores, documented hard-case expected behavior, and
known-limits tracking.

Focus on five small pieces next:

1. **More approved validation clips** — add a small set of videos that are safe to use and easy to review.
   Simple example: use a few normal clips, a few possible rising-water clips, and a few unclear clips.
2. **More machine outputs inside each label window** — the comparison can use matching time windows now; next, the pipeline should create more useful machine records inside each reviewed window.
   Simple example: if the human labels `00:30 to 01:00`, create machine evidence inside that same range, not only near the video start.
3. **Real hard-case evidence** — add safe examples for glare, darkness, camera shake, blocked views, and unreadable input.
   Simple example: a dark video should stay `DEGRADED` or `cannot_compare`, not success.
4. **Locked validation set** — keep a small set of reviewed examples that are not changed every time thresholds are tuned.
   Simple example: tune on practice clips, then check against a separate fixed set.
5. **Clear review outputs** — keep reports simple enough for people who are not ML engineers.
   Simple example: "lower watched area changed, but this is not proof of flooding."

Important choice: do not jump straight into ML yet. First define a locked data
split, label-quality rules, evaluation metrics, and failure-case gates. Also keep
strengthening privacy, validation, and failure handling as the project grows.

The safer path is:

```text
reference region -> simple water/change scores -> saved records -> human review -> labels -> later ML
```

This keeps the project understandable, testable, and safer.

## Safety Boundaries

OpenFloodAI must be careful because flood warnings can affect real people.

The project should:

- show degraded or unknown states when evidence is poor
- explain why a risk state was chosen
- keep raw video and exact locations private unless a site policy allows them
- keep public warnings separate from prototype code
- use field evidence before making safety claims

Simple example: if the camera is broken, the system should say `UNKNOWN`. It should not say `NORMAL`.

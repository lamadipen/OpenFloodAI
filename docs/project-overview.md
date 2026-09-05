# Project Overview

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

The first backend path is:

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

## Current POC Status

OpenFloodAI can now run small local proof-of-concept steps.

The completed foundation phase means the project can now connect the basic local review flow:

```text
local video
-> health check
-> selected reference region
-> simple visual-change records
-> review images
-> human labels
-> time-window comparison
-> comparison and threshold reports
-> validation notes
-> hard-case expectations
```

Simple example: a reviewer can watch one video, label it as `water_rising`, and compare that label with the simple system output.

It can:

- read a local video file
- check whether the video is usable
- create frame metadata records
- load safe site and camera config
- measure simple full-frame visual signals
- measure simple signals inside a configured reference region
- write local JSON Lines records
- create a test risk-state record
- summarize saved records
- turn technical records into plain-language operator notes
- generate a few local review images for the biggest visual change
- read human labels
- compare human labels with local system output
- compare label windows with machine records from the same time range
- try prototype visual-change thresholds
- run multi-video local validation and create a combined summary report
- use the local Home UI to inspect site readiness, follow next-step guidance, and run validation
- document hard-case expected behavior for confusing inputs
- track validation results and known limits
- provide privacy, retention, ML research, and labeling guidance

Simple example: a developer can run a local video, save records, generate a comparison image with the watched area marked, and use the labeling guide to describe what changed.

OpenFloodAI still cannot:

- detect real floods accurately
- train or package ML models
- connect to live cameras
- send alerts
- publish public warnings
- provide a production monitoring or fleet dashboard
- replace local emergency decision-making

## Current Validation Direction

The current validation direction is:

```text
more reviewed clips -> more records inside each label window -> hard-case evidence -> locked validation set -> later ML
```

Simple meaning: first test more reviewed videos, compare the system and human labels over the same seconds, and keep confusing cases visible. ML should come later, after the project has safe labeled examples and stronger evaluation.

What is already in place:

- multi-video validation for one local site folder
- combined validation summary report
- comparison between human label windows and matching machine records
- improved reference-region signal with upper, middle, and lower region change scores
- documented hard-case expected behavior
- known-limits tracking

What should come next:

1. Add more approved validation clips for different conditions.
2. Create more machine outputs inside each reviewed time window.
3. Add real hard-case samples when they are safe to share.
4. Define a small locked validation set before ML training.
5. Keep review outputs simple enough for local teams and non-technical reviewers.

## Safety Boundaries

OpenFloodAI must be careful because flood warnings can affect real people.

The project should:

- show degraded or unknown states when evidence is poor
- explain why a risk state was chosen
- keep raw video and exact locations private unless a site policy allows them
- keep public warnings separate from prototype code
- use field evidence before making safety claims

Simple example: if the camera is broken, the system should say `UNKNOWN`. It should not say `NORMAL`.

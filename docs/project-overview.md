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

## Safety Boundaries

OpenFloodAI must be careful because flood warnings can affect real people.

The project should:

- show degraded or unknown states when evidence is poor
- explain why a risk state was chosen
- keep raw video and exact locations private unless a site policy allows them
- keep public warnings separate from prototype code
- use field evidence before making safety claims

Simple example: if the camera is broken, the system should say `UNKNOWN`. It should not say `NORMAL`.

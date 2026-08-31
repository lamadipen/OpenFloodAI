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

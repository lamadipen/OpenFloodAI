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

## Current Status

The project is still in foundation and proof-of-concept preparation.

Current work includes:

- shared data contracts
- event/audit validation helpers
- local video frame metadata
- local JSON Lines record storage
- a small test-only risk-state evaluator

Future work will add camera health checks, visual signal generation, better testing, and field validation.

## Follow The Project

- [GitHub repository](https://github.com/lamadipen/OpenFloodAI)
- [Discord discussion](https://discord.gg/2VzpADTZ3)

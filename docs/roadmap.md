# Roadmap

This roadmap is a simple first version. It will change as the project learns from tests, datasets, and field needs.

OpenFloodAI is moving toward an edge-first camera system that watches a configured river area, measures simple water-level or water-coverage changes over time, saves clear metadata, and supports human review before any public warning action.

## Phases

| Phase | Focus | Status |
| --- | --- | --- |
| Phase 1 | Foundation and requirements | Mostly complete |
| Phase 2 | Research existing technology and datasets | Planned |
| Phase 3 | Build baseline flood detection | Planned |
| Phase 4 | Historical-video testing | Planned |
| Phase 5 | Real-time camera pipeline | Planned |
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

## What Is Not Done Yet

OpenFloodAI does not yet:

- detect real floods accurately
- train or package ML models
- send alerts
- run a public warning workflow
- provide a dashboard
- replace local emergency decision-making

## What Comes Next

Near-term work should stay small and testable:

- create camera/feed health records
- create simple visual signal records
- connect visual signals to the risk-state skeleton
- save local event and audit records for review
- add replay tests using safe sample or generated data

# Roadmap

This roadmap is a simple first version. It will change as the project learns from tests, datasets, and field needs.

OpenFloodAI is moving toward an edge-first camera system that watches a configured river area, measures simple water-level or water-coverage changes over time, saves clear metadata, and supports human review before any public warning action.

## Phases

| Phase | Focus | Status |
| --- | --- | --- |
| Phase 1 | Foundation and requirements | Mostly complete |
| Phase 2 | Research existing technology and datasets | Started |
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

## Current Progress

OpenFloodAI can now do the early local POC steps.

Completed or started:

- repository foundation, CI checks, and project structure
- V1 requirements, architecture notes, reason codes, and data contracts
- JSON schema validation for event/audit records
- local JSON Lines record writing and reading
- local video health checks
- local video frame metadata extraction
- simple visual signal records from frames
- rule-based test risk-state evaluation
- local POC pipeline from video to saved records
- region-based local POC pipeline using a configured reference region
- local replay summary report for saved POC records
- plain-language operator notes for POC outputs
- local review images for biggest visual changes
- safe site and camera config loading
- privacy and retention policy for local POC data
- MkDocs documentation site
- research note for ML models, datasets, Google ML options, and public water-data inspiration
- human labeling guide for water-change review

Simple example: today a developer can run a local video through the POC pipeline, save records to `data/local-runs/poc-records.jsonl`, print a short summary, create plain-language notes, and generate a few local review images.

## Next Direction

The next direction is to turn the POC from "it creates records" into "it helps a person understand water change in one camera view."

Focus on five small pieces:

1. Reference region or virtual ruler

   Let a user define the part of the image to watch.

   Simple example: watch the lower half of a bridge pillar. The system should track changes in that area, not the whole image.

2. Water change baseline

   Create a simple baseline that compares the watched area over time.

   Simple example: frame 1 looks normal, but frame 50 has more water-like change in the watched area, so the score increases.

3. Human review output

   Create output that is easy for a person to read after a run.

   Simple example:

   ```yaml
   time_window: 00:00 to 00:30
   watched_area_change: 42%
   risk_state: WATCH
   reason: Water-like area increased inside the reference region.
   ```

4. Labeling guide

   Before ML training, define what humans should label. See the [Human Labeling Guide](research/labeling-guide.md).

   Simple labels can include:

   - normal water
   - rising water
   - high water
   - unclear view
   - camera moved
   - poor visibility

5. Small sample dataset plan

   Do not collect a huge dataset yet. Start with a few safe clips.

   Simple starting set:

   - 2 normal clips
   - 2 rising-water clips, if available and approved
   - 2 bad-quality clips
   - 1 missing or unreadable input case

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

- define the first baseline water-region or virtual-ruler signal
- use the labeling guide on safe local examples
- improve replay examples using generated or approved local data
- keep connecting reference-region config into local POC review tools
- keep strengthening privacy, validation, and failure handling

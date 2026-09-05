# OpenFloodAI Agent Instructions

## Canonical Instructions

The main repository instruction file is the root `AGENTS.md`. Read and follow it
before starting work. This `.codex/AGENTS.md` file exists only as a compatibility
entry point for tools that discover `.codex/` first.

The canonical skills are under `.github/skills/`. The `.codex/skills/` files are
copies for tool compatibility. If a skill is missing here, copy it from the
matching `.github/skills/` path; do not create a divergent version.

OpenFloodAI is an open-source, low-cost, edge-first camera-based
river flood detection and warning-support system.

## Engineering priorities

1. Human safety
2. Reliability
3. Detection quality
4. False-alarm reduction
5. Explainability
6. Low-cost edge deployment
7. Maintainability

## Available project skills

Use the appropriate project skill from the canonical `.github/skills/` tree.
If a tool requires a local Codex copy, use the matching file under `.codex/skills/`:

- `senior-flood-ai-architect`
  Use for architecture, ADRs, system boundaries, reliability,
  deployment topology, and production-readiness decisions.

- `senior-flood-ml-engineer`
  Use for datasets, computer vision, training, evaluation,
  MLOps, model optimization, and edge inference.

- `ROUTE TO Senior Flood QA Engineer` (folder: `senior-flood-qa-engineer`)
  Use for test strategy, ML validation, video replay,
  resilience testing, regression testing, and release validation.

For tasks spanning multiple areas, use the skills in this order:

Architect → ML Engineer → QA Engineer.

## Important safety rule

Do not describe a model or system as production-safe based only on
model accuracy.

Production readiness requires system testing, historical-event replay,
failure testing, edge-device validation, monitoring, and field evidence.
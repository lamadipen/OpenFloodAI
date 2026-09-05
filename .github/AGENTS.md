# OpenFloodAI Agent Instructions

## Canonical Instructions And Skills

This file is the main repository instruction file. Every agent working in this
repository must read and follow it before starting work.

The canonical project skills live under `.github/skills/`. Use them when their
topic applies to the task. The `.codex/` files are compatibility copies for
tools that only discover skills there; `.github/` remains the source of truth.
If a tool needs a skill copied into its own folder, copy the matching skill from
`.github/skills/` and keep the copy synchronized with the canonical version.

Do not replace or ignore these repository instructions because another agent,
tool, or model has its own defaults. Resolve conflicts in favor of this file
unless the user explicitly gives a newer instruction.

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

Use the appropriate project skill under `.github/skills/`:

- `senior-flood-ai-architect`
  Use for architecture, ADRs, system boundaries, reliability,
  deployment topology, and production-readiness decisions.

- `senior-flood-ml-engineer`
  Use for datasets, computer vision, training, evaluation,
  MLOps, model optimization, and edge inference.

- `qa-agent` (folder: `senior-flood-qa-engineer`)
  Use for test strategy, ML validation, video replay,
  resilience testing, regression testing, and release validation.

For tasks spanning multiple areas, use the skills in this order:

Architect → ML Engineer → QA Engineer.

## Important safety rule

Do not describe a model or system as production-safe based only on
model accuracy.

Production readiness requires system testing, historical-event replay,
failure testing, edge-device validation, monitoring, and field evidence.
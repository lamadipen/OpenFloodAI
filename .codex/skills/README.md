# OpenFloodAI Senior Engineering Skills

Project-local skills tailored for a production-grade, low-cost, open-source camera-based river flood detection and warning-support platform.

The canonical repository instructions are in `.github/AGENTS.md`. Read that file
before using these compatibility copies. Keep `.codex/skills/` synchronized with
the matching `.github/skills/` files.

- `senior-flood-ai-architect/` — system architecture, ADRs, edge/cloud boundaries, reliability and production gates.
- `senior-flood-ml-engineer/` — datasets, CV/ML experiments, evaluation, MLOps, edge optimization and monitoring.
- `senior-flood-qa-engineer/` — independent QA, ML validation, replay, resilience, edge and field acceptance.
- `our-coding-standard/` — delivery checklist for requirements, tests, lint/type checks, docs, privacy, and commits.

These are original refinements informed by current public Agent Skills patterns and production engineering/MLOps/QA practices. They do not copy a single community skill verbatim.

Recommended workflow:
Our Coding Standard keeps each change complete → Architect defines boundaries and acceptance requirements → ML Engineer creates evidence-producing models/pipelines → QA independently verifies system/model behavior → Architect/product owner reviews release evidence.

For a life-safety-adjacent system, the skills deliberately distinguish flood detection/decision support from authoritative public warning. Field validation, local operational ownership, redundant evidence, and documented escalation remain required.

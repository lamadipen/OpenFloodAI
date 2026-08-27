# OpenFloodAI Senior Engineering Skills

Three role skills tailored for a production-grade, low-cost, open-source camera-based river flood detection and warning-support platform.

- `senior-flood-ai-architect/` — system architecture, ADRs, edge/cloud boundaries, reliability and production gates.
- `senior-flood-ml-engineer/` — datasets, CV/ML experiments, evaluation, MLOps, edge optimization and monitoring.
- `senior-flood-qa-engineer/` — independent QA, ML validation, replay, resilience, edge and field acceptance.

These are original refinements informed by current public Agent Skills patterns and production engineering/MLOps/QA practices. They do not copy a single community skill verbatim.

Recommended workflow:
Architect defines boundaries and acceptance requirements → ML Engineer creates evidence-producing models/pipelines → QA independently verifies system/model behavior → Architect/product owner reviews release evidence.

For a life-safety-adjacent system, the skills deliberately distinguish flood detection/decision support from authoritative public warning. Field validation, local operational ownership, redundant evidence, and documented escalation remain required.

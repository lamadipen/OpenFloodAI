# OpenFloodAI Agent Instructions

This is the main rulebook for all coding agents and contributors working in this
repository.

Before starting work:

- Read the GitHub issue or task.
- Check dependencies and the current worktree.
- Work on one issue at a time.
- Keep OpenFloodAI camera-first for the current MVP.
- Keep UI work connected to `tools/openfloodai-home-ui.html`.
- Do not upload or publish private videos or images.
- Do not send alerts or public warnings.
- Do not claim production flood detection accuracy.
- Do not start ML training until the ML readiness gate is met.
- Add or update tests for behavior changes.
- Update docs when product direction or user-visible behavior changes.

If you are running inside Codex, also read `.codex/AGENTS.md` and the skills under
`.codex/skills/`. The canonical project skills are maintained under
`.github/skills/`; compatibility copies may also exist under `.codex/skills/`.

The project is a local validation and warning-support proof of concept. Human
review, privacy, field evidence, independent QA, and clear degraded states are
required before any future production or public-warning decision.

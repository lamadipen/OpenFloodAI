---
name: our-coding-standard
description: OpenFloodAI delivery checklist for repository changes. Use when implementing, reviewing, or finishing code, docs, scripts, tests, UI, data, or pipeline work in this repo so requirements, checks, docs, privacy, and handoff notes are handled consistently.
---

# Our Coding Standard

Use this skill whenever you make or review changes in OpenFloodAI.

OpenFloodAI is a warning-support project, so every change should be easy to understand, tested, and honest about what it does and does not prove.

## Before Editing

1. Read the request, issue, and nearby repo files first.
2. Check the git worktree and do not overwrite unrelated user changes.
3. Say the proposed change in simple words before editing when the user asks for planning or the change has risk.
4. Identify assumptions, especially around safety, privacy, data layout, and local-only files.
5. Keep the change focused on the issue. Do not add flood detection, ML, APIs, uploads, alerts, or business logic unless the issue asks for it.

## While Implementing

1. Make sure the stated requirement is actually fulfilled.
2. Follow existing project patterns before adding a new style or abstraction.
3. Add or update tests for the changed behavior.
4. Keep examples simple enough for a non-engineer to follow.
5. Update `README.md`, `READMELOCAL.md`, MkDocs pages, data contracts, or research docs when commands, workflows, outputs, schemas, or user-facing behavior change.
6. Do not commit private videos, raw local run outputs, secrets, personal paths, or site-specific files that should stay local.
7. For safety-related behavior, be clear that OpenFloodAI supports human review and does not issue official public warnings by itself.

## Required Checks

Run the relevant checks before final delivery:

```bash
python3 -m ruff format --check .
python3 -m ruff check .
python3 -m mypy src tests
python3 -m pytest
```

Also run these when they apply:

```bash
python3 -m mkdocs build --strict
```

Use the MkDocs check when documentation navigation, docs pages, or site content changes.

Run a targeted manual command when the feature adds a script, local pipeline, UI, data tool, or example workflow. For example, if a new script writes a summary file, run that script against the example site or a generated test input.

If a check cannot run, say exactly why and what risk remains.

## Definition Of Done

A change is ready when:

1. The requested requirement is fulfilled.
2. Tests were added or updated where useful.
3. Format, lint, type check, and pytest pass, or any skipped check is explained.
4. Related README and docs are updated.
5. Data/privacy rules are respected.
6. No unrelated files are mixed into the change.
7. The final response lists what changed, what checks ran, and what was intentionally deferred.

## Commit Rule

Do not commit unless the user explicitly asks for a commit.

When the user asks for a commit:

1. Check `git status --short`.
2. Stage only files related to the requested work.
3. Use a clear, short commit message.
4. Report the commit hash and mention if anything is left uncommitted.


# OpenFloodAI

OpenFloodAI is an open-source, low-cost, edge-first camera-based river flood detection and warning-support system.

This repository is in its foundation phase. The current scope is project structure, contribution standards, and development tooling. Flood detection logic, machine learning models, APIs, and application business logic are intentionally not implemented yet.

## Goals

- Support affordable river monitoring with edge-first deployment.
- Keep the system auditable, testable, and suitable for public-interest use.
- Prefer minimal dependencies and clear operational boundaries.
- Build toward warning-support workflows, not autonomous emergency decision-making.

## Repository Layout

```text
.github/              GitHub templates and CI workflows
docs/                 Project documentation
  architecture/       Architecture notes and diagrams
  adr/                Architecture Decision Records
  research/           Research notes and references
src/openfloodai/      Python package source
  common/             Shared utilities and types
  edge/               Edge deployment components
  risk_engine/        Risk evaluation components
  vision/             Camera and vision components
tests/                Automated tests
data/                 Local data placeholders; raw datasets are not committed
models/               Local model placeholders; trained models are not committed
scripts/              Development and operational scripts
configs/              Configuration examples and templates
```

## Development

OpenFloodAI targets Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run checks:

```bash
ruff check .
ruff format --check .
mypy src tests
pytest
```

## Project Status

Initial repository foundation only. See `CONTRIBUTING.md` and `SECURITY.md` before proposing functional changes.

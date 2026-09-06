# Contributing to OpenFloodAI

Thank you for helping build OpenFloodAI. This project is intended for flood warning support, so changes should favor clarity, testability, and responsible operational behavior.

## Development Setup

Use Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Checks

Run the full local check suite before opening a pull request:

```bash
ruff check .
ruff format --check .
mypy src tests
pytest
```

## Contribution Guidelines

- Keep dependencies minimal and justified.
- Add tests for behavior changes.
- Avoid committing datasets, trained model binaries, secrets, or local environment files.
- Do not introduce flood detection, ML, API, or application business logic without a focused issue and design discussion.
- Document significant architecture decisions in `docs/adr/`.

## Pull Requests

Pull requests should include:

- A short summary of the change.
- The issue being addressed.
- Tests or checks run locally.
- Any known limitations or follow-up work.

## Contributors

Thank you to all the contributors who have helped build OpenFloodAI:

- [@lamadipen](https://github.com/lamadipen) - Dipen Lama
- [@sande5h](https://github.com/sande5h) - Sandesh Bhusal

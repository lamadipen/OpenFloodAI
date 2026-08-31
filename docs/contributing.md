# How To Contribute

Thank you for helping OpenFloodAI.

This project is about flood warning support, so clear and careful work matters more than fast or flashy work.

## Start Here

1. Read the [V1 Requirements](product/requirements.md).
2. Check the [GitHub repository](https://github.com/lamadipen/OpenFloodAI).
3. Pick a small issue.
4. Keep changes focused.
5. Add tests when behavior changes.

## Local Setup

Use Python 3.12 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

## Run Checks

Before opening a pull request, run:

```bash
ruff check .
ruff format --check .
mypy src tests
pytest
mkdocs build --strict
```

## Contribution Rules

- Do not commit private videos, camera URLs, passwords, GPS coordinates, or personal contact details.
- Do not add public warning behavior without a focused design and review.
- Do not claim real flood detection accuracy without field evidence.
- Keep examples simple and safe.
- Use plain language in docs.

Simple example: a pull request that adds a test helper should explain what it tests and what it does not test.

## Community

- [GitHub repository](https://github.com/lamadipen/OpenFloodAI)
- [Discord discussion](https://discord.gg/2VzpADTZ3)

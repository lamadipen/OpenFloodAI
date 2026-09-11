# Developer Quickstart

This page gets you from a fresh clone to a running local copy of OpenFloodAI.
For the desktop app end users install from a release, see the
[end-user Quickstart](end-user-quickstart.md) instead.

## 1. Clone the repository

```bash
git clone https://github.com/lamadipen/OpenFloodAI.git
cd OpenFloodAI
```

## 2. Set up a virtual environment

OpenFloodAI targets Python 3.12 or newer. On macOS and many Linux systems,
use `python3`. On Windows, `py -3` is often the closest equivalent.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

## 3. Run the checks

Run these before opening a pull request:

```bash
ruff check .
ruff format --check .
mypy src tests
pytest
mkdocs build --strict
```

The Home UI also has a few JavaScript tests. They need Node 20 or newer, and
they use only built-in Node modules, so there is nothing to install:

```bash
node --test "tests/ui/*.cjs"
```

Quote the pattern. `node --test tests/ui/` does not work, because Node only
looks for file names such as `name.test.cjs`, and these files are named
`test_name.cjs` to match the Python tests beside them.

## 4. Run the app locally

```bash
python3 scripts/run_openfloodai_home_ui.py
```

This starts a local server and opens your browser to the Home UI. Site data
is stored under `data/sites/` in your checkout.

## Where to go next

- Follow [Your First End-to-End Review](learning/end-to-end-workflow.md)
  to create a practice site and run your first validation, once the app is
  running.
- Read [How To Contribute](contributing.md) for pull request conventions and
  contribution rules before opening a PR.

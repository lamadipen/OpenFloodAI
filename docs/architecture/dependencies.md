# Dependency Map

This page explains the current dependency footprint and what each part does.

OpenFloodAI is still a local proof-of-concept validation system. A small runtime
dependency set keeps local testing easier to install and helps future edge-device
planning. It does not make the system production-ready.

## Runtime Dependencies

| Dependency | What it does | Why it is here |
| --- | --- | --- |
| Python 3.12+ | Runs the project code | The supported language runtime. |
| `jsonschema` | Checks event and data-contract JSON | Keeps structured records consistent. |
| `numpy` | Handles numeric frame and signal calculations | Supports simple visual measurements. |
| `opencv-python-headless` | Opens local videos and writes/reads frames | Supports video replay without a desktop UI. |

The runtime does not currently include TensorFlow, PyTorch, scikit-learn, a cloud
SDK, a database client, or an alert provider. ML training, cloud services, live
cameras, and alert delivery are future work, not hidden runtime features.

## Development Dependencies

The development installation adds tools for quality and documentation:

| Dependency | What it does |
| --- | --- |
| `pytest` | Runs deterministic unit, component, and replay-style tests. |
| `ruff` | Checks Python lint and formatting. |
| `mypy` | Checks Python types. |
| `mkdocs` | Builds the documentation site. |
| `types-jsonschema` | Provides type information for `jsonschema`. |
| `hatchling` | Builds the Python package. |

Install the project and development tools with:

```bash
python3 -m pip install -e ".[dev]"
```

## Current Runtime Boundary

The current dependency map supports:

```text
local video -> frame metadata -> simple visual signals -> local records -> human review
```

It does not provide:

- production flood detection;
- a trained ML model;
- live camera or RTSP deployment;
- cloud upload or storage;
- public warning delivery;
- emergency decision-making.

## Why This Matters

A small dependency footprint is useful for local validation and future edge
experiments, but dependency size is only one engineering concern. A future edge
system still needs device benchmarking, failure testing, privacy controls,
monitoring, update/rollback support, and field evidence before deployment claims.

See [Project Overview](../project-overview.md), [Validation Results And Known Limits](../research/validation-results.md), and the [V1 Requirements](../product/requirements.md) for current boundaries.

# Overview

<a href="classic/" class="md-button">Switch to Classic Docs</a>

OpenFloodAI is an open-source project for low-cost river flood detection support.
Use a fixed camera near a river, run checks close to the camera, and create clear
records when something may need human review.

OpenFloodAI is **not** a finished public warning system. Early code must not send
public warnings or make emergency decisions by itself. Current output means
"please review this evidence," not "there is a confirmed flood."

## What's here

<div class="grid cards" markdown>

-   **Product**

    ---

    Requirements, quality checklists, and the ML readiness plan that decide
    what gets built next.

    [Go to Product](product/index.md)

-   **Architecture**

    ---

    How the pieces fit together: data contracts, reason codes, windowed
    video evidence, and validation input snapshots.

    [Go to Architecture](architecture/README.md)

-   **Validation & Research**

    ---

    Labeling guides, human-label comparisons, threshold tuning, and known
    validation limits.

    [Go to Validation & Research](research/README.md)

-   **Learning**

    ---

    Guided walkthroughs of a full end-to-end review and the core pipeline
    basics.

    [Go to Learning](learning/index.md)

-   **Packaging & Release**

    ---

    How the desktop app is built and released for Windows and macOS.

    [Go to Packaging & Release](packaging.md)

-   **Decisions**

    ---

    Architecture Decision Records — significant technical choices and why
    they were made.

    [Go to Decisions](adr/README.md)

</div>

## Current status

OpenFloodAI has a usable local validation MVP. The project is still a proof of
concept, but contributors can prepare labelled examples, run validation, inspect
scorecards and evidence, and compare recent local reports without cloud services.

OpenFloodAI still does not detect real floods, train ML models, send alerts,
publish warnings, run live camera deployments, or replace local emergency
decision-making. The Home UI is a local validation and review tool, not a
production monitoring or fleet dashboard.

The current runtime uses Python, `jsonschema`, `numpy`, and OpenCV. Development
checks use pytest, Ruff, mypy, and MkDocs. See the [dependency map](architecture/dependencies.md).

## Follow the project

- [GitHub repository](https://github.com/lamadipen/OpenFloodAI)
- [Discord discussion](https://discord.gg/2VzpADTZ3)

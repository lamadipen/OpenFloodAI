"""Run the safe local OpenFloodAI POC smoke workflow."""

from __future__ import annotations

from pathlib import Path

from openfloodai.pipeline import run_local_poc_smoke


def main() -> None:
    """Create synthetic local smoke-test outputs under the example site folder."""

    result = run_local_poc_smoke(Path("data/sites/example-site/outputs/smoke-test"))

    print("Local POC smoke workflow completed.")
    print(f"Records: {result.records_path}")
    print(f"Summary: {result.summary_path}")
    print(f"Operator notes: {result.operator_notes_path}")
    print("Review images:")
    for path in result.review_image_paths:
        print(f"- {path}")


if __name__ == "__main__":
    main()

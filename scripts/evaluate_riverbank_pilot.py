"""Evaluate saved riverbank-crossing evidence against human pilot reviews."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from openfloodai.review import (
    evaluate_riverbank_pilot_files,
    render_riverbank_pilot_report,
)


def main() -> None:
    """Write local Markdown and JSON pilot-evaluation reports."""

    parser = argparse.ArgumentParser(
        description="Compare riverbank-crossing evidence with human-reviewed pilot observations."
    )
    parser.add_argument("--evidence-path", required=True, type=Path)
    parser.add_argument("--reviews-path", required=True, type=Path)
    parser.add_argument("--output-path", required=True, type=Path)
    parser.add_argument("--json-output-path", type=Path)
    args = parser.parse_args()

    report = evaluate_riverbank_pilot_files(
        evidence_path=args.evidence_path,
        reviewed_observations_path=args.reviews_path,
    )
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(render_riverbank_pilot_report(report), encoding="utf-8")
    print(f"Pilot evaluation written to: {args.output_path}")

    if args.json_output_path is not None:
        args.json_output_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_output_path.write_text(
            json.dumps(asdict(report), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Machine-readable pilot evaluation written to: {args.json_output_path}")


if __name__ == "__main__":
    main()

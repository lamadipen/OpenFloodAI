"""Run the one-camera water-change feasibility pilot from the command line (Issue #222).

Order (see docs/learning/water-change-measurement.md):

    inventory      list the human-accepted water masks per camera (read-only)
    blind-sheet    images only, for people to judge BEFORE seeing machine results or the gauge
    judgments      export a reviewer's blind labels from the focused review page as a judgments file
    measure        measure the pairs under the written criteria (held-out pairs are skipped
                   unless --include-held-out)
    sheet          contact sheet with masks, spatial overlay, numbers and frozen gauge context
    report         errors AND unavailable counts, checks written before the run, limitations
    decision       a named person records proceed / revise / stop

Nothing here uploads anything, starts segmentation, trains a model or sends an alert.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openfloodai.curation.common import CurationError
from openfloodai.water_change.pilot import (
    DECISIONS,
    build_report,
    record_decision,
    run_measurements,
)
from openfloodai.water_change.pilot_judgments import export_reviewer_judgments
from openfloodai.water_change.pilot_sheets import (
    inventory_accepted_masks,
    render_blind_sheet,
    render_measured_sheet,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--sites-dir", type=Path, default=Path("data/sites"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory", help="List accepted water masks per camera and watched area.")
    for name in ("blind-sheet", "judgments", "measure", "sheet", "report", "decision"):
        step = sub.add_parser(name)
        step.add_argument("--pilot-dir", type=Path, required=True)
        if name == "judgments":
            step.add_argument(
                "--reviewer", required=True, help="the reviewer code used when labelling"
            )
        if name == "measure":
            step.add_argument("--include-held-out", action="store_true")
        if name == "report":
            step.add_argument("--evaluate-held-out", action="store_true")
        if name == "decision":
            step.add_argument("--decision", choices=DECISIONS, required=True)
            step.add_argument("--decided-by", required=True)
            step.add_argument("--rationale", required=True)
            step.add_argument("--limitations", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inventory":
            print(json.dumps(inventory_accepted_masks(args.sites_dir), indent=2))
        elif args.command == "blind-sheet":
            print(render_blind_sheet(args.pilot_dir, args.sites_dir))
        elif args.command == "judgments":
            result = export_reviewer_judgments(args.pilot_dir, args.sites_dir, args.reviewer)
            print(
                f"Wrote {result['path']}: {len(result['exported_pairs'])} pair(s), "
                f"{len(result['not_labelled_by_reviewer'])} not labelled by {result['reviewer']}."
            )
            if result["warning"]:
                print(f"warning: {result['warning']}")
        elif args.command == "measure":
            result = run_measurements(
                args.pilot_dir, args.sites_dir, include_held_out=args.include_held_out
            )
            available = sum(1 for r in result["results"] if r["evidence"]["status"] == "available")
            print(f"Measured {len(result['results'])} pairs; {available} available.")
        elif args.command == "sheet":
            files = sorted((args.pilot_dir / "measurements").glob("*.json"))
            if not files:
                raise CurationError("No measurements yet. Run 'measure' first.")
            latest = json.loads(files[-1].read_text(encoding="utf-8"))
            print(render_measured_sheet(args.pilot_dir, args.sites_dir, latest))
        elif args.command == "report":
            report = build_report(args.pilot_dir, evaluate_held_out=args.evaluate_held_out)
            print(f"Mechanical status: {report['mechanical_status']} (see report.md)")
        else:
            record_decision(
                args.pilot_dir,
                args.decision,
                args.decided_by,
                args.rationale,
                args.limitations,
            )
            print("Decision recorded.")
    except (CurationError, OSError, FileExistsError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

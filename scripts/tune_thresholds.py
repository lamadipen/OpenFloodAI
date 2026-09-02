"""Try prototype visual-change thresholds against human labels."""

from __future__ import annotations

import argparse
from pathlib import Path

from openfloodai.review import (
    DEFAULT_CANDIDATE_THRESHOLDS,
    render_threshold_tuning_report,
    tune_threshold_files,
)


def main() -> None:
    """Run local prototype threshold tuning."""

    parser = argparse.ArgumentParser(
        description="Try visual-change thresholds against human label comparison."
    )
    parser.add_argument("--records-path", required=True, type=Path)
    parser.add_argument("--labels-path", required=True, type=Path)
    parser.add_argument("--video-id", required=True)
    parser.add_argument(
        "--threshold",
        dest="thresholds",
        action="append",
        type=float,
        help="Candidate threshold to try. May be repeated.",
    )
    parser.add_argument("--output-path", type=Path)
    args = parser.parse_args()

    report = tune_threshold_files(
        system_records_path=args.records_path,
        human_labels_path=args.labels_path,
        video_id=args.video_id,
        candidate_thresholds=args.thresholds
        if args.thresholds is not None
        else DEFAULT_CANDIDATE_THRESHOLDS,
    )
    rendered_report = render_threshold_tuning_report(report)

    if args.output_path is None:
        print(rendered_report)
        return

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(rendered_report, encoding="utf-8")
    print(f"Threshold tuning report written to: {args.output_path}")


if __name__ == "__main__":
    main()

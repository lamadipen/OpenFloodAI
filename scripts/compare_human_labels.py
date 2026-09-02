"""Compare local OpenFloodAI output records against human labels."""

from __future__ import annotations

import argparse
from pathlib import Path

from openfloodai.review import compare_label_files, render_label_comparison_report


def main() -> None:
    """Run a local label comparison report."""

    parser = argparse.ArgumentParser(
        description="Compare local POC records against human review labels."
    )
    parser.add_argument("--records-path", required=True, type=Path)
    parser.add_argument("--labels-path", required=True, type=Path)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output-path", type=Path)
    args = parser.parse_args()

    report = compare_label_files(
        system_records_path=args.records_path,
        human_labels_path=args.labels_path,
        video_id=args.video_id,
    )
    rendered_report = render_label_comparison_report(report)

    if args.output_path is None:
        print(rendered_report)
        return

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(rendered_report, encoding="utf-8")
    print(f"Comparison report written to: {args.output_path}")


if __name__ == "__main__":
    main()

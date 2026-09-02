"""Run local review outputs for a real local video file."""

from __future__ import annotations

import argparse
from pathlib import Path

from openfloodai.pipeline import run_local_video_review


def main() -> None:
    """Run the local POC review workflow from command-line paths."""

    parser = argparse.ArgumentParser(
        description="Create local OpenFloodAI POC review outputs from a local video."
    )
    parser.add_argument("--video-path", required=True, type=Path)
    parser.add_argument("--config-path", default=Path("configs/example-site.json"), type=Path)
    parser.add_argument(
        "--output-dir",
        default=Path("data/sites/example-site/outputs"),
        type=Path,
    )
    args = parser.parse_args()

    result = run_local_video_review(
        video_path=args.video_path,
        config_path=args.config_path,
        output_dir=args.output_dir,
    )

    print("Local video review workflow completed.")
    print(f"Records: {result.records_path}")
    print(f"Summary: {result.summary_path}")
    print(f"Operator notes: {result.operator_notes_path}")
    print("Review images:")
    for path in result.review_image_paths:
        print(f"- {path}")


if __name__ == "__main__":
    main()

"""Run local validation for all videos in one site folder."""

from __future__ import annotations

import argparse
from pathlib import Path

from openfloodai.ingestion.evidence_sampling import SamplingSettings
from openfloodai.validation import render_site_validation_report, run_site_validation


def main() -> None:
    """Run a local multi-video validation report."""

    parser = argparse.ArgumentParser(
        description="Run OpenFloodAI local validation for one site folder."
    )
    parser.add_argument("--site-dir", required=True, type=Path)
    parser.add_argument("--config-path", type=Path)
    parser.add_argument("--sample-interval-seconds", type=float, default=5.0)
    parser.add_argument("--max-samples", type=int, default=120)
    parser.add_argument("--minimum-brightness", type=float, default=5.0)
    args = parser.parse_args()
    sampling = SamplingSettings(
        interval_seconds=args.sample_interval_seconds,
        max_samples=args.max_samples,
        minimum_brightness=args.minimum_brightness,
    )

    report = run_site_validation(args.site_dir, config_path=args.config_path, sampling=sampling)

    print(render_site_validation_report(report))
    print(f"Combined report written to: {report.output_path}")


if __name__ == "__main__":
    main()

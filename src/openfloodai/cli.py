"""Command-line interface for OpenFloodAI.

Provides the ``openfloodai`` command with subcommands for monitoring,
checking data sources, and validating site configurations.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from openfloodai.common import SiteConfig, load_site_config


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``openfloodai`` CLI."""

    parser = argparse.ArgumentParser(
        prog="openfloodai",
        description="Edge-first camera-based river flood detection and warning system.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command")

    _add_monitor_parser(subparsers)
    _add_check_sources_parser(subparsers)
    _add_validate_config_parser(subparsers)
    _add_validate_video_parser(subparsers)
    _add_sites_parser(subparsers)

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.command is None:
        parser.print_help()
        return 0

    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger("openfloodai").error("%s", exc)
        return 1


def _add_monitor_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser(
        "monitor",
        help="Start continuous monitoring for a site",
    )
    p.add_argument("--config", required=True, help="Path to site config JSON")
    p.add_argument("--site", required=True, help="Site ID to monitor")
    p.add_argument("--stream", required=True, help="Camera stream URL (RTSP/MJPEG/file)")
    p.add_argument("--webhook", action="append", default=[], help="Webhook URL for alerts")
    p.add_argument("--fps", type=float, default=1.0, help="Target frames per second")
    p.add_argument("--window", type=int, default=10, help="Temporal window in minutes")


def _add_check_sources_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "check-sources",
        help="Check external data sources for a site",
    )
    p.add_argument("--config", required=True, help="Path to site config JSON")
    p.add_argument("--site", required=True, help="Site ID to check")


def _add_validate_config_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "validate-config",
        help="Validate a site configuration file",
    )
    p.add_argument("config", help="Path to site config JSON")


def _add_validate_video_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "validate-video",
        help="Run detection pipeline on a recorded video file and produce a report",
    )
    p.add_argument("--config", required=True, help="Path to site config JSON")
    p.add_argument("--site", required=True, help="Site ID from config")
    p.add_argument("--video", required=True, help="Path to video file")
    p.add_argument("--fps", type=float, default=1.0, help="Frames per second to sample")
    p.add_argument(
        "--output",
        help="Path to write JSON report (default: stdout)",
    )
    p.add_argument(
        "--max-frames",
        type=int,
        default=300,
        help="Maximum frames to process (default: 300)",
    )


def _add_sites_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser(
        "sites",
        help="List sites from a configuration file",
    )
    p.add_argument("config", help="Path to site config JSON")


def _dispatch(args: argparse.Namespace) -> int:
    command: str = args.command
    if command == "monitor":
        return _cmd_monitor(args)
    if command == "check-sources":
        return _cmd_check_sources(args)
    if command == "validate-config":
        return _cmd_validate_config(args)
    if command == "validate-video":
        return _cmd_validate_video(args)
    if command == "sites":
        return _cmd_sites(args)
    return 1


def _cmd_monitor(args: argparse.Namespace) -> int:
    from openfloodai.common import find_site
    from openfloodai.edge.monitor import (
        build_monitor_config,
        create_monitor,
        run_monitor,
    )

    sites = load_site_config(Path(args.config))
    site = find_site(sites, args.site)
    if site is None:
        print(f"Site '{args.site}' not found in config", file=sys.stderr)
        return 1

    config = build_monitor_config(
        site,
        args.stream,
        webhook_urls=args.webhook,
        target_fps=args.fps,
        window_minutes=args.window,
    )
    state = create_monitor(config)
    run_monitor(config, state)
    return 0


def _cmd_check_sources(args: argparse.Namespace) -> int:
    from openfloodai.common import find_site

    sites = load_site_config(Path(args.config))
    site = find_site(sites, args.site)
    if site is None:
        print(f"Site '{args.site}' not found in config", file=sys.stderr)
        return 1

    results: dict[str, object] = {"site_id": site.site_id}
    print(f"Checking data sources for {site.site_id}...")
    print(f"  Location: {site.latitude}, {site.longitude}")

    _check_earthquake_source(site, results)
    _check_eonet_source(site, results)
    _check_reliefweb_source(results)
    _check_precipitation_source(site, results)

    if site.usgs_site_number:
        _check_usgs_source(site, results)

    _check_dhm_source(results)

    print(json.dumps(results, indent=2, default=str))
    return 0


def _check_earthquake_source(site: SiteConfig, results: dict[str, object]) -> None:
    if site.latitude is None or site.longitude is None:
        print("  Earthquakes: skipped (no coordinates)")
        return
    try:
        from openfloodai.data_sources.usgs_earthquake import (
            assess_seismic_flood_risk,
            fetch_nearby_earthquakes,
        )

        quakes = fetch_nearby_earthquakes(site.latitude, site.longitude)
        risk = assess_seismic_flood_risk(quakes)
        results["earthquake"] = risk
        count = risk["earthquake_count"]
        state = risk["seismic_risk_state"]
        print(f"  Earthquakes: {count} nearby, state={state}")
    except Exception as exc:
        results["earthquake_error"] = str(exc)
        print(f"  Earthquakes: error - {exc}")


def _check_eonet_source(site: SiteConfig, results: dict[str, object]) -> None:
    if site.latitude is None or site.longitude is None:
        print("  EONET events: skipped (no coordinates)")
        return
    try:
        from openfloodai.data_sources.nasa_eonet import (
            fetch_events_near,
            summarize_events,
        )

        events = fetch_events_near(site.latitude, site.longitude)
        summary = summarize_events(events)
        results["eonet"] = summary
        print(f"  EONET events: {summary['event_count']} nearby, state={summary['event_state']}")
    except Exception as exc:
        results["eonet_error"] = str(exc)
        print(f"  EONET events: error - {exc}")


def _check_reliefweb_source(results: dict[str, object]) -> None:
    try:
        from openfloodai.data_sources.reliefweb import (
            fetch_flood_reports,
            summarize_reports,
        )

        reports = fetch_flood_reports(country="Nepal")
        summary = summarize_reports(reports)
        results["reliefweb"] = summary
        print(f"  ReliefWeb: {summary['report_count']} reports, state={summary['report_state']}")
    except Exception as exc:
        results["reliefweb_error"] = str(exc)
        print(f"  ReliefWeb: error - {exc}")


def _check_precipitation_source(site: SiteConfig, results: dict[str, object]) -> None:
    if site.latitude is None or site.longitude is None:
        print("  Precipitation: skipped (no coordinates)")
        return
    try:
        from openfloodai.data_sources.open_meteo import fetch_precipitation

        precip = fetch_precipitation(site.latitude, site.longitude)
        results["precipitation"] = precip
        total = precip.get("precipitation_sum_mm")
        print(f"  Precipitation: {total}mm forecast")
    except Exception as exc:
        results["precipitation_error"] = str(exc)
        print(f"  Precipitation: error - {exc}")


def _check_usgs_source(site: SiteConfig, results: dict[str, object]) -> None:
    try:
        from openfloodai.data_sources.usgs_water import fetch_site_conditions

        assert site.usgs_site_number is not None
        conditions = fetch_site_conditions(site.usgs_site_number)
        results["usgs_water"] = conditions
        height = conditions.get("gage_height_ft")
        print(f"  USGS water: gage height {height} ft")
    except Exception as exc:
        results["usgs_water_error"] = str(exc)
        print(f"  USGS water: error - {exc}")


def _check_dhm_source(results: dict[str, object]) -> None:
    try:
        from openfloodai.data_sources.dhm_nepal import (
            assess_dhm_flood_risk,
            fetch_flood_bulletin,
        )

        stations = fetch_flood_bulletin()
        risk = assess_dhm_flood_risk(stations)
        results["dhm_nepal"] = risk
        state = risk["dhm_risk_state"]
        total = risk["stations_total"]
        danger = risk["stations_danger"]
        warning = risk["stations_warning"]
        print(f"  DHM Nepal: {total} stations, {danger} danger, {warning} warning, state={state}")
    except Exception as exc:
        results["dhm_nepal_error"] = str(exc)
        print(f"  DHM Nepal: error - {exc}")


def _cmd_validate_video(args: argparse.Namespace) -> int:
    import cv2

    from openfloodai.common import find_site
    from openfloodai.edge.monitor import (
        build_monitor_config,
        create_monitor,
        process_frame,
    )

    sites = load_site_config(Path(args.config))
    site = find_site(sites, args.site)
    if site is None:
        print(f"Site '{args.site}' not found in config", file=sys.stderr)
        return 1

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Video file not found: {video_path}", file=sys.stderr)
        return 1

    config = build_monitor_config(site, str(video_path), target_fps=args.fps)
    state = create_monitor(config)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"Cannot open video: {video_path}", file=sys.stderr)
        return 1

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_interval = max(1, int(video_fps / args.fps))
    max_frames: int = args.max_frames

    results: list[dict[str, object]] = []
    frame_idx = 0
    processed = 0

    print(f"Processing {video_path.name} for site {site.site_id}...")
    print(f"  Video FPS: {video_fps:.1f}, sampling every {frame_interval} frames")

    import numpy as np

    while processed < max_frames:
        ok, raw_frame = cap.read()
        if not ok:
            break

        if frame_idx % frame_interval == 0:
            frame = np.asarray(raw_frame)
            result = process_frame(frame, config, state)
            results.append(result)
            processed += 1

            if processed % 50 == 0:
                print(f"  Processed {processed} frames...")

        frame_idx += 1

    cap.release()

    risk_counts: dict[str, int] = {}
    for r in results:
        rs = str(r.get("instant_risk_state", "UNKNOWN"))
        risk_counts[rs] = risk_counts.get(rs, 0) + 1

    report: dict[str, object] = {
        "site_id": site.site_id,
        "video_file": str(video_path),
        "total_video_frames": frame_idx,
        "frames_processed": processed,
        "sample_fps": args.fps,
        "risk_state_distribution": risk_counts,
        "final_temporal_state": state.current_risk_state,
        "frame_results": results,
    }

    output_json = json.dumps(report, indent=2, default=str)

    if args.output:
        Path(args.output).write_text(output_json + "\n", encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(output_json)

    print(f"\nSummary: {processed} frames, final state: {state.current_risk_state}")
    for rs, count in sorted(risk_counts.items()):
        pct = count / processed * 100 if processed > 0 else 0
        print(f"  {rs}: {count} ({pct:.1f}%)")

    return 0


def _cmd_validate_config(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    try:
        sites = load_site_config(config_path)
    except Exception as exc:
        print(f"Invalid config: {exc}", file=sys.stderr)
        return 1

    print(f"Valid configuration: {len(sites)} site(s)")
    for site in sites:
        print(f"  {site.site_id}: ({site.latitude}, {site.longitude})")
    return 0


def _cmd_sites(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    sites = load_site_config(config_path)

    for site in sites:
        desc = site.description or "No description"
        print(f"{site.site_id}")
        print(f"  Camera: {site.camera_id}")
        print(f"  Location: ({site.latitude}, {site.longitude})")
        print(f"  Description: {desc}")
        if site.usgs_site_number:
            print(f"  USGS Site: {site.usgs_site_number}")
        if site.nws_zone:
            print(f"  NWS Zone: {site.nws_zone}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

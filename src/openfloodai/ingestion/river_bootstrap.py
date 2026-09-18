"""Orchestrate a registry-driven camera bootstrap run for issue #152.

Ties together the river camera registry, the USGS image-sequence pipeline,
safe site creation, and gage-data enrichment behind two entry points:
`preview_bootstrap_run` (read-only diagnostics) and `run_bootstrap`
(creates/reuses sites and downloads). Both operate per-camera and never let
one camera's failure stop the rest of the batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openfloodai.config.site_config import SiteConfigError, load_site_config
from openfloodai.contracts import read_jsonl_records
from openfloodai.ingestion.river_images import (
    DEFAULT_DAYLIGHT_WINDOW_END_HOUR,
    DEFAULT_DAYLIGHT_WINDOW_START_HOUR,
    RiverImageError,
    download_river_image_sequence,
    list_archive_images_between_windowed,
    parse_sequence_date_range,
    sample_image_sequence_candidates,
)
from openfloodai.ingestion.river_registry import CameraRecord, RiverRegistry, load_river_registry
from openfloodai.ingestion.river_site_bootstrap import bootstrap_camera_site
from openfloodai.ingestion.usgs_gage_data import GageDataError, write_gauge_readings_summary


def select_cameras(registry: RiverRegistry, camera_ids: list[str]) -> tuple[CameraRecord, ...]:
    """Return the requested cameras from the registry, or all of them if none named."""

    if not camera_ids:
        return registry.cameras
    selected: list[CameraRecord] = []
    unknown: list[str] = []
    for camera_id in camera_ids:
        camera = registry.camera(camera_id)
        if camera is None:
            unknown.append(camera_id)
        else:
            selected.append(camera)
    if unknown:
        available = ", ".join(camera.camera_id for camera in registry.cameras)
        raise ValueError(
            f"Unknown camera id(s) for river '{registry.river_id}': {', '.join(unknown)}. "
            f"Available cameras: {available}."
        )
    return tuple(selected)


@dataclass(frozen=True)
class CameraPreview:
    """Read-only diagnostics for one camera, before any download happens."""

    camera_id: str
    folder_name: str
    display_name: str
    timezone: str
    days_requested: int
    candidate_count: int
    daylight_images_available: int
    missing_day_count: int
    estimated_bytes: int
    earliest_captured_utc: str | None
    latest_captured_utc: str | None
    gage_relationship: str
    gage_relationship_note: str | None
    site_status: str
    site_message: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class BootstrapPreview:
    """A no-download preview across every selected camera for one river/run."""

    river_id: str
    start_date: str
    end_date: str
    sampling_mode: str
    excluded_cameras_note: str
    cameras: list[CameraPreview] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "river_id": self.river_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "sampling_mode": self.sampling_mode,
            "excluded_cameras_note": self.excluded_cameras_note,
            "cameras": [camera.to_dict() for camera in self.cameras],
        }


def preview_bootstrap_run(
    *,
    reference_dir: Path,
    sites_base_dir: Path,
    river_id: str,
    camera_ids: list[str],
    start_date: str,
    end_date: str,
    sampling_mode: str,
    daylight_window_start_hour: int = DEFAULT_DAYLIGHT_WINDOW_START_HOUR,
    daylight_window_end_hour: int = DEFAULT_DAYLIGHT_WINDOW_END_HOUR,
) -> BootstrapPreview:
    """Report what a bootstrap run would do, without downloading anything."""

    registry = load_river_registry(river_id, reference_dir)
    cameras = select_cameras(registry, camera_ids)

    previews: list[CameraPreview] = []
    for camera in cameras:
        previews.append(
            _preview_one_camera(
                camera,
                sites_base_dir=sites_base_dir,
                start_date=start_date,
                end_date=end_date,
                sampling_mode=sampling_mode,
                daylight_window_start_hour=daylight_window_start_hour,
                daylight_window_end_hour=daylight_window_end_hour,
            )
        )

    return BootstrapPreview(
        river_id=registry.river_id,
        start_date=start_date,
        end_date=end_date,
        sampling_mode=sampling_mode,
        excluded_cameras_note=registry.notes,
        cameras=previews,
    )


def _preview_one_camera(
    camera: CameraRecord,
    *,
    sites_base_dir: Path,
    start_date: str,
    end_date: str,
    sampling_mode: str,
    daylight_window_start_hour: int,
    daylight_window_end_hour: int,
) -> CameraPreview:
    site_status, site_message = _peek_site_conflict(sites_base_dir, camera)

    try:
        start_utc, end_utc = parse_sequence_date_range(start_date, end_date, camera.timezone)
        candidates = list_archive_images_between_windowed(camera.camera_id, start_utc, end_utc)
        sampled = sample_image_sequence_candidates(
            candidates,
            sampling_mode,
            timezone_name=camera.timezone,
            daylight_window_start_hour=daylight_window_start_hour,
            daylight_window_end_hour=daylight_window_end_hour,
        )
        days_requested = (end_utc.date() - start_utc.date()).days
        missing_day_count = max(days_requested - len(sampled), 0)
        return CameraPreview(
            camera_id=camera.camera_id,
            folder_name=camera.folder_name,
            display_name=camera.display_name,
            timezone=camera.timezone,
            days_requested=days_requested,
            candidate_count=len(candidates),
            daylight_images_available=len(sampled),
            missing_day_count=missing_day_count,
            estimated_bytes=sum(item.size_bytes for item in sampled),
            earliest_captured_utc=sampled[0].captured_utc.isoformat() if sampled else None,
            latest_captured_utc=sampled[-1].captured_utc.isoformat() if sampled else None,
            gage_relationship=camera.gage_relationship,
            gage_relationship_note=camera.gage_relationship_note,
            site_status=site_status,
            site_message=site_message,
        )
    except RiverImageError as error:
        return CameraPreview(
            camera_id=camera.camera_id,
            folder_name=camera.folder_name,
            display_name=camera.display_name,
            timezone=camera.timezone,
            days_requested=0,
            candidate_count=0,
            daylight_images_available=0,
            missing_day_count=0,
            estimated_bytes=0,
            earliest_captured_utc=None,
            latest_captured_utc=None,
            gage_relationship=camera.gage_relationship,
            gage_relationship_note=camera.gage_relationship_note,
            site_status=site_status,
            site_message=site_message,
            error=str(error),
        )


def _peek_site_conflict(sites_base_dir: Path, camera: CameraRecord) -> tuple[str, str]:
    """Read-only lookahead: would this camera create, reuse, or conflict with a site?

    Mirrors `bootstrap_camera_site`'s decision without creating anything, so
    preview mode never writes to disk.
    """

    site_dir = (sites_base_dir / camera.folder_name).resolve()
    if not site_dir.exists():
        return "would_create", f"No site exists yet at {site_dir}."
    config_path = site_dir / "configs" / f"{camera.folder_name}.json"
    if not config_path.is_file():
        return "conflict", f"Site folder exists but its config is missing: {config_path}."
    try:
        existing = load_site_config(config_path)
    except SiteConfigError as error:
        return "conflict", f"Could not read the existing site config: {error}"
    if existing.camera_id != camera.camera_id:
        return (
            "conflict",
            f"Site folder '{camera.folder_name}' already has a different camera_id "
            f"({existing.camera_id!r}, not {camera.camera_id!r}).",
        )
    return "would_reuse", f"Would reuse the existing site at {site_dir}."


@dataclass(frozen=True)
class CameraBootstrapOutcome:
    """What happened for one camera during a real (non-preview) bootstrap run."""

    camera_id: str
    folder_name: str
    site_status: str
    site_message: str
    downloaded_count: int = 0
    missing_count: int = 0
    failed_count: int = 0
    sequence_id: str | None = None
    gage_available: bool | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def run_bootstrap(
    *,
    reference_dir: Path,
    sites_base_dir: Path,
    river_id: str,
    camera_ids: list[str],
    start_date: str,
    end_date: str,
    sampling_mode: str,
    replace_sequence: bool = False,
    resume: bool = True,
    daylight_window_start_hour: int = DEFAULT_DAYLIGHT_WINDOW_START_HOUR,
    daylight_window_end_hour: int = DEFAULT_DAYLIGHT_WINDOW_END_HOUR,
) -> list[CameraBootstrapOutcome]:
    """Create/reuse sites and download image sequences for each selected camera.

    One camera's conflict or failure never stops the rest of the batch, and
    gage-data enrichment failure never cancels image collection (matching
    the plan's explicit requirements).
    """

    registry = load_river_registry(river_id, reference_dir)
    cameras = select_cameras(registry, camera_ids)

    outcomes: list[CameraBootstrapOutcome] = []
    for camera in cameras:
        site_result = bootstrap_camera_site(
            sites_base_dir=sites_base_dir,
            folder_name=camera.folder_name,
            camera_id=camera.camera_id,
            site_name=camera.display_name,
            public_location=camera.display_name,
        )
        if site_result.status == "conflict":
            outcomes.append(
                CameraBootstrapOutcome(
                    camera_id=camera.camera_id,
                    folder_name=camera.folder_name,
                    site_status=site_result.status,
                    site_message=site_result.message,
                )
            )
            continue

        try:
            download = download_river_image_sequence(
                camera_url=(f"https://apps.usgs.gov/hivis/camera/{camera.camera_id}"),
                start_date=start_date,
                end_date=end_date,
                timezone_name=camera.timezone,
                sampling_mode=sampling_mode,
                site_id=f"{camera.folder_name}_sid",
                site_dir=site_result.site_dir,
                overwrite=replace_sequence,
                resume=resume,
                daylight_window_start_hour=daylight_window_start_hour,
                daylight_window_end_hour=daylight_window_end_hour,
            )
        except RiverImageError as error:
            outcomes.append(
                CameraBootstrapOutcome(
                    camera_id=camera.camera_id,
                    folder_name=camera.folder_name,
                    site_status=site_result.status,
                    site_message=site_result.message,
                    error=str(error),
                )
            )
            continue

        summary = download.to_dict()
        gage_available = _write_gage_summary(download.directory, camera, start_date, end_date)

        outcomes.append(
            CameraBootstrapOutcome(
                camera_id=camera.camera_id,
                folder_name=camera.folder_name,
                site_status=site_result.status,
                site_message=site_result.message,
                downloaded_count=summary["downloaded_count"],
                missing_count=summary["missing_count"],
                failed_count=summary["failed_count"],
                sequence_id=download.sequence_id,
                gage_available=gage_available,
            )
        )
    return outcomes


def _write_gage_summary(
    sequence_dir: Path, camera: CameraRecord, start_date: str, end_date: str
) -> bool | None:
    """Enrich a sequence with gage data. Never raises: failure must not cancel image collection."""

    try:
        manifest_records = read_jsonl_records(sequence_dir / "sequence-manifest.jsonl")
    except ValueError:
        return None
    try:
        summary = write_gauge_readings_summary(
            sequence_dir,
            nwis_site_id=camera.nwis_id,
            start_date=start_date,
            end_date=end_date,
            gage_relationship=camera.gage_relationship,
            gage_relationship_note=camera.gage_relationship_note,
            manifest_records=manifest_records,
        )
        return summary.available
    except GageDataError:
        return None

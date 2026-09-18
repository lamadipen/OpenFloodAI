"""Build a per-site tracker view for a river's pilot cameras (issue #152).

Groups sites using the river registry file, not by parsing folder names,
and reuses existing per-site primitives (site config, image-sequence
summaries, dataset-group assignments, validation-site status) rather than
a new aggregate data store. One row per registry camera; a camera with no
site yet still gets a row, so a missing site is visible, not silently
skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openfloodai.config.site_config import SiteConfigError, load_site_config
from openfloodai.ingestion.river_images import list_site_image_sequences
from openfloodai.ingestion.river_registry import CameraRecord, RiverRegistry, load_river_registry
from openfloodai.review.dataset_groups import DEFAULT_DATASET_GROUP, list_dataset_group_assignments
from openfloodai.review.sample_quality import is_normal_baseline_confirmed
from openfloodai.validation.image_sequence_runner import list_image_sequence_runs
from openfloodai.validation.site_status import read_validation_site_status

_DEFAULT_REFERENCE_REGION = {"x": 0, "y": 50, "width": 100, "height": 50}


@dataclass(frozen=True)
class TrackerRow:
    """One tracker row: a registry camera, and what local progress exists for it."""

    river_id: str
    river_display_name: str
    camera_id: str
    display_name: str
    folder_name: str
    camera_availability: str
    requested_date_range: str | None
    daylight_images_downloaded: int
    missing_days: int
    gage_data_status: str
    watched_area_status: str
    riverbank_guide_status: str
    baseline_selected: bool
    validation_run_count: int
    dataset_group: str
    human_review_progress: str
    known_problems: list[str]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def build_river_tracker(
    river_id: str, *, reference_dir: Path, sites_base_dir: Path
) -> tuple[RiverRegistry, list[TrackerRow]]:
    """Return the river registry and one tracker row per camera it lists."""

    registry = load_river_registry(river_id, reference_dir)
    rows = [_build_row(camera, registry, sites_base_dir) for camera in registry.cameras]
    return registry, rows


def _build_row(camera: CameraRecord, registry: RiverRegistry, sites_base_dir: Path) -> TrackerRow:
    site_dir = (sites_base_dir / camera.folder_name).resolve()
    if not site_dir.is_dir():
        return TrackerRow(
            river_id=registry.river_id,
            river_display_name=registry.display_name,
            camera_id=camera.camera_id,
            display_name=camera.display_name,
            folder_name=camera.folder_name,
            camera_availability="not_created",
            requested_date_range=None,
            daylight_images_downloaded=0,
            missing_days=0,
            gage_data_status="not_run",
            watched_area_status="not_drawn",
            riverbank_guide_status="not_drawn",
            baseline_selected=False,
            validation_run_count=0,
            dataset_group=DEFAULT_DATASET_GROUP,
            human_review_progress="not_started",
            known_problems=[],
        )

    known_problems: list[str] = []

    watched_area_status, riverbank_guide_status, baseline_selected = _read_config_progress(
        site_dir, camera.folder_name, known_problems
    )

    sequences = list_site_image_sequences(site_dir)
    matching = [s for s in sequences if s.get("camera_url", "").endswith(f"/{camera.camera_id}")]
    latest = matching[-1] if matching else (sequences[-1] if sequences else None)

    requested_date_range = None
    daylight_images_downloaded = 0
    missing_days = 0
    gage_data_status = "not_run"
    camera_availability = "created_no_downloads_yet"
    if latest is not None:
        camera_availability = "downloaded"
        start = latest.get("requested_start_date")
        end = latest.get("requested_end_date")
        if start and end:
            requested_date_range = f"{start} to {end}"
        daylight_images_downloaded = int(latest.get("downloaded_count") or 0)
        missing_days = int(latest.get("missing_count") or 0)
        failed_count = int(latest.get("failed_count") or 0)
        if failed_count:
            known_problems.append(f"{failed_count} image(s) failed to download.")
        gage_data_status = _read_gage_status(site_dir, latest.get("sequence_id"))

    status = read_validation_site_status(site_dir)
    if status.video_count > 0:
        # A missing manifest only matters once there is a local video for it
        # to track; an image-sequence-only pilot site never has one.
        known_problems.extend(status.manifest_issues)

    dataset_group = _summarize_dataset_group(site_dir)

    # This tracker is about the image-sequence pilot flow specifically, so
    # its progress must come from image-sequence runs (image-sequence-runs/,
    # run-summary.json), never `status.report_count` — that only counts the
    # unrelated video flow's `validation-report*.md` files. Using it here
    # made an image-only site's run count silently read from the wrong
    # flow: 0 after a real image run, or nonzero from a stray video report.
    image_sequence_run_count = 0
    sequence_id = latest.get("sequence_id") if latest is not None else None
    if isinstance(sequence_id, str) and sequence_id:
        image_sequence_run_count = len(list_image_sequence_runs(site_dir, sequence_id))

    human_review_progress = "not_started"
    if latest is not None:
        if baseline_selected and image_sequence_run_count > 0:
            human_review_progress = "validated"
        elif baseline_selected:
            human_review_progress = "baseline_ready"
        else:
            human_review_progress = "images_downloaded"

    return TrackerRow(
        river_id=registry.river_id,
        river_display_name=registry.display_name,
        camera_id=camera.camera_id,
        display_name=camera.display_name,
        folder_name=camera.folder_name,
        camera_availability=camera_availability,
        requested_date_range=requested_date_range,
        daylight_images_downloaded=daylight_images_downloaded,
        missing_days=missing_days,
        gage_data_status=gage_data_status,
        watched_area_status=watched_area_status,
        riverbank_guide_status=riverbank_guide_status,
        baseline_selected=baseline_selected,
        validation_run_count=image_sequence_run_count,
        dataset_group=dataset_group,
        human_review_progress=human_review_progress,
        known_problems=known_problems,
    )


def _read_config_progress(
    site_dir: Path, folder_name: str, known_problems: list[str]
) -> tuple[str, str, bool]:
    config_path = site_dir / "configs" / f"{folder_name}.json"
    try:
        config = load_site_config(config_path)
    except SiteConfigError as error:
        known_problems.append(f"Could not read site config: {error}")
        return "unknown", "unknown", False

    if config.reference_region is None:
        watched_area_status = "not_drawn"
    else:
        region = config.reference_region
        is_default = (
            region.x == _DEFAULT_REFERENCE_REGION["x"]
            and region.y == _DEFAULT_REFERENCE_REGION["y"]
            and region.width == _DEFAULT_REFERENCE_REGION["width"]
            and region.height == _DEFAULT_REFERENCE_REGION["height"]
        )
        watched_area_status = "not_drawn" if is_default else "drawn"

    guides = [
        {
            "status": guide.status,
            "normal_condition": guide.normal_condition,
        }
        for guide in config.normal_waterline_guides
    ]
    riverbank_guide_status = f"{len(guides)} guide(s) drawn" if guides else "not_drawn"
    baseline_selected = is_normal_baseline_confirmed(guides)
    return watched_area_status, riverbank_guide_status, baseline_selected


def _read_gage_status(site_dir: Path, sequence_id: object) -> str:
    if not isinstance(sequence_id, str) or not sequence_id:
        return "not_run"
    summary_path = (
        site_dir / "inputs" / "image-sequences" / sequence_id / "gauge-readings-summary.json"
    )
    if not summary_path.is_file():
        return "not_run"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"
    if not isinstance(summary, dict):
        return "unreadable"
    if summary.get("available"):
        label = summary.get("parameter_label", "gage data")
        return f"available ({label})"
    reason = summary.get("unavailable_reason") or "no reason given"
    return f"unavailable: {reason}"


def _summarize_dataset_group(site_dir: Path) -> str:
    assignments = list_dataset_group_assignments(site_dir)
    if not assignments:
        return DEFAULT_DATASET_GROUP
    return "; ".join(
        f"{assignment.group} ({assignment.start_date} to {assignment.end_date})"
        for assignment in assignments
    )

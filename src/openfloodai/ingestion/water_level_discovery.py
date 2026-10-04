"""Find and download gauge-guided water-level samples (Issue #212 / OF-092).

Discovery fetches only gauge readings and the archive's image LISTING (names,
times, sizes). No image is downloaded until the reviewer approves a set and
confirms. The selection rules live in `water_level_sampling`; this module wires
them to the camera's USGS-provided station association, the real services, and
the existing image-sequence intake.

Both services are passed in as callables so tests use mocked gauge and image
data and never reach the network.

The browser only ever names an approved sample by its group, the motivating
reading's time, and the image's file name. Everything else is re-derived from
fresh data at download time and checked again (`verify_approved`), so a stale or
edited request cannot put an unqualified image into a sequence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from openfloodai.ingestion.river_images import (
    WATER_LEVEL_SAMPLING_MODE,
    ImageSequenceCandidate,
    ImageSequenceDownloadResult,
    RiverImageError,
    camera_slug,
    camera_timezone,
    download_river_image_sequence,
    list_archive_images_between,
    parse_sequence_date_range,
)
from openfloodai.ingestion.river_registry import CameraRecord, find_camera
from openfloodai.ingestion.usgs_gage_data import (
    GageDataError,
    GageReading,
    GageSeries,
    fetch_gage_readings,
)
from openfloodai.ingestion.water_level_sampling import (
    NOTE_RELATIVE,
    POLICY_VERSION,
    SamplingError,
    SelectedSample,
    select_samples,
    verify_approved,
    water_level_unavailable,
)

SELECTION_SCHEMA_VERSION = 1

STATE_OK = "ok"
STATE_NO_STATION = "no_station_association"
STATE_SERVICE_UNAVAILABLE = "gauge_service_unavailable"
STATE_NO_GAUGE_HEIGHT = "gauge_height_unavailable"
STATE_NO_IMAGES = "no_images_in_range"

# One whole-year listing can exceed the downloader's per-request listing cap on a camera
# that archives every few minutes. Discovery only needs names and times, so it lists one
# UTC month at a time, with a total bound so a runaway range still stops.
MAX_DISCOVERY_IMAGES = 300_000


def _month_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    current = start
    while current < end:
        following = (
            datetime(current.year + 1, 1, 1, tzinfo=UTC)
            if current.month == 12
            else datetime(current.year, current.month + 1, 1, tzinfo=UTC)
        )
        windows.append((current, min(following, end)))
        current = following
    return windows


def list_archive_images_chunked(
    slug: str, start_utc: datetime, end_utc: datetime
) -> list[ImageSequenceCandidate]:
    """Archive image listing for [start, end), fetched one UTC month at a time."""

    images: list[ImageSequenceCandidate] = []
    for window_start, window_end in _month_windows(start_utc, end_utc):
        try:
            images.extend(list_archive_images_between(slug, window_start, window_end))
        except RiverImageError as error:
            if "too many images" in str(error):
                raise RiverImageError(
                    "This camera archives too many images in one month to list for "
                    "water-level sampling. Choose a shorter date range."
                ) from error
            raise
        if len(images) > MAX_DISCOVERY_IMAGES:
            raise RiverImageError(
                "This date range covers too many archive images to list. "
                "Choose a shorter date range."
            )
    return images


GaugeFetcher = Callable[[str, str, str], GageSeries]
ImageLister = Callable[[str, datetime, datetime], list[ImageSequenceCandidate]]


@dataclass(frozen=True)
class DiscoveryContext:
    """Everything a discovery needs that does not come from the form."""

    slug: str
    camera: CameraRecord | None
    timezone: str
    start_date: str
    end_date: str
    start_utc: datetime
    end_utc: datetime


def build_context(
    camera_url: str, start_date: str, end_date: str, timezone_name: str, reference_dir: Path
) -> DiscoveryContext:
    slug = camera_slug(camera_url)
    camera = find_camera(slug, reference_dir)
    zone_name = (
        timezone_name.strip() or (camera.timezone if camera else "") or camera_timezone(slug)
    )
    start_utc, end_utc = parse_sequence_date_range(start_date.strip(), end_date.strip(), zone_name)
    return DiscoveryContext(
        slug, camera, zone_name, start_date.strip(), end_date.strip(), start_utc, end_utc
    )


def _padded_dates(context: DiscoveryContext) -> tuple[str, str]:
    """Fetch a day either side: NWIS dates are site-local, and the range is trimmed afterward."""

    start = date.fromisoformat(context.start_date) - timedelta(days=1)
    end = date.fromisoformat(context.end_date) + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _in_period(readings: Sequence[GageReading], context: DiscoveryContext) -> list[GageReading]:
    return [
        reading
        for reading in readings
        if context.start_utc <= datetime.fromisoformat(reading.datetime_utc) < context.end_utc
    ]


def _association(camera: CameraRecord) -> dict[str, Any]:
    return {
        "camera_id": camera.camera_id,
        "nwis_site_id": camera.nwis_id,
        "relationship": camera.gage_relationship,
        "relationship_note": camera.gage_relationship_note,
        "source": camera.registry_source or None,
        "source_checked": camera.registry_source_checked,
        "registry": camera.river_id,
    }


def _base(context: DiscoveryContext, groups: Sequence[str], per_group: int) -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "note": NOTE_RELATIVE,
        "camera_id": context.slug,
        "timezone": context.timezone,
        "request": {
            "start_date": context.start_date,
            "end_date": context.end_date,
            "groups": list(groups),
            "images_per_group": per_group,
        },
        "association": _association(context.camera) if context.camera else None,
    }


def discover(
    context: DiscoveryContext,
    *,
    groups: Sequence[str],
    images_per_group: int,
    kept: Sequence[Mapping[str, str]] = (),
    declined: Sequence[str] = (),
    fetch_gauge: GaugeFetcher | None = None,
    list_images: ImageLister | None = None,
) -> dict[str, Any]:
    """Propose samples, or explain why water-level sampling cannot be used here."""

    fetch_gauge = fetch_gauge or fetch_gage_readings
    list_images = list_images or list_archive_images_chunked
    out = _base(context, groups, images_per_group)
    out["selected_at_utc"] = datetime.now(tz=UTC).isoformat()
    camera = context.camera
    if camera is None or camera.gage_relationship == "unavailable":
        out["state"] = STATE_NO_STATION
        out["message"] = (
            "USGS does not provide a gauge association for this camera, so water-level "
            "sampling is unavailable. The nearest station is never guessed."
        )
        return out
    series, readings, state_message = _load_gauge(context, camera, fetch_gauge)
    if state_message is not None:
        out["state"], out["message"] = state_message
        return out
    assert series is not None
    out["gauge"] = {
        "nwis_site_id": camera.nwis_id,
        "parameter_code": series.parameter_code,
        "parameter_label": series.parameter_label,
        "unit": series.unit,
        "source_url": series.source_url,
        "rejected_reading_count": series.rejected_reading_count,
        "valid_reading_count": len(readings),
    }
    images = list_images(context.slug, context.start_utc, context.end_utc)
    if not images:
        out["state"] = STATE_NO_IMAGES
        out["message"] = "The camera archive lists no images for this date range."
        return out
    kept_samples = (
        verify_approved(kept, readings, images, timezone_name=context.timezone, unit=series.unit)
        if kept
        else []
    )
    kept_by_group: dict[str, list[SelectedSample]] = {}
    for sample in kept_samples:
        kept_by_group.setdefault(sample.group, []).append(sample)
    result = select_samples(
        readings,
        images,
        groups=groups,
        images_per_group=images_per_group,
        timezone_name=context.timezone,
        unit=series.unit,
        kept=kept_by_group,
        declined_images=frozenset(declined),
    )
    out["state"] = STATE_OK
    out["selection"] = result.to_dict()
    out["declined_images"] = sorted(set(declined))
    if camera.gage_relationship == "nearby":
        out["warning"] = (
            "USGS lists this gauge as nearby, not at the camera. "
            + (camera.gage_relationship_note or "")
        ).strip()
    return out


def _load_gauge(
    context: DiscoveryContext, camera: CameraRecord, fetch_gauge: GaugeFetcher
) -> tuple[GageSeries | None, list[GageReading], tuple[str, str] | None]:
    start, end = _padded_dates(context)
    try:
        series = fetch_gauge(camera.nwis_id, start, end)
    except GageDataError:
        return (
            None,
            [],
            (
                STATE_SERVICE_UNAVAILABLE,
                "The USGS water-services request failed, so no samples can be proposed. "
                "Try again later.",
            ),
        )
    reason = water_level_unavailable(series.parameter_code, series.used_fallback_discharge)
    if reason is not None:
        return None, [], (STATE_NO_GAUGE_HEIGHT, reason)
    return series, _in_period(series.readings, context), None


def build_provenance(
    context: DiscoveryContext,
    discovery: Mapping[str, Any],
    samples: Sequence[SelectedSample],
    *,
    declined: Sequence[str],
) -> dict[str, Any]:
    """The saved, auditable record of why each approved image was chosen."""

    selection = discovery["selection"]
    return {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "selected_at_utc": discovery["selected_at_utc"],
        "note": NOTE_RELATIVE,
        "camera_id": context.slug,
        "timezone": context.timezone,
        "request": discovery["request"],
        "association": discovery["association"],
        "gauge": discovery["gauge"],
        "thresholds": selection["thresholds"],
        "samples": [{**sample.to_dict(), "filename": sample.filename} for sample in samples],
        "groups": [
            {
                "group": group["group"],
                "requested": group["requested"],
                "approved": approved_count,
                "shortfall": (
                    {"missing": group["requested"] - approved_count, "reason": "fewer_approved"}
                    if approved_count < group["requested"]
                    else None
                ),
                "policy_skipped": group["skipped"],
                "policy_skipped_examples": group["skipped_examples"],
            }
            for group in selection["groups"]
            for approved_count in [sum(1 for s in samples if s.group == group["group"])]
        ],
        "policy_run_note": (
            "Thresholds and skip reasons come from a fresh policy run on the same readings "
            "and images at download time; the approved samples above are what was downloaded."
        ),
        "declined_images": sorted(set(declined)),
        "approved_by_reviewer": True,
    }


def download_approved(
    context: DiscoveryContext,
    *,
    approved: Sequence[Mapping[str, str]],
    declined: Sequence[str],
    groups: Sequence[str],
    images_per_group: int,
    site_id: str,
    site_dir: Path,
    overwrite: bool = False,
    resume: bool = False,
    fetch_gauge: GaugeFetcher | None = None,
    list_images: ImageLister | None = None,
    download: Callable[..., ImageSequenceDownloadResult] | None = None,
) -> tuple[ImageSequenceDownloadResult, dict[str, Any]]:
    """Verify the approved set from fresh data, then download only those images."""

    fetch_gauge = fetch_gauge or fetch_gage_readings
    list_images = list_images or list_archive_images_chunked
    download = download or download_river_image_sequence
    if not approved:
        raise RiverImageError("Approve at least one sample before downloading.")
    camera = context.camera
    if camera is None or camera.gage_relationship == "unavailable":
        raise RiverImageError("This camera has no USGS gauge association.")
    series, readings, problem = _load_gauge(context, camera, fetch_gauge)
    if problem is not None or series is None:
        raise RiverImageError(problem[1] if problem else "Gauge data is unavailable.")
    images = list_images(context.slug, context.start_utc, context.end_utc)
    try:
        samples = verify_approved(
            approved, readings, images, timezone_name=context.timezone, unit=series.unit
        )
    except SamplingError as error:
        raise RiverImageError(f"{error} Run Find samples again before downloading.") from error
    # A clean policy run from the same data supplies the thresholds and skip reasons, so the
    # saved provenance is ours, not the browser's. The approved set is recorded separately.
    discovery = discover(
        context,
        groups=groups,
        images_per_group=images_per_group,
        declined=declined,
        fetch_gauge=lambda *_: series,
        list_images=lambda *_: images,
    )
    provenance = build_provenance(context, discovery, samples, declined=declined)
    result = download(
        camera_url=f"https://apps.usgs.gov/hivis/camera/{context.slug}",
        start_date=context.start_date,
        end_date=context.end_date,
        timezone_name=context.timezone,
        sampling_mode=WATER_LEVEL_SAMPLING_MODE,
        site_id=site_id,
        site_dir=site_dir,
        overwrite=overwrite,
        resume=resume,
        selected_candidates=[sample.image for sample in samples],
        selection_provenance=provenance,
    )
    return result, provenance

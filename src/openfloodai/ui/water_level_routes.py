"""Routes for gauge-guided water-level image sampling (Issue #212).

`preview` fetches gauge readings and the archive's image LISTING only; it never
downloads an image. `download` re-derives and re-verifies every approved sample
from fresh data, needs an explicit confirmation of the exact image count, and
then uses the existing image-sequence intake.
"""

from __future__ import annotations

from typing import Any

from openfloodai.config import SiteConfigError, load_site_config
from openfloodai.ingestion import water_level_discovery as discovery
from openfloodai.ingestion import water_level_sampling as sampling
from openfloodai.ingestion.river_images import RiverImageError
from openfloodai.ingestion.usgs_gage_data import GageDataError

PREVIEW_PATH = "/api/preview-water-level-sampling"
DOWNLOAD_PATH = "/api/download-water-level-sampling"
_MAX_BODY_BYTES = 48 * 1024
_MAX_APPROVED = len(sampling.GROUPS) * sampling.MAX_IMAGES_PER_GROUP
_MAX_DECLINED = 200


def _items(value: Any, limit: int, what: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{what} must be a list of at most {limit} items.")
    return value


def _sample_refs(value: Any, what: str) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in _items(value, _MAX_APPROVED, what):
        if not isinstance(item, dict):
            raise ValueError(f"Each item in {what} must be an object.")
        refs.append(
            {
                "group": str(item.get("group", "")),
                "reading_datetime_utc": str(item.get("reading_datetime_utc", "")),
                "filename": str(item.get("filename", "")),
            }
        )
    return refs


def _parse(data: dict[str, Any], reference_dir: Any) -> tuple[Any, list[str], int, list[str], str]:
    groups = [str(g) for g in _items(data.get("groups"), len(sampling.GROUPS), "groups")]
    per_group = data.get("images_per_group", sampling.DEFAULT_IMAGES_PER_GROUP)
    if isinstance(per_group, bool) or not isinstance(per_group, int):
        raise ValueError("Images per group must be a whole number.")
    declined = [str(n) for n in _items(data.get("declined"), _MAX_DECLINED, "declined")]
    context = discovery.build_context(
        str(data.get("camera_url", "")),
        str(data.get("start_date", "")),
        str(data.get("end_date", "")),
        str(data.get("timezone", "")),
        reference_dir,
    )
    time_of_day = sampling.validate_time_of_day(str(data.get("time_of_day", "any")))
    return context, groups, per_group, declined, time_of_day


def handle_post(handler: Any, path: str) -> bool:
    if path not in {PREVIEW_PATH, DOWNLOAD_PATH}:
        return False
    data = handler._reject_untrusted_json_post(_MAX_BODY_BYTES)
    if data is None:
        return True
    try:
        context, groups, per_group, declined, time_of_day = _parse(data, handler._reference_dir())
        if path == PREVIEW_PATH:
            kept = _sample_refs(data.get("kept"), "kept")
            result = discovery.discover(
                context,
                groups=groups,
                images_per_group=per_group,
                kept=kept,
                declined=declined,
                time_of_day=time_of_day,
            )
            handler._send_json({"success": True, **result}, status_code=200)
        else:
            _download(handler, data, context, groups, per_group, declined, time_of_day)
    except (
        ValueError,
        sampling.SamplingError,
        RiverImageError,
        GageDataError,
        SiteConfigError,
    ) as error:
        handler._send_json({"success": False, "message": str(error)}, status_code=400)
    except OSError:
        handler._send_json(
            {"message": "Could not save the download. Check local disk space and permissions."},
            status_code=500,
        )
    return True


def _download(
    handler: Any,
    data: dict[str, Any],
    context: Any,
    groups: list[str],
    per_group: int,
    declined: list[str],
    time_of_day: str,
) -> None:
    approved = _sample_refs(data.get("approved"), "approved")
    if data.get("confirmed") is not True or data.get("confirmed_count") != len(approved):
        raise ValueError(
            f"Confirm the download of exactly {len(approved)} approved image(s) to continue."
        )
    site_dir = handler._resolve_site_dir(str(data.get("folder_name", "")).strip())
    config_paths = sorted((site_dir / "configs").glob("*.json"))
    if not config_paths:
        raise SiteConfigError(f"Site config was not found under {site_dir / 'configs'}")
    site_config = load_site_config(config_paths[0])
    result, _ = discovery.download_approved(
        context,
        approved=approved,
        declined=declined,
        groups=groups,
        images_per_group=per_group,
        site_id=site_config.site_id,
        site_dir=site_dir,
        overwrite=data.get("overwrite") is True,
        resume=data.get("resume") is True,
        time_of_day=time_of_day,
    )
    payload = result.to_dict()
    payload["sampling_mode"] = "water_level"
    payload["gage_available"] = handler._write_gage_data_if_camera_registered(
        result.directory, site_config.camera_id, context.start_date, context.end_date
    )
    handler._send_json(payload, status_code=200)

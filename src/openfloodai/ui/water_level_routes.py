"""Routes for gauge-guided water-level image sampling (Issues #212 and #214).

`preview` fetches gauge readings and the archive's image LISTING only; it never
downloads an image. `destinations` lists the site's sequences that can take the
camera's images, with reasons for any that cannot. `plan` says what approving a set
would do to a destination (new images, duplicates skipped, conflicts) without
changing anything. `download` re-derives and re-verifies every approved sample from
fresh data, recomputes the plan, and only proceeds if the caller confirmed exactly
those counts; it then creates a new sequence or appends to an existing one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openfloodai.config import SiteConfigError, load_site_config
from openfloodai.ingestion import water_level_discovery as discovery
from openfloodai.ingestion import water_level_intake as intake
from openfloodai.ingestion import water_level_sampling as sampling
from openfloodai.ingestion.river_images import RiverImageError, list_site_image_sequences
from openfloodai.ingestion.sequence_store import validate_display_name
from openfloodai.ingestion.usgs_gage_data import GageDataError

PREVIEW_PATH = "/api/preview-water-level-sampling"
DOWNLOAD_PATH = "/api/download-water-level-sampling"
DESTINATIONS_PATH = "/api/water-level-destinations"
PLAN_PATH = "/api/plan-water-level-intake"
_ALL_PATHS = {PREVIEW_PATH, DOWNLOAD_PATH, DESTINATIONS_PATH, PLAN_PATH}
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


def _site_config(handler: Any, data: dict[str, Any]) -> Any | None:
    """The named site's saved config, or None when the request names no site."""

    folder_name = str(data.get("folder_name", "")).strip()
    if not folder_name:
        return None
    site_dir = handler._resolve_site_dir(folder_name)
    config_paths = sorted((site_dir / "configs").glob("*.json"))
    if not config_paths:
        raise SiteConfigError(f"Site config was not found under {site_dir / 'configs'}")
    return load_site_config(config_paths[0])


def _cameras_in_site(site_dir: Path) -> set[str]:
    """The USGS camera ids of every image already saved in this site's sequences."""

    cameras: set[str] = set()
    for sequence in list_site_image_sequences(site_dir):
        for record in sequence.get("records", []):
            if isinstance(record, dict) and record.get("camera_id"):
                cameras.add(str(record["camera_id"]))
    return cameras


def _check_camera(
    handler: Any, data: dict[str, Any], context: Any, site_config: Any | None
) -> str | None:
    """Keep one site to one camera without requiring its internal label to equal the USGS id.

    A site's own `camera_id` is an internal label (it may carry a suffix such as `_camid`),
    so it is not compared with the camera in the URL. Images and the gauge station both
    come from the URL's camera and the registry entry for it, so they cannot disagree.

    What is protected is the site's saved evidence: if the site already holds images from
    a different USGS camera, adding another camera's images is refused. If the site has no
    images yet, the URL's camera defines it, and a differing label is only noted.
    """

    if site_config is None:
        return None
    site_dir = handler._resolve_site_dir(str(data.get("folder_name", "")).strip())
    held = _cameras_in_site(site_dir)
    if held and context.slug not in held:
        raise ValueError(
            f"This site already holds images from camera {', '.join(sorted(held))}, but the "
            f"camera URL is for {context.slug}. Use that camera's URL, or add these images to a "
            "site made for this camera."
        )
    if site_config.camera_id != context.slug and not held:
        return (
            f"This site's own camera id is {site_config.camera_id}. Its images will be saved "
            f"as USGS camera {context.slug}, taken from the URL you entered."
        )
    return None


def _destination(data: dict[str, Any]) -> tuple[str | None, str | None]:
    """(existing sequence id or None for a new one, validated optional display name)."""

    raw = data.get("destination")
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        raise ValueError("destination must be an object.")
    mode = str(raw.get("mode", "new"))
    if mode == "new":
        return None, validate_display_name(raw.get("name"))
    if mode != "append":
        raise ValueError("destination mode must be 'new' or 'append'.")
    sequence_id = raw.get("sequence_id")
    if not isinstance(sequence_id, str) or not sequence_id:
        raise ValueError("Choose the sequence to add to.")
    return sequence_id, None


def handle_post(handler: Any, path: str) -> bool:
    if path not in _ALL_PATHS:
        return False
    data = handler._reject_untrusted_json_post(_MAX_BODY_BYTES)
    if data is None:
        return True
    try:
        context, groups, per_group, declined, time_of_day = _parse(data, handler._reference_dir())
        site_config = _site_config(handler, data)
        camera_notice = _check_camera(handler, data, context, site_config)
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
            if camera_notice:
                result["camera_notice"] = camera_notice
            handler._send_json({"success": True, **result}, status_code=200)
        elif path == DESTINATIONS_PATH:
            _destinations(handler, data, context, site_config)
        elif path == PLAN_PATH:
            _plan(handler, data, context, groups, per_group, time_of_day)
        else:
            _download(handler, data, context, groups, per_group, declined, time_of_day, site_config)
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


def _destinations(
    handler: Any, data: dict[str, Any], context: Any, site_config: Any | None
) -> None:
    if site_config is None:
        raise ValueError("Choose the site first.")
    if context.camera is None:
        raise ValueError("This camera has no USGS gauge association, so it cannot be added to.")
    site_dir = handler._resolve_site_dir(str(data.get("folder_name", "")).strip())
    rows = intake.list_destinations(
        site_dir,
        camera_slug=context.slug,
        timezone_name=context.timezone,
        site_id=site_config.site_id,
        nwis_site_id=context.camera.nwis_id,
    )
    handler._send_json({"success": True, "destinations": rows}, status_code=200)


def _plan(
    handler: Any,
    data: dict[str, Any],
    context: Any,
    groups: list[str],
    per_group: int,
    time_of_day: str,
) -> None:
    site_dir = handler._resolve_site_dir(str(data.get("folder_name", "")).strip())
    destination_id, _ = _destination(data)
    plan = discovery.plan_intake(
        context,
        approved=_sample_refs(data.get("approved"), "approved"),
        groups=groups,
        images_per_group=per_group,
        site_dir=site_dir,
        destination_id=destination_id,
        time_of_day=time_of_day,
    )
    handler._send_json(
        {"success": True, "plan": plan.to_dict(), "destination_id": destination_id},
        status_code=200,
    )


def _confirmed(data: dict[str, Any], plan: Any, approved_count: int) -> bool:
    """Did the caller confirm exactly what the server now says will happen?"""

    if data.get("confirmed") is not True:
        return False
    counts = data.get("confirmed_plan")
    if isinstance(counts, dict):
        return bool(
            counts.get("new") == plan.new_count
            and counts.get("duplicates") == plan.duplicate_count
            and counts.get("conflicts") == plan.conflict_count
        )
    # Older form: only the number of images, which for a new sequence is all of them.
    return (
        data.get("confirmed_count") == approved_count
        and plan.new_count == approved_count
        and not plan.duplicate_count
        and not plan.conflict_count
    )


def _summary_message(result: Any) -> str:
    label = result.to_dict()["label"]
    parts = [f"Added {len(result.added)} new image(s) to {label}."]
    if result.duplicates:
        parts.append(f"Skipped {len(result.duplicates)} already present.")
    if result.conflicts:
        parts.append(f"{len(result.conflicts)} conflict(s) not added.")
    if result.failed:
        parts.append(f"{len(result.failed)} could not be downloaded.")
    if result.no_op:
        parts.append("Nothing changed.")
    return " ".join(parts)


def _download(
    handler: Any,
    data: dict[str, Any],
    context: Any,
    groups: list[str],
    per_group: int,
    declined: list[str],
    time_of_day: str,
    site_config: Any | None,
) -> None:
    if site_config is None:
        raise ValueError("Choose the site to download into.")
    approved = _sample_refs(data.get("approved"), "approved")
    destination_id, display_name = _destination(data)
    site_dir = handler._resolve_site_dir(str(data.get("folder_name", "")).strip())
    plan = discovery.plan_intake(
        context,
        approved=approved,
        groups=groups,
        images_per_group=per_group,
        site_dir=site_dir,
        destination_id=destination_id,
        time_of_day=time_of_day,
    )
    if not _confirmed(data, plan, len(approved)):
        raise ValueError(
            f"Confirm what will happen: add {plan.new_count} new image(s), skip "
            f"{plan.duplicate_count} already present, {plan.conflict_count} conflict(s) not added."
            " Run the plan again if this changed."
        )
    result, _ = discovery.download_approved(
        context,
        approved=approved,
        declined=declined,
        groups=groups,
        images_per_group=per_group,
        site_id=site_config.site_id,
        site_dir=site_dir,
        destination_id=destination_id,
        display_name=display_name,
        time_of_day=time_of_day,
    )
    payload = result.to_dict()
    payload.update(
        {
            "message": _summary_message(result),
            "sampling_mode": "water_level",
            "downloaded_count": len(result.added),
            "missing_count": 0,
        }
    )
    handler._send_json(payload, status_code=200)

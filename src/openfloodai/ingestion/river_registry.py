"""Load a river's camera registry file (issue #152's source of truth for site grouping)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_RIVER_ID_PATTERN = re.compile(r"^[a-z0-9-]{1,80}$")
# Matches site_setup.py's own folder-name pattern: every caller resolves
# `sites_base_dir / folder_name` directly, so an unvalidated value here
# (e.g. containing "..") could resolve outside the sites directory.
_FOLDER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class RiverRegistryError(ValueError):
    """Raised when a river registry file cannot be loaded or is invalid."""


@dataclass(frozen=True)
class CameraRecord:
    """One camera entry from a river registry file."""

    river_id: str
    camera_id: str
    nwis_id: str
    state: str
    latitude: float
    longitude: float
    display_name: str
    folder_name: str
    gage_relationship: str
    timezone: str
    gage_relationship_note: str | None = None


@dataclass(frozen=True)
class RiverRegistry:
    """A river's camera registry: the source of truth for grouping sites by river."""

    river_id: str
    display_name: str
    source: str
    notes: str
    cameras: tuple[CameraRecord, ...]

    def camera(self, camera_id: str) -> CameraRecord | None:
        for camera in self.cameras:
            if camera.camera_id == camera_id:
                return camera
        return None


def _require_str(record: dict[str, Any], field: str, *, context: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RiverRegistryError(f"{context}: field '{field}' must be a non-empty string.")
    return value


def _require_float(record: dict[str, Any], field: str, *, context: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RiverRegistryError(f"{context}: field '{field}' must be a number.")
    return float(value)


def load_river_registry(river_id: str, reference_dir: Path) -> RiverRegistry:
    """Load and validate `<reference_dir>/rivers/<river_id>.json`."""

    if not _RIVER_ID_PATTERN.fullmatch(river_id):
        raise RiverRegistryError(
            "Invalid river id: use lowercase letters, digits, and dashes only."
        )
    registry_path = (reference_dir / "rivers" / f"{river_id}.json").resolve()
    try:
        reference_root = reference_dir.resolve()
        registry_path.relative_to(reference_root)
    except ValueError as error:
        raise RiverRegistryError(
            "Invalid river id: path escapes the reference directory."
        ) from error

    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RiverRegistryError(
            f"No river registry found for '{river_id}': {registry_path}"
        ) from error
    except json.JSONDecodeError as error:
        raise RiverRegistryError(f"River registry is not valid JSON: {registry_path}") from error

    if not isinstance(raw, dict):
        raise RiverRegistryError("River registry file must contain a JSON object.")

    display_name = _require_str(raw, "display_name", context="River registry")
    source = raw.get("source")
    if not isinstance(source, str):
        source = ""

    raw_cameras = raw.get("cameras")
    if not isinstance(raw_cameras, list) or not raw_cameras:
        raise RiverRegistryError("River registry must include a non-empty 'cameras' list.")

    cameras: list[CameraRecord] = []
    seen_camera_ids: set[str] = set()
    for index, entry in enumerate(raw_cameras):
        if not isinstance(entry, dict):
            raise RiverRegistryError(f"Camera entry #{index} must be a JSON object.")
        context = f"Camera entry #{index}"
        camera_id = _require_str(entry, "camera_id", context=context)
        if camera_id in seen_camera_ids:
            raise RiverRegistryError(f"Duplicate camera_id in registry: {camera_id}")
        seen_camera_ids.add(camera_id)

        folder_name = _require_str(entry, "folder_name", context=context)
        if not _FOLDER_NAME_PATTERN.fullmatch(folder_name):
            raise RiverRegistryError(
                f"{context}: folder_name must use only letters, numbers, dash, and "
                f"underscore (got {folder_name!r})."
            )

        gage_relationship = _require_str(entry, "gage_relationship", context=context)
        if gage_relationship not in {"same_site", "nearby", "unavailable"}:
            raise RiverRegistryError(
                f"{context}: gage_relationship must be same_site, nearby, or unavailable."
            )
        gage_relationship_note = entry.get("gage_relationship_note")
        if gage_relationship == "nearby" and not (
            isinstance(gage_relationship_note, str) and gage_relationship_note.strip()
        ):
            raise RiverRegistryError(
                f"{context}: a 'nearby' gage_relationship needs a gage_relationship_note."
            )

        cameras.append(
            CameraRecord(
                river_id=_require_str(entry, "river_id", context=context),
                camera_id=camera_id,
                nwis_id=_require_str(entry, "nwis_id", context=context),
                state=_require_str(entry, "state", context=context),
                latitude=_require_float(entry, "latitude", context=context),
                longitude=_require_float(entry, "longitude", context=context),
                display_name=_require_str(entry, "display_name", context=context),
                folder_name=folder_name,
                gage_relationship=gage_relationship,
                timezone=_require_str(entry, "timezone", context=context),
                gage_relationship_note=(
                    gage_relationship_note if isinstance(gage_relationship_note, str) else None
                ),
            )
        )

    notes = raw.get("notes")
    return RiverRegistry(
        river_id=_require_str(raw, "river_id", context="River registry"),
        display_name=display_name,
        source=source,
        notes=notes if isinstance(notes, str) else "",
        cameras=tuple(cameras),
    )


def list_river_registries(reference_dir: Path) -> list[dict[str, Any]]:
    """Return {river_id, display_name, camera_count} for every registry on disk.

    Lightweight by design (no camera-level detail) -- for populating a
    river picker, not for tracking progress. Skips any file that fails to
    parse rather than raising, so one bad registry can't take down the
    whole list.
    """

    rivers_dir = reference_dir / "rivers"
    if not rivers_dir.is_dir():
        return []
    rivers: list[dict[str, Any]] = []
    for path in sorted(rivers_dir.glob("*.json")):
        try:
            registry = load_river_registry(path.stem, reference_dir)
        except RiverRegistryError:
            continue
        rivers.append(
            {
                "river_id": registry.river_id,
                "display_name": registry.display_name,
                "camera_count": len(registry.cameras),
            }
        )
    return sorted(rivers, key=lambda r: r["display_name"])


def find_camera(camera_id: str, reference_dir: Path) -> CameraRecord | None:
    """Search every river registry under reference_dir for one camera, by id.

    Best-effort: a camera_id belongs to at most one registry, but which
    river it's under isn't known to a caller that only has a site's
    camera_id (e.g. a site created outside the River Camera Tracker's
    bootstrap flow). Skips any registry file that fails to parse rather
    than raising, since most sites are never registered at all.
    """

    rivers_dir = reference_dir / "rivers"
    if not rivers_dir.is_dir():
        return None
    for path in sorted(rivers_dir.glob("*.json")):
        try:
            registry = load_river_registry(path.stem, reference_dir)
        except RiverRegistryError:
            continue
        camera = registry.camera(camera_id)
        if camera is not None:
            return camera
    return None

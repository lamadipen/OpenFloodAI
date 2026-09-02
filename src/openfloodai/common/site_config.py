"""Unified site configuration for OpenFloodAI.

Combines camera/video configuration (for POC pipelines) with geolocation
and hydrological metadata (for edge monitoring and data-source queries)
into a single ``SiteConfig`` dataclass.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

InputType = Literal["local_video", "camera_stream"]


class SiteConfigError(ValueError):
    """Raised when site configuration cannot be loaded or is invalid."""


@dataclass(frozen=True)
class ReferenceRegion:
    """A broad image region to watch, written as percentages of the full frame."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class SiteConfig:
    """Configuration for a single monitored site."""

    site_id: str
    camera_id: str
    latitude: float | None = None
    longitude: float | None = None
    site_name: str = ""
    public_location: str = ""
    description: str = ""
    input_type: InputType | None = None
    reference_region: ReferenceRegion | None = None
    privacy_notes: str | None = None
    usgs_site_number: str | None = None
    nws_zone: str | None = None
    flood_stage_ft: float | None = None


_ALLOWED_FIELDS = frozenset(
    {
        "site_id",
        "camera_id",
        "latitude",
        "longitude",
        "site_name",
        "public_location",
        "description",
        "input_type",
        "reference_region",
        "privacy_notes",
        "usgs_site_number",
        "nws_zone",
        "flood_stage_ft",
    }
)

_REQUIRED_FIELDS = frozenset({"site_id", "camera_id"})


def load_site_config(config_path: Path) -> list[SiteConfig]:
    """Load site configurations from a JSON file.

    Accepts a JSON array of objects or a single JSON object (auto-wrapped
    in a list for backward compatibility with POC configs).

    Raises :class:`SiteConfigError` when the file cannot be read or the
    content is not a valid site configuration.
    """

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SiteConfigError(f"Cannot read site config file {config_path}: {exc}") from exc

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SiteConfigError(f"Invalid JSON in site config file {config_path}: {exc}") from exc

    if isinstance(data, dict):
        entries: list[object] = [data]
    elif isinstance(data, list):
        entries = data
    else:
        raise SiteConfigError(
            f"Site config file must contain a JSON object or array, got {type(data).__name__}"
        )

    configs: list[SiteConfig] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SiteConfigError(
                f"Entry {index} in site config must be an object, got {type(entry).__name__}"
            )
        configs.append(_parse_site_entry(entry, index))

    return configs


def save_site_config(configs: list[SiteConfig], config_path: Path) -> None:
    """Save site configurations to a JSON file.

    Creates parent directories if they do not exist.

    Raises :class:`SiteConfigError` when the file cannot be written.
    """

    data = [_site_to_dict(cfg) for cfg in configs]
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise SiteConfigError(f"Cannot write site config file {config_path}: {exc}") from exc


def find_site(configs: list[SiteConfig], site_id: str) -> SiteConfig | None:
    """Look up a site configuration by its ``site_id``.

    Returns ``None`` if no matching site is found.
    """

    for cfg in configs:
        if cfg.site_id == site_id:
            return cfg
    return None


def _site_to_dict(cfg: SiteConfig) -> dict[str, object]:
    """Serialize a SiteConfig to a dict, converting ReferenceRegion."""

    d = asdict(cfg)
    return {k: v for k, v in d.items() if v is not None and v != ""}


def _parse_site_entry(
    entry: dict[str, Any],
    index: int,
) -> SiteConfig:
    """Parse and validate a single site config entry."""

    extra = sorted(entry.keys() - _ALLOWED_FIELDS)
    if extra:
        raise SiteConfigError(
            f"Entry {index} in site config has unsupported field(s): {', '.join(extra)}"
        )

    missing = sorted(_REQUIRED_FIELDS - entry.keys())
    if missing:
        raise SiteConfigError(
            f"Entry {index} in site config is missing required field(s): {', '.join(missing)}"
        )

    site_id = _require_text(entry, "site_id", index)
    camera_id = _require_text(entry, "camera_id", index)
    latitude = _opt_number(entry, "latitude", index)
    longitude = _opt_number(entry, "longitude", index)
    site_name = _opt_text(entry, "site_name", index)
    public_location = _opt_text(entry, "public_location", index)
    description = _opt_text(entry, "description", index)
    input_type = _opt_input_type(entry, index)
    reference_region = _opt_reference_region(entry, index)
    privacy_notes = _opt_text_or_none(entry, "privacy_notes", index)
    usgs_site_number = _opt_text_or_none(entry, "usgs_site_number", index)
    nws_zone = _opt_text_or_none(entry, "nws_zone", index)
    flood_stage_ft = _opt_number(entry, "flood_stage_ft", index)

    return SiteConfig(
        site_id=site_id,
        camera_id=camera_id,
        latitude=latitude,
        longitude=longitude,
        site_name=site_name,
        public_location=public_location,
        description=description,
        input_type=input_type,
        reference_region=reference_region,
        privacy_notes=privacy_notes,
        usgs_site_number=usgs_site_number,
        nws_zone=nws_zone,
        flood_stage_ft=flood_stage_ft,
    )


def _require_text(
    entry: dict[str, Any],
    field: str,
    index: int,
) -> str:
    value = entry[field]
    if not isinstance(value, str) or not value.strip():
        raise SiteConfigError(f"Entry {index}: field '{field}' must be a non-empty string")
    return value.strip()


def _opt_text(
    entry: dict[str, Any],
    field: str,
    index: int,
) -> str:
    value = entry.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SiteConfigError(f"Entry {index}: field '{field}' must be a string")
    return value.strip()


def _opt_text_or_none(
    entry: dict[str, Any],
    field: str,
    index: int,
) -> str | None:
    value = entry.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SiteConfigError(f"Entry {index}: field '{field}' must be a non-empty string")
    return value.strip()


def _opt_number(
    entry: dict[str, Any],
    field: str,
    index: int,
) -> float | None:
    value = entry.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SiteConfigError(f"Entry {index}: field '{field}' must be a number")
    return float(value)


def _opt_input_type(
    entry: dict[str, Any],
    index: int,
) -> InputType | None:
    value = entry.get("input_type")
    if value is None:
        return None
    if value == "local_video":
        return "local_video"
    if value == "camera_stream":
        return "camera_stream"
    raise SiteConfigError(
        f"Entry {index}: field 'input_type' must be 'local_video' or 'camera_stream'"
    )


def _opt_reference_region(
    entry: dict[str, Any],
    index: int,
) -> ReferenceRegion | None:
    value = entry.get("reference_region")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SiteConfigError(f"Entry {index}: field 'reference_region' must be a JSON object")

    region = dict[str, Any](value)
    expected = {"x", "y", "width", "height"}

    missing = sorted(expected - region.keys())
    if missing:
        raise SiteConfigError(
            f"Entry {index}: reference_region is missing field(s): {', '.join(missing)}"
        )

    extra = sorted(region.keys() - expected)
    if extra:
        raise SiteConfigError(
            f"Entry {index}: reference_region has unsupported field(s): {', '.join(extra)}"
        )

    x = _region_number(region["x"], "x", index)
    y = _region_number(region["y"], "y", index)
    width = _region_number(region["width"], "width", index)
    height = _region_number(region["height"], "height", index)

    if x < 0 or y < 0:
        raise SiteConfigError(f"Entry {index}: reference_region x and y must be 0 or greater")
    if width <= 0 or height <= 0:
        raise SiteConfigError(
            f"Entry {index}: reference_region width and height must be greater than 0"
        )
    if x + width > 100 or y + height > 100:
        raise SiteConfigError(
            f"Entry {index}: reference_region must fit inside the 0-100 image area"
        )

    return ReferenceRegion(x=x, y=y, width=width, height=height)


def _region_number(value: object, field: str, index: int) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SiteConfigError(f"Entry {index}: reference_region field '{field}' must be a number")
    return float(value)

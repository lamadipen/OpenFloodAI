"""Site and camera configuration loading for local POC runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

InputType = Literal["local_video", "camera_stream"]

REQUIRED_FIELDS = {
    "site_id",
    "camera_id",
    "site_name",
    "input_type",
}
OPTIONAL_FIELDS = {
    "public_location",
    "reference_region",
    "privacy_notes",
}
ALLOWED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS


class SiteConfigError(ValueError):
    """Raised when a site/camera config file is invalid."""


@dataclass(frozen=True)
class ReferenceRegion:
    """A broad image region to watch, written as percentages of the full frame."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class SiteCameraConfig:
    """Safe public config for one local POC site and camera."""

    site_id: str
    camera_id: str
    site_name: str
    public_location: str | None
    input_type: InputType
    reference_region: ReferenceRegion | None = None
    privacy_notes: str | None = None


def load_site_config(config_path: Path) -> SiteCameraConfig:
    """Load and validate a safe site/camera config from a JSON file."""

    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SiteConfigError(f"Site config file was not found: {config_path}") from error
    except json.JSONDecodeError as error:
        raise SiteConfigError(f"Site config file is not valid JSON: {config_path}") from error

    if not isinstance(raw_config, dict):
        raise SiteConfigError("Site config must be a JSON object")

    config = dict[str, Any](raw_config)
    _validate_fields(config)

    input_type = _load_input_type(config["input_type"])

    return SiteCameraConfig(
        site_id=_load_required_text(config, "site_id"),
        camera_id=_load_required_text(config, "camera_id"),
        site_name=_load_required_text(config, "site_name"),
        public_location=_load_optional_text(config.get("public_location"), "public_location"),
        input_type=input_type,
        reference_region=_load_reference_region(config.get("reference_region")),
        privacy_notes=_load_optional_text(config.get("privacy_notes"), "privacy_notes"),
    )


def _validate_fields(config: dict[str, Any]) -> None:
    missing_fields = sorted(REQUIRED_FIELDS - config.keys())
    if missing_fields:
        joined_fields = ", ".join(missing_fields)
        raise SiteConfigError(f"Site config is missing required field(s): {joined_fields}")

    extra_fields = sorted(config.keys() - ALLOWED_FIELDS)
    if extra_fields:
        joined_fields = ", ".join(extra_fields)
        raise SiteConfigError(f"Site config has unsupported field(s): {joined_fields}")


def _load_required_text(config: dict[str, Any], field_name: str) -> str:
    value = config[field_name]
    if not isinstance(value, str) or not value.strip():
        raise SiteConfigError(f"Site config field '{field_name}' must be a non-empty string")
    return value.strip()


def _load_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SiteConfigError(f"Site config field '{field_name}' must be a non-empty string")
    return value.strip()


def _load_input_type(value: object) -> InputType:
    if value not in {"local_video", "camera_stream"}:
        raise SiteConfigError(
            "Site config field 'input_type' must be 'local_video' or 'camera_stream'"
        )
    return value


def _load_reference_region(value: object) -> ReferenceRegion | None:
    if value is None:
        return None

    if not isinstance(value, dict):
        raise SiteConfigError("Site config field 'reference_region' must be a JSON object")

    region = dict[str, Any](value)
    expected_fields = {"x", "y", "width", "height"}
    missing_fields = sorted(expected_fields - region.keys())
    if missing_fields:
        joined_fields = ", ".join(missing_fields)
        raise SiteConfigError(f"Reference region is missing required field(s): {joined_fields}")

    extra_fields = sorted(region.keys() - expected_fields)
    if extra_fields:
        joined_fields = ", ".join(extra_fields)
        raise SiteConfigError(f"Reference region has unsupported field(s): {joined_fields}")

    x = _load_region_number(region["x"], "x")
    y = _load_region_number(region["y"], "y")
    width = _load_region_number(region["width"], "width")
    height = _load_region_number(region["height"], "height")

    if x < 0 or y < 0:
        raise SiteConfigError("Reference region x and y must be 0 or greater")
    if width <= 0 or height <= 0:
        raise SiteConfigError("Reference region width and height must be greater than 0")
    if x + width > 100 or y + height > 100:
        raise SiteConfigError("Reference region must fit inside the 0-100 image area")

    return ReferenceRegion(x=x, y=y, width=width, height=height)


def _load_region_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SiteConfigError(f"Reference region field '{field_name}' must be a number")
    return float(value)

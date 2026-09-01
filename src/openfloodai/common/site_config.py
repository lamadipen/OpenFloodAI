"""Site configuration tying camera sites to external data sources."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


class SiteConfigError(ValueError):
    """Raised when site configuration cannot be loaded or is invalid."""


@dataclass(frozen=True)
class SiteConfig:
    """Configuration for a single monitored site."""

    site_id: str
    camera_id: str
    latitude: float
    longitude: float
    usgs_site_number: str | None = None
    nws_zone: str | None = None
    flood_stage_ft: float | None = None
    description: str = ""


def load_site_config(config_path: Path) -> list[SiteConfig]:
    """Load site configurations from a JSON file.

    The file must contain a JSON array of objects whose keys match the
    :class:`SiteConfig` field names.

    Raises :class:`SiteConfigError` when the file cannot be read or the
    content is not a valid site configuration list.
    """

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SiteConfigError(f"Cannot read site config file {config_path}: {exc}") from exc

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SiteConfigError(f"Invalid JSON in site config file {config_path}: {exc}") from exc

    if not isinstance(data, list):
        raise SiteConfigError(
            f"Site config file must contain a JSON array, got {type(data).__name__}"
        )

    configs: list[SiteConfig] = []
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise SiteConfigError(
                f"Entry {index} in site config must be an object, got {type(entry).__name__}"
            )
        try:
            configs.append(SiteConfig(**entry))
        except TypeError as exc:
            raise SiteConfigError(
                f"Entry {index} in site config has invalid fields: {exc}"
            ) from exc

    return configs


def save_site_config(configs: list[SiteConfig], config_path: Path) -> None:
    """Save site configurations to a JSON file.

    Creates parent directories if they do not exist.

    Raises :class:`SiteConfigError` when the file cannot be written.
    """

    data = [asdict(cfg) for cfg in configs]
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

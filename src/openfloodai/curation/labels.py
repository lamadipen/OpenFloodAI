"""Versioned, approved low / middle / high category definitions for one site (Issue #215).

Low, middle and high are NOT read from a sampling group (those depend on the requested date
range) and there are no universal flood thresholds. A site's categories exist only when a person
records, with a rationale and an approver, the numeric bands on one station's gauge, the unit and
which side of each boundary belongs to which band. A definition is never edited: a change is a new
version, and a dataset names the version it uses, so old records are never silently recategorized.
The numeric gauge reading is always kept beside the category.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openfloodai.curation.common import (
    LEVEL_CATEGORIES,
    SCHEMA_VERSION,
    CurationError,
    clean_text,
    utc_now,
)
from openfloodai.ingestion.sequence_store import atomic_write_json

DEFINITIONS_DIRNAME = "_label-definitions"
BOUNDARIES = ("upper_inclusive", "lower_inclusive")


def _site_dir(datasets_dir: Path, site_id: str) -> Path:
    cleaned = clean_text(site_id, "Site", max_length=120)
    if "/" in cleaned or "\\" in cleaned or cleaned.startswith("."):
        raise CurationError("Choose a valid site.")
    return datasets_dir / DEFINITIONS_DIRNAME / cleaned


def _number(value: object, what: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CurationError(f"{what} must be a number.")
    return float(value)


def _validate_bands(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise CurationError("Define at least one band.")
    bands: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise CurationError("Each band must be an object.")
        name = str(item.get("name", ""))
        if name not in LEVEL_CATEGORIES:
            raise CurationError(f"A band name must be one of {', '.join(LEVEL_CATEGORIES)}.")
        lower = _number(item.get("lower"), f"The lower limit of {name}")
        upper = _number(item.get("upper"), f"The upper limit of {name}")
        if lower is not None and upper is not None and not lower < upper:
            raise CurationError(f"The lower limit of {name} must be below its upper limit.")
        bands.append({"name": name, "lower": lower, "upper": upper})
    if len({b["name"] for b in bands}) != len(bands):
        raise CurationError("Each band name can be used once.")
    ordered = sorted(
        bands, key=lambda b: (b["lower"] is not None, b["lower"] if b["lower"] is not None else 0.0)
    )
    for first, second in zip(ordered, ordered[1:], strict=False):
        if first["upper"] is None or second["lower"] is None or first["upper"] > second["lower"]:
            raise CurationError("Bands must not overlap, and only the first can be open below.")
        if first["upper"] != second["lower"]:
            raise CurationError(
                f"There is a gap between {first['name']} and {second['name']}. "
                "Bands must meet at a shared boundary so every reading has one category."
            )
    return ordered


def list_definition_versions(datasets_dir: Path, site_id: str) -> list[dict[str, Any]]:
    folder = _site_dir(datasets_dir, site_id)
    if not folder.is_dir():
        return []
    versions = []
    for path in sorted(folder.glob("v*.json")):
        try:
            versions.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return versions


def get_definition(datasets_dir: Path, site_id: str, version: int) -> dict[str, Any]:
    for definition in list_definition_versions(datasets_dir, site_id):
        if definition.get("version") == version:
            return definition
    raise CurationError(f"Category definition version {version} was not found for this site.")


def create_definition(datasets_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Record a new, approved category definition as the next version for a site."""

    site_id = clean_text(payload.get("site_id"), "Site", max_length=120)
    unit = clean_text(payload.get("unit"), "Unit", max_length=20)
    station = clean_text(payload.get("station_nwis_id"), "Gauge station", max_length=40)
    boundary = str(payload.get("boundary", ""))
    if boundary not in BOUNDARIES:
        raise CurationError(
            "Say which side of each boundary belongs to the band below it or above it."
        )
    definition = {
        "schema_version": SCHEMA_VERSION,
        "site_id": site_id,
        "unit": unit,
        "station_nwis_id": station,
        "parameter_code": clean_text(
            payload.get("parameter_code", "00065"), "Parameter", max_length=10
        ),
        "datum": clean_text(payload.get("datum"), "Datum", required=False, max_length=120) or None,
        "boundary": boundary,
        "bands": _validate_bands(payload.get("bands")),
        "rationale": clean_text(payload.get("rationale"), "Source or rationale", max_length=600),
        "author": clean_text(payload.get("author"), "Author", max_length=80),
        "approved_by": clean_text(payload.get("approved_by"), "Approver", max_length=80),
        "approved_at_utc": utc_now(),
        "note": "Local site categories for dataset curation. They are not flood thresholds.",
    }
    folder = _site_dir(datasets_dir, site_id)
    folder.mkdir(parents=True, exist_ok=True)
    version = len(list_definition_versions(datasets_dir, site_id)) + 1
    definition["version"] = version
    path = folder / f"v{version:04d}.json"
    if path.exists():
        raise CurationError("That definition version already exists.")
    atomic_write_json(path, definition)
    return definition


def categorize(value: float, definition: dict[str, Any]) -> str | None:
    """The band a gauge value falls in under this definition, or None if it is in no band."""

    upper_inclusive = definition["boundary"] == "upper_inclusive"
    for band in definition["bands"]:
        lower, upper = band["lower"], band["upper"]
        above = lower is None or (value > lower if upper_inclusive else value >= lower)
        below = upper is None or (value <= upper if upper_inclusive else value < upper)
        if above and below:
            return str(band["name"])
    return None

"""The release policy: the human approvals a public dataset release depends on (Issue #207).

Nothing here is guessed. A release only includes an image when a person has recorded, with their
name:

- that the image SOURCE may be reused, under which license, with which credit text;
- the license of OpenFloodAI's OWN annotations;
- for each site, how its location may be shown and that a privacy review (faces, license plates,
  private property) was done.

Third-party or uncertain sources stay out until permission is recorded. USGS material must be
credited to the U.S. Geological Survey and must never imply endorsement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openfloodai.curation.common import CurationError, clean_text, content_id, utc_now
from openfloodai.ingestion.sequence_store import atomic_write_json

POLICY_FILENAME = "release-policy.json"
SCHEMA_VERSION = 1
LOCATION_MODES = ("generalized", "exact_approved", "omitted")
PRIVACY_CHECKS = ("faces_reviewed", "license_plates_reviewed", "private_property_reviewed")
USGS_CREDIT = "U.S. Geological Survey"


def empty_policy() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "annotation_license": None,
        "sources": {},
        "sites": {},
    }


def load_policy(path: Path) -> dict[str, Any]:
    """The saved policy, or an empty one (which approves nothing) if none exists yet."""

    if not path.is_file():
        return empty_policy()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CurationError(f"The release policy could not be read: {error}") from error
    if not isinstance(loaded, dict):
        raise CurationError("The release policy must be a JSON object.")
    return {**empty_policy(), **loaded}


def policy_digest(policy: dict[str, Any]) -> str:
    return content_id(policy, 24)


def _save(path: Path, policy: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, policy)
    return policy


def approve_source(
    path: Path,
    *,
    source_system: str,
    license_name: str,
    credit: str,
    reuse_note: str,
    approved_by: str,
) -> dict[str, Any]:
    """Record that images from this source system may be reused, with their credit text."""

    system = clean_text(source_system, "Source system", max_length=60)
    credit_text = clean_text(credit, "Credit text", max_length=300)
    if "usgs" in system.lower() and USGS_CREDIT not in credit_text:
        raise CurationError(f"USGS material must be credited to the {USGS_CREDIT}.")
    policy = load_policy(path)
    policy["sources"][system] = {
        "status": "approved",
        "license_name": clean_text(license_name, "License", max_length=120),
        "credit": credit_text,
        "reuse_note": clean_text(reuse_note, "Reuse note", max_length=400),
        "approved_by": clean_text(approved_by, "Approver", max_length=80),
        "approved_at_utc": utc_now(),
    }
    return _save(path, policy)


def approve_annotation_license(
    path: Path, *, spdx_id: str, holder: str, approved_by: str
) -> dict[str, Any]:
    policy = load_policy(path)
    policy["annotation_license"] = {
        "spdx_id": clean_text(spdx_id, "License identifier", max_length=60),
        "holder": clean_text(holder, "License holder", max_length=120),
        "approved_by": clean_text(approved_by, "Approver", max_length=80),
        "approved_at_utc": utc_now(),
    }
    return _save(path, policy)


def approve_site(
    path: Path,
    *,
    site_id: str,
    location_mode: str,
    precision_decimals: int,
    reviewed_by: str,
    checks: dict[str, bool],
    notes: str = "",
    exact_location_approved_by: str = "",
) -> dict[str, Any]:
    """Record a site's location rule and that its privacy review covered the required points."""

    site = clean_text(site_id, "Site", max_length=120)
    if location_mode not in LOCATION_MODES:
        raise CurationError(f"The location mode must be one of {', '.join(LOCATION_MODES)}.")
    if isinstance(precision_decimals, bool) or not 0 <= int(precision_decimals) <= 3:
        raise CurationError("Location precision must be 0 to 3 decimal places.")
    missing = [name for name in PRIVACY_CHECKS if checks.get(name) is not True]
    if missing:
        raise CurationError(
            "The privacy review must cover faces, license plates and private property. "
            f"Not confirmed: {', '.join(missing)}."
        )
    exact_approver = clean_text(
        exact_location_approved_by, "Exact-location approver", required=False, max_length=80
    )
    if location_mode == "exact_approved" and not exact_approver:
        raise CurationError("Showing an exact location needs a named approver.")
    policy = load_policy(path)
    policy["sites"][site] = {
        "location": {
            "mode": location_mode,
            "precision_decimals": int(precision_decimals),
            "exact_approved_by": exact_approver or None,
        },
        "privacy_review": {
            "status": "approved",
            "reviewed_by": clean_text(reviewed_by, "Reviewer", max_length=80),
            "reviewed_at_utc": utc_now(),
            "checks": {name: True for name in PRIVACY_CHECKS},
            "notes": clean_text(notes, "Notes", required=False, max_length=400),
        },
    }
    return _save(path, policy)


def source_approved(policy: dict[str, Any], source_system: object) -> bool:
    entry = policy["sources"].get(str(source_system))
    return bool(entry and entry.get("status") == "approved")


def site_approved(policy: dict[str, Any], site_id: object) -> bool:
    entry = policy["sites"].get(str(site_id))
    return bool(entry and (entry.get("privacy_review") or {}).get("status") == "approved")


def location_for(
    policy: dict[str, Any], site_id: str, latitude: float | None, longitude: float | None
) -> dict[str, Any] | None:
    """The location a release may show for a site: generalized, approved exact, or none."""

    entry = policy["sites"].get(site_id)
    if not entry or latitude is None or longitude is None:
        return None
    rule = entry["location"]
    if rule["mode"] == "omitted":
        return None
    if rule["mode"] == "exact_approved":
        return {"latitude": latitude, "longitude": longitude, "precision": "exact_approved"}
    places = int(rule["precision_decimals"])
    return {
        "latitude": round(latitude, places),
        "longitude": round(longitude, places),
        "precision": f"generalized_{places}_decimals",
    }

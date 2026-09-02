"""Fetch disaster reports from the UN ReliefWeb API.

ReliefWeb is the United Nations' humanitarian information portal.  It
aggregates situation reports, flash updates, and damage assessments from
governments, NGOs, and UN agencies worldwide.  This gives OpenFloodAI
access to authoritative on-the-ground reports about active flood disasters
-- especially valuable in regions like Nepal, Bangladesh, and Pakistan
where local sensor coverage may be sparse.

API documentation: https://apidoc.rwlabs.org/
Free, no API key required.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import uuid4

_BASE_URL = "https://api.reliefweb.int/v1"
_USER_AGENT = "OpenFloodAI/0.1.0 (open-source flood detection; github.com/openfloodai)"

_FLOOD_DISASTER_TYPES = frozenset({
    "Flood",
    "Flash Flood",
    "Storm Surge",
    "Monsoon",
    "Cyclone",
    "Tsunami",
    "Landslide",
    "Mudslide",
})


class ReliefWebError(RuntimeError):
    """Raised when ReliefWeb API data cannot be fetched or parsed."""


def fetch_flood_reports(
    *,
    country: str | None = None,
    days_back: int = 30,
    limit: int = 20,
    timeout: float = 15.0,
) -> list[dict[str, object]]:
    """Fetch recent flood-related disaster reports.

    Optionally filter by country name (e.g. "Nepal", "Bangladesh").
    Returns a list of V1 report records.
    """

    if days_back < 1:
        raise ReliefWebError("days_back must be at least 1")
    if limit < 1 or limit > 50:
        raise ReliefWebError("limit must be between 1 and 50")

    cutoff = (datetime.now(tz=UTC) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    query_payload: dict[str, object] = {
        "appname": "openfloodai",
        "preset": "latest",
        "profile": "list",
        "limit": limit,
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "date.created", "value": {"from": cutoff}},
                {
                    "field": "disaster_type.name",
                    "value": list(_FLOOD_DISASTER_TYPES),
                    "operator": "OR",
                },
            ],
        },
        "fields": {
            "include": [
                "title",
                "date.created",
                "date.original",
                "source.name",
                "country.name",
                "disaster_type.name",
                "url_alias",
                "status",
            ],
        },
        "sort": ["date.created:desc"],
    }

    if country:
        filter_block = query_payload["filter"]
        if isinstance(filter_block, dict):
            conds = filter_block.get("conditions")
            if isinstance(conds, list):
                conds.append({"field": "country.name", "value": country})

    data = _post_json(f"{_BASE_URL}/reports", query_payload, timeout=timeout)

    items = data.get("data")
    if not isinstance(items, list):
        raise ReliefWebError("ReliefWeb response missing 'data' array")

    records: list[dict[str, object]] = []
    for item in items:
        record = _build_report_record(item)
        if record is not None:
            records.append(record)

    return records


def fetch_active_disasters(
    *,
    country: str | None = None,
    days_back: int = 90,
    limit: int = 10,
    timeout: float = 15.0,
) -> list[dict[str, object]]:
    """Fetch active flood-related disasters from ReliefWeb.

    Disasters are higher-level than reports -- each disaster tracks
    a major event (e.g. "Nepal Floods - Sep 2024").
    """

    if days_back < 1:
        raise ReliefWebError("days_back must be at least 1")

    cutoff = (datetime.now(tz=UTC) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    query_payload: dict[str, object] = {
        "appname": "openfloodai",
        "preset": "latest",
        "profile": "list",
        "limit": limit,
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "date.created", "value": {"from": cutoff}},
                {"field": "type.name", "value": list(_FLOOD_DISASTER_TYPES), "operator": "OR"},
                {"field": "status", "value": "current"},
            ],
        },
        "fields": {
            "include": [
                "name",
                "date.created",
                "date.event",
                "country.name",
                "type.name",
                "status",
                "url_alias",
                "glide",
            ],
        },
        "sort": ["date.created:desc"],
    }

    if country:
        filter_block = query_payload["filter"]
        if isinstance(filter_block, dict):
            conds = filter_block.get("conditions")
            if isinstance(conds, list):
                conds.append({"field": "country.name", "value": country})

    data = _post_json(f"{_BASE_URL}/disasters", query_payload, timeout=timeout)

    items = data.get("data")
    if not isinstance(items, list):
        raise ReliefWebError("ReliefWeb response missing 'data' array")

    records: list[dict[str, object]] = []
    for item in items:
        record = _build_disaster_record(item)
        if record is not None:
            records.append(record)

    return records


def summarize_reports(reports: list[dict[str, object]]) -> dict[str, object]:
    """Summarize a list of ReliefWeb report records.

    Pure computation -- no network calls.
    """

    if not reports:
        return {
            "report_count": 0,
            "countries_affected": [],
            "disaster_types": [],
            "report_state": "CLEAR",
            "latest_report": None,
        }

    countries: set[str] = set()
    disaster_types: set[str] = set()
    latest: dict[str, object] | None = None
    latest_date = ""

    for report in reports:
        report_countries = report.get("countries")
        if isinstance(report_countries, list):
            for c in report_countries:
                if isinstance(c, str):
                    countries.add(c)

        report_types = report.get("disaster_types")
        if isinstance(report_types, list):
            for t in report_types:
                if isinstance(t, str):
                    disaster_types.add(t)

        created = str(report.get("date_created", ""))
        if created > latest_date:
            latest_date = created
            latest = report

    return {
        "report_count": len(reports),
        "countries_affected": sorted(countries),
        "disaster_types": sorted(disaster_types),
        "report_state": "ACTIVE_DISASTER" if reports else "CLEAR",
        "latest_report": {
            "title": latest.get("title") if latest else None,
            "source": latest.get("source") if latest else None,
            "date": latest.get("date_created") if latest else None,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _post_json(
    url: str,
    payload: dict[str, object],
    *,
    timeout: float,
) -> dict[str, object]:
    body_bytes = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body_bytes,
        headers={
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        raise ReliefWebError(f"ReliefWeb API returned HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ReliefWebError(f"Could not reach ReliefWeb API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ReliefWebError(f"ReliefWeb API request timed out after {timeout}s") from exc

    try:
        return json.loads(response_body)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        raise ReliefWebError("ReliefWeb API returned invalid JSON") from exc


def _build_report_record(item: object) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None

    fields = item.get("fields")
    if not isinstance(fields, dict):
        return None

    title = fields.get("title")
    if not isinstance(title, str):
        return None

    countries = _extract_name_list(fields.get("country"))
    disaster_types = _extract_name_list(fields.get("disaster_type"))
    sources = _extract_name_list(fields.get("source"))

    date_obj = fields.get("date")
    date_created = ""
    if isinstance(date_obj, dict):
        raw = date_obj.get("created")
        if isinstance(raw, str):
            date_created = raw

    return {
        "contract_version": "v1",
        "record_id": f"reliefweb-report-{uuid4()}",
        "record_type": "reliefweb_report",
        "reliefweb_id": str(item.get("id", "")),
        "title": title,
        "date_created": date_created,
        "source": sources[0] if sources else "",
        "countries": countries,
        "disaster_types": disaster_types,
        "url": str(fields.get("url_alias", "")),
    }


def _build_disaster_record(item: object) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None

    fields = item.get("fields")
    if not isinstance(fields, dict):
        return None

    name = fields.get("name")
    if not isinstance(name, str):
        return None

    countries = _extract_name_list(fields.get("country"))
    disaster_types = _extract_name_list(fields.get("type"))

    date_obj = fields.get("date")
    date_created = ""
    date_event = ""
    if isinstance(date_obj, dict):
        raw_created = date_obj.get("created")
        raw_event = date_obj.get("event")
        if isinstance(raw_created, str):
            date_created = raw_created
        if isinstance(raw_event, str):
            date_event = raw_event

    return {
        "contract_version": "v1",
        "record_id": f"reliefweb-disaster-{uuid4()}",
        "record_type": "reliefweb_disaster",
        "reliefweb_id": str(item.get("id", "")),
        "name": name,
        "date_created": date_created,
        "date_event": date_event,
        "countries": countries,
        "disaster_types": disaster_types,
        "status": str(fields.get("status", "")),
        "glide": str(fields.get("glide", "")),
        "url": str(fields.get("url_alias", "")),
    }


def _extract_name_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                names.append(name)
        elif isinstance(item, str):
            names.append(item)
    return names

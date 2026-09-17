"""Fetch and summarize USGS NWIS gage/streamflow data to enrich image-sequence runs.

A small, separate module for issue #152's "gage data enrichment" companion
to the USGS/NIMS still-image pipeline in `river_images.py`. It talks to a
different public USGS service (NWIS Instantaneous Values) and is
intentionally self-contained rather than importing `river_images.py`'s
private network helpers — same public-data trust story, same stdlib-urllib
style, its own small copy of the no-redirects/size-limit safety net.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

# USGS permanently redirects the bare "waterservices.usgs.gov" host to this
# one; request it directly so a redirect is never needed (redirects are
# refused outright by _NoRedirects for safety).
NWIS_IV_URL = "https://nwis.waterservices.usgs.gov/nwis/iv/"
PARAMETER_GAGE_HEIGHT = "00065"
PARAMETER_DISCHARGE = "00060"
PARAMETER_UNITS = {PARAMETER_GAGE_HEIGHT: "ft", PARAMETER_DISCHARGE: "ft3/s"}
PARAMETER_LABELS = {PARAMETER_GAGE_HEIGHT: "gage height", PARAMETER_DISCHARGE: "discharge"}
ALLOWED_GAGE_RELATIONSHIPS = {"same_site", "nearby", "unavailable"}
DELTA_WINDOW_HOURS = (6, 12, 24)
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 20


class GageDataError(ValueError):
    """Raised when USGS gage/streamflow data cannot be reached or read."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> Request | None:
        raise GageDataError("The USGS water-services request redirected. No data was used.")


def _fetch_json(url: str) -> Any:
    headers = {"User-Agent": "OpenFloodAI-usgs-gage-data/1.0"}
    try:
        with build_opener(_NoRedirects()).open(
            Request(url, headers=headers), timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        raise GageDataError(f"USGS water-services request failed (HTTP {error.code}).") from error
    except (URLError, OSError, HTTPException) as error:
        raise GageDataError("Could not reach USGS water-services. Try again later.") from error
    if len(data) > MAX_RESPONSE_BYTES:
        raise GageDataError("The USGS water-services response exceeded the size limit.")
    try:
        return json.loads(data)
    except ValueError as error:
        raise GageDataError("USGS water-services returned unreadable data.") from error


def yearly_windows(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Split a YYYY-MM-DD date range into whole-calendar-year windows.

    Shared shape with the image-archive listing windows in
    `river_images.py` (both chunk a multi-year request the same
    predictable way): one window per calendar year, with the first and
    last windows clipped to the requested start/end dates.
    """

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise GageDataError("end_date must be on or after start_date")

    windows: list[tuple[str, str]] = []
    year = start.year
    while year <= end.year:
        window_start = max(start, date(year, 1, 1))
        window_end = min(end, date(year, 12, 31))
        windows.append((window_start.isoformat(), window_end.isoformat()))
        year += 1
    return windows


@dataclass(frozen=True)
class GageReading:
    """One instantaneous-value reading, normalized to UTC."""

    datetime_utc: str
    value: float


@dataclass(frozen=True)
class GageSeries:
    """One parameter's readings for one site over one date range."""

    nwis_site_id: str
    parameter_code: str
    parameter_label: str
    unit: str
    used_fallback_discharge: bool
    readings: list[GageReading]
    source_url: str


def fetch_gage_readings(nwis_site_id: str, start_date: str, end_date: str) -> GageSeries:
    """Fetch gage-height readings for one site, falling back to discharge.

    Chunks the request into yearly windows (`yearly_windows`) and combines
    the results, since NWIS instantaneous-values requests are best kept to
    bounded ranges. Tries gage height (00065) first; if that parameter has
    no data at this site for this range, retries with discharge (00060)
    and marks the result as a fallback so callers never describe discharge
    as water height.
    """

    if not nwis_site_id.strip():
        raise GageDataError("nwis_site_id must be non-empty")

    for parameter_code, used_fallback in (
        (PARAMETER_GAGE_HEIGHT, False),
        (PARAMETER_DISCHARGE, True),
    ):
        readings: list[GageReading] = []
        source_url = ""
        for window_start, window_end in yearly_windows(start_date, end_date):
            query = urlencode(
                {
                    "format": "json",
                    "sites": nwis_site_id,
                    "startDT": window_start,
                    "endDT": window_end,
                    "parameterCd": parameter_code,
                }
            )
            url = f"{NWIS_IV_URL}?{query}"
            source_url = source_url or url
            payload = _fetch_json(url)
            readings.extend(_parse_time_series(payload))
        if readings:
            return GageSeries(
                nwis_site_id=nwis_site_id,
                parameter_code=parameter_code,
                parameter_label=PARAMETER_LABELS[parameter_code],
                unit=PARAMETER_UNITS[parameter_code],
                used_fallback_discharge=used_fallback,
                readings=sorted(readings, key=lambda reading: reading.datetime_utc),
                source_url=source_url,
            )
    return GageSeries(
        nwis_site_id=nwis_site_id,
        parameter_code="",
        parameter_label="unavailable",
        unit="",
        used_fallback_discharge=False,
        readings=[],
        source_url="",
    )


def _parse_time_series(payload: Any) -> list[GageReading]:
    readings: list[GageReading] = []
    try:
        time_series = payload["value"]["timeSeries"]
    except (KeyError, TypeError):
        return readings
    for series in time_series:
        try:
            values = series["values"][0]["value"]
        except (KeyError, IndexError, TypeError):
            continue
        for point in values:
            reading = _parse_reading_point(point)
            if reading is not None:
                readings.append(reading)
    return readings


def _parse_reading_point(point: Any) -> GageReading | None:
    if not isinstance(point, Mapping):
        return None
    raw_value = point.get("value")
    raw_datetime = point.get("dateTime")
    if raw_value is None or raw_datetime is None:
        return None
    try:
        numeric_value = float(raw_value)
    except (TypeError, ValueError):
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_datetime))
    except ValueError:
        return None
    return GageReading(datetime_utc=parsed.astimezone(UTC).isoformat(), value=numeric_value)


@dataclass(frozen=True)
class GageExtreme:
    """The single highest or lowest reading found, and the nearest image to it."""

    value: float
    datetime_utc: str
    nearest_image_filename: str | None
    nearest_image_captured_at_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "datetime_utc": self.datetime_utc,
            "nearest_image_filename": self.nearest_image_filename,
            "nearest_image_captured_at_utc": self.nearest_image_captured_at_utc,
        }


@dataclass(frozen=True)
class GageDelta:
    """The largest rise or fall found within one fixed time window."""

    window_hours: int
    delta_value: float
    start_datetime_utc: str
    end_datetime_utc: str
    nearest_image_filename: str | None
    nearest_image_captured_at_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_hours": self.window_hours,
            "delta_value": self.delta_value,
            "start_datetime_utc": self.start_datetime_utc,
            "end_datetime_utc": self.end_datetime_utc,
            "nearest_image_filename": self.nearest_image_filename,
            "nearest_image_captured_at_utc": self.nearest_image_captured_at_utc,
        }


@dataclass(frozen=True)
class GageReadingsSummary:
    """Everything a human or the tracker needs about one site's gage data."""

    nwis_site_id: str
    parameter_code: str
    parameter_label: str
    unit: str
    gage_relationship: str
    gage_relationship_note: str | None
    used_fallback_discharge: bool
    source_url: str
    start_date: str
    end_date: str
    point_count: int
    available: bool
    unavailable_reason: str | None
    highest: GageExtreme | None
    lowest: GageExtreme | None
    largest_increases: list[GageDelta]
    largest_decreases: list[GageDelta]

    def to_dict(self) -> dict[str, Any]:
        return {
            "nwis_site_id": self.nwis_site_id,
            "parameter_code": self.parameter_code,
            "parameter_label": self.parameter_label,
            "unit": self.unit,
            "gage_relationship": self.gage_relationship,
            "gage_relationship_note": self.gage_relationship_note,
            "used_fallback_discharge": self.used_fallback_discharge,
            "source_url": self.source_url,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "point_count": self.point_count,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "highest": self.highest.to_dict() if self.highest else None,
            "lowest": self.lowest.to_dict() if self.lowest else None,
            "largest_increases": [delta.to_dict() for delta in self.largest_increases],
            "largest_decreases": [delta.to_dict() for delta in self.largest_decreases],
        }


def summarize_gage_readings(
    *,
    nwis_site_id: str,
    start_date: str,
    end_date: str,
    gage_relationship: str,
    gage_relationship_note: str | None,
    manifest_records: Sequence[Mapping[str, Any]],
) -> GageReadingsSummary:
    """Fetch, summarize, and never raise — an unavailable summary beats a failed run."""

    if gage_relationship not in ALLOWED_GAGE_RELATIONSHIPS:
        raise GageDataError(
            f"Invalid gage_relationship: use one of {sorted(ALLOWED_GAGE_RELATIONSHIPS)}."
        )
    if gage_relationship == "nearby" and not (gage_relationship_note or "").strip():
        raise GageDataError("A nearby gage record must include a short explanation.")

    empty = GageReadingsSummary(
        nwis_site_id=nwis_site_id,
        parameter_code="",
        parameter_label="unavailable",
        unit="",
        gage_relationship=gage_relationship,
        gage_relationship_note=gage_relationship_note,
        used_fallback_discharge=False,
        source_url="",
        start_date=start_date,
        end_date=end_date,
        point_count=0,
        available=False,
        unavailable_reason=None,
        highest=None,
        lowest=None,
        largest_increases=[],
        largest_decreases=[],
    )

    if gage_relationship == "unavailable":
        return _with_reason(empty, "This site has no known matching or nearby USGS gage.")

    try:
        series = fetch_gage_readings(nwis_site_id, start_date, end_date)
    except GageDataError as error:
        return _with_reason(empty, str(error))

    if not series.readings:
        return _with_reason(
            empty, "No gage-height or discharge data was available for this site and date range."
        )

    highest_reading = max(series.readings, key=lambda reading: reading.value)
    lowest_reading = min(series.readings, key=lambda reading: reading.value)

    largest_increases = []
    largest_decreases = []
    for window_hours in DELTA_WINDOW_HOURS:
        increase, decrease = _largest_deltas(series.readings, window_hours)
        if increase is not None:
            largest_increases.append(_build_delta(window_hours, increase, manifest_records))
        if decrease is not None:
            largest_decreases.append(_build_delta(window_hours, decrease, manifest_records))

    return GageReadingsSummary(
        nwis_site_id=nwis_site_id,
        parameter_code=series.parameter_code,
        parameter_label=series.parameter_label,
        unit=series.unit,
        gage_relationship=gage_relationship,
        gage_relationship_note=gage_relationship_note,
        used_fallback_discharge=series.used_fallback_discharge,
        source_url=series.source_url,
        start_date=start_date,
        end_date=end_date,
        point_count=len(series.readings),
        available=True,
        unavailable_reason=None,
        highest=_build_extreme(highest_reading, manifest_records),
        lowest=_build_extreme(lowest_reading, manifest_records),
        largest_increases=largest_increases,
        largest_decreases=largest_decreases,
    )


def write_gauge_readings_summary(
    sequence_dir: Path,
    *,
    nwis_site_id: str,
    start_date: str,
    end_date: str,
    gage_relationship: str,
    gage_relationship_note: str | None,
    manifest_records: Sequence[Mapping[str, Any]],
) -> GageReadingsSummary:
    """Summarize gage data for one sequence and save it alongside the sequence."""

    summary = summarize_gage_readings(
        nwis_site_id=nwis_site_id,
        start_date=start_date,
        end_date=end_date,
        gage_relationship=gage_relationship,
        gage_relationship_note=gage_relationship_note,
        manifest_records=manifest_records,
    )
    (sequence_dir / "gauge-readings-summary.json").write_text(
        json.dumps(summary.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return summary


def _with_reason(summary: GageReadingsSummary, reason: str) -> GageReadingsSummary:
    return GageReadingsSummary(
        **{**summary.__dict__, "unavailable_reason": reason},
    )


@dataclass(frozen=True)
class _DeltaCandidate:
    start_datetime_utc: str
    end_datetime_utc: str
    delta_value: float


def _largest_deltas(
    readings: list[GageReading], window_hours: int
) -> tuple[_DeltaCandidate | None, _DeltaCandidate | None]:
    """Return the largest rise and the largest fall found within a window.

    `readings` must already be sorted by time. Uses a forward-only two
    -pointer scan: for each start reading, `end` advances to the last
    reading at or before `start + window_hours` — valid because both the
    start time and the window's end bound increase monotonically with the
    start index.
    """

    if len(readings) < 2:
        return None, None
    window = timedelta(hours=window_hours)
    parsed = [(datetime.fromisoformat(reading.datetime_utc), reading.value) for reading in readings]
    n = len(parsed)
    best_increase: _DeltaCandidate | None = None
    best_decrease: _DeltaCandidate | None = None
    end = 0
    for start in range(n):
        if end < start:
            end = start
        target = parsed[start][0] + window
        while end + 1 < n and parsed[end + 1][0] <= target:
            end += 1
        if end <= start:
            continue
        delta = parsed[end][1] - parsed[start][1]
        if best_increase is None or delta > best_increase.delta_value:
            best_increase = _DeltaCandidate(
                start_datetime_utc=readings[start].datetime_utc,
                end_datetime_utc=readings[end].datetime_utc,
                delta_value=delta,
            )
        if best_decrease is None or delta < best_decrease.delta_value:
            best_decrease = _DeltaCandidate(
                start_datetime_utc=readings[start].datetime_utc,
                end_datetime_utc=readings[end].datetime_utc,
                delta_value=delta,
            )
    return best_increase, best_decrease


def _nearest_image(
    manifest_records: Sequence[Mapping[str, Any]], target_datetime_utc: str
) -> tuple[str | None, str | None]:
    """Find the downloaded manifest record with the closest capture time."""

    try:
        target = datetime.fromisoformat(target_datetime_utc)
    except ValueError:
        return None, None

    best_filename: str | None = None
    best_captured_at: str | None = None
    best_diff: float | None = None
    for record in manifest_records:
        if record.get("download_status") != "downloaded":
            continue
        captured_at = record.get("captured_at_utc")
        if not captured_at:
            continue
        try:
            captured = datetime.fromisoformat(str(captured_at))
        except ValueError:
            continue
        diff = abs((captured - target).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_filename = record.get("filename")
            best_captured_at = str(captured_at)
    return best_filename, best_captured_at


def _build_extreme(
    reading: GageReading, manifest_records: Sequence[Mapping[str, Any]]
) -> GageExtreme:
    filename, captured_at = _nearest_image(manifest_records, reading.datetime_utc)
    return GageExtreme(
        value=reading.value,
        datetime_utc=reading.datetime_utc,
        nearest_image_filename=filename,
        nearest_image_captured_at_utc=captured_at,
    )


def _build_delta(
    window_hours: int,
    candidate: _DeltaCandidate,
    manifest_records: Sequence[Mapping[str, Any]],
) -> GageDelta:
    filename, captured_at = _nearest_image(manifest_records, candidate.end_datetime_utc)
    return GageDelta(
        window_hours=window_hours,
        delta_value=candidate.delta_value,
        start_datetime_utc=candidate.start_datetime_utc,
        end_datetime_utc=candidate.end_datetime_utc,
        nearest_image_filename=filename,
        nearest_image_captured_at_utc=captured_at,
    )

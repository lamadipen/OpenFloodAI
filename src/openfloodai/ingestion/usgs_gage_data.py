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
import math
from bisect import bisect_left
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from openfloodai.ingestion.sequence_store import atomic_write_json

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
# A gage reading only counts as a measurement of an image's moment when it
# is within this far (inclusive, before or after) of the image's capture
# time. Nothing farther is interpolated, carried forward, or averaged in --
# an image with no reading inside the window simply has no matched reading.
MATCH_TOLERANCE_SECONDS = 15 * 60
MATCH_POLICY = {
    "tolerance_seconds": MATCH_TOLERANCE_SECONDS,
    "inclusive": True,
    "selection": "nearest valid reading; equal distance prefers the earlier reading",
    "interpolation": "none",
    "duplicate_timestamp": "prefer approved, then provisional, then other; then lower value",
}
# USGS NWIS declares its own "no data" sentinel per series (normally this).
DEFAULT_NO_DATA_VALUE = -999999.0
QUALITY_APPROVED = "approved"
QUALITY_PROVISIONAL = "provisional"
QUALITY_NOT_REPORTED = "not_reported"
QUALITY_UNKNOWN = "unknown"
_QUALITY_RANK = {
    QUALITY_APPROVED: 0,
    QUALITY_PROVISIONAL: 1,
    QUALITY_NOT_REPORTED: 2,
    QUALITY_UNKNOWN: 2,
}
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
    # Original USGS qualifier codes (e.g. "P", "A", "e", "Ice"), kept exactly
    # as received -- quality_status below is OUR reading of them, never a
    # replacement for them.
    qualifiers: tuple[str, ...] = ()
    quality_status: str = QUALITY_NOT_REPORTED


def interpret_quality(qualifiers: Sequence[str]) -> str:
    """Interpret USGS qualifier codes without ever upgrading an unknown one.

    "P" (provisional) wins over "A" if both somehow appear -- the cautious
    reading. Any codes that are neither (e.g. "e" estimated, "Ice",
    "Eqp") are "unknown": retained, but never described as approved or OK.
    No qualifiers at all is "not_reported", which is also not approval.
    """

    if not qualifiers:
        return QUALITY_NOT_REPORTED
    if "P" in qualifiers:
        return QUALITY_PROVISIONAL
    if "A" in qualifiers:
        return QUALITY_APPROVED
    return QUALITY_UNKNOWN


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
    # Source points that were present but unusable (missing, non-numeric,
    # non-finite, declared no-data, unreadable or timezone-less timestamp).
    rejected_reading_count: int = 0


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
        rejected = 0
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
            parsed, window_rejected = _parse_time_series(payload, nwis_site_id, parameter_code)
            readings.extend(parsed)
            rejected += window_rejected
        if readings:
            return GageSeries(
                nwis_site_id=nwis_site_id,
                parameter_code=parameter_code,
                parameter_label=PARAMETER_LABELS[parameter_code],
                unit=PARAMETER_UNITS[parameter_code],
                used_fallback_discharge=used_fallback,
                readings=dedupe_readings(readings),
                source_url=source_url,
                rejected_reading_count=rejected,
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


def _parse_time_series(
    payload: Any, nwis_site_id: str, parameter_code: str
) -> tuple[list[GageReading], int]:
    """Parse one NWIS response into valid readings, counting the unusable ones.

    Only series for the requested station and parameter are read -- a
    response may also carry other sensors/parameters, and mixing gage
    height with discharge would be silently wrong. A series missing that
    identifying information entirely is still read, since the request
    itself already asked for exactly one site and parameter.
    """

    readings: list[GageReading] = []
    rejected = 0
    try:
        time_series = payload["value"]["timeSeries"]
    except (KeyError, TypeError):
        return readings, rejected
    for series in time_series:
        if not _series_matches(series, nwis_site_id, parameter_code):
            continue
        no_data_value = _series_no_data_value(series)
        try:
            values = series["values"][0]["value"]
        except (KeyError, IndexError, TypeError):
            continue
        for point in values:
            reading = _parse_reading_point(point, no_data_value)
            if reading is None:
                rejected += 1
            else:
                readings.append(reading)
    return readings, rejected


def _series_matches(series: Any, nwis_site_id: str, parameter_code: str) -> bool:
    try:
        codes = [str(entry.get("value")) for entry in series["variable"]["variableCode"]]
        if codes and parameter_code not in codes:
            return False
    except (KeyError, TypeError, AttributeError):
        pass
    try:
        site_codes = [str(entry.get("value")) for entry in series["sourceInfo"]["siteCode"]]
        if site_codes and nwis_site_id not in site_codes:
            return False
    except (KeyError, TypeError, AttributeError):
        pass
    return True


def _series_no_data_value(series: Any) -> float:
    try:
        declared = float(series["variable"]["noDataValue"])
    except (KeyError, TypeError, ValueError):
        return DEFAULT_NO_DATA_VALUE
    return declared if math.isfinite(declared) else DEFAULT_NO_DATA_VALUE


def _parse_reading_point(
    point: Any, no_data_value: float = DEFAULT_NO_DATA_VALUE
) -> GageReading | None:
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
    # float() accepts "nan"/"inf"; neither is a measurement. The series' own
    # declared no-data sentinel (e.g. -999999) is also never a real reading.
    if not math.isfinite(numeric_value) or numeric_value == no_data_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_datetime))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Without an offset the instant is ambiguous; guessing the machine's
        # local zone would silently mis-time the reading.
        return None
    raw_qualifiers = point.get("qualifiers")
    qualifiers = (
        tuple(str(code) for code in raw_qualifiers) if isinstance(raw_qualifiers, list) else ()
    )
    return GageReading(
        datetime_utc=parsed.astimezone(UTC).isoformat(),
        value=numeric_value,
        qualifiers=qualifiers,
        quality_status=interpret_quality(qualifiers),
    )


def dedupe_readings(readings: Sequence[GageReading]) -> list[GageReading]:
    """One reading per UTC instant, deterministically, sorted by time.

    Source data can repeat a timestamp (overlapping yearly windows, or two
    sensors). The kept reading is chosen by a fixed rule -- approved, then
    provisional, then anything else; then the lower value; then the
    qualifier text -- so the same input always yields the same series.
    """

    best: dict[str, GageReading] = {}
    for reading in readings:
        current = best.get(reading.datetime_utc)
        if current is None or _dedupe_key(reading) < _dedupe_key(current):
            best[reading.datetime_utc] = reading
    return sorted(best.values(), key=lambda reading: _parse_utc(reading.datetime_utc))


def _dedupe_key(reading: GageReading) -> tuple[int, float, str]:
    return (
        _QUALITY_RANK.get(reading.quality_status, 2),
        reading.value,
        ",".join(reading.qualifiers),
    )


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


@dataclass(frozen=True)
class GageMatch:
    """The outcome of matching one image timestamp to the gage readings."""

    status: str  # "matched" | "no_matching_reading" | "image_timestamp_invalid"
    reading: GageReading | None
    # Reading time minus image time, in whole seconds (negative: reading is
    # earlier). None when nothing matched.
    time_difference_seconds: int | None
    reason: str | None
    candidates_in_window: int


class GageReadingIndex:
    """Valid readings sorted by time, for repeated nearest-in-window lookups."""

    def __init__(self, readings: Sequence[GageReading]) -> None:
        ordered = dedupe_readings(readings)
        self.readings = ordered
        self._epochs = [_parse_utc(reading.datetime_utc).timestamp() for reading in ordered]

    def match(
        self, image_datetime: str, tolerance_seconds: int = MATCH_TOLERANCE_SECONDS
    ) -> GageMatch:
        """Nearest valid reading within the inclusive tolerance, else no match.

        Equal distance prefers the earlier reading. Never interpolates,
        carries a reading forward, or widens the window.
        """

        try:
            target = datetime.fromisoformat(image_datetime)
        except (TypeError, ValueError):
            return GageMatch("image_timestamp_invalid", None, None, "unreadable_image_time", 0)
        if target.tzinfo is None:
            return GageMatch("image_timestamp_invalid", None, None, "image_time_has_no_zone", 0)
        target_epoch = target.astimezone(UTC).timestamp()
        low = bisect_left(self._epochs, target_epoch - tolerance_seconds)
        best_index: int | None = None
        best_distance = 0.0
        candidates = 0
        for index in range(low, len(self._epochs)):
            if self._epochs[index] > target_epoch + tolerance_seconds:
                break
            candidates += 1
            distance = abs(self._epochs[index] - target_epoch)
            # Strict "<" keeps the earlier reading when two are equidistant,
            # since candidates are visited in time order.
            if best_index is None or distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            return GageMatch("no_matching_reading", None, None, "none_within_15_minutes", 0)
        difference = round(self._epochs[best_index] - target_epoch)
        return GageMatch("matched", self.readings[best_index], difference, None, candidates)


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

    return _build_summary_from_series(series, empty, manifest_records)


def _build_summary_from_series(
    series: GageSeries,
    empty: GageReadingsSummary,
    manifest_records: Sequence[Mapping[str, Any]],
) -> GageReadingsSummary:
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
        nwis_site_id=empty.nwis_site_id,
        parameter_code=series.parameter_code,
        parameter_label=series.parameter_label,
        unit=series.unit,
        gage_relationship=empty.gage_relationship,
        gage_relationship_note=empty.gage_relationship_note,
        used_fallback_discharge=series.used_fallback_discharge,
        source_url=series.source_url,
        start_date=empty.start_date,
        end_date=empty.end_date,
        point_count=len(series.readings),
        available=True,
        unavailable_reason=None,
        highest=_build_extreme(highest_reading, manifest_records),
        lowest=_build_extreme(lowest_reading, manifest_records),
        largest_increases=largest_increases,
        largest_decreases=largest_decreases,
    )


GAUGE_SOURCE_FILENAME = "gauge-readings.json"
GAUGE_SOURCE_SCHEMA_VERSION = 1
# Why a sequence has no usable readings. Kept distinct on purpose: a missing
# station association, an unreachable service, and an empty date range are
# three different problems and must never read as the same absence.
GAUGE_STATUS_AVAILABLE = "available"
GAUGE_STATUS_NO_STATION = "no_station_association"
GAUGE_STATUS_SERVICE_UNAVAILABLE = "service_unavailable"
GAUGE_STATUS_NO_READINGS = "no_readings_in_range"


def _association_record(
    *,
    camera_id: str | None,
    nwis_site_id: str,
    gage_relationship: str,
    gage_relationship_note: str | None,
    association_source: str | None,
    association_source_checked: str | None,
    registry_id: str | None,
) -> dict[str, Any]:
    """The USGS-provided camera-to-station link, exactly as the registry gave it."""

    return {
        "camera_id": camera_id,
        "nwis_site_id": nwis_site_id,
        "relationship": gage_relationship,
        "relationship_note": gage_relationship_note,
        "source": association_source or None,
        "source_checked": association_source_checked or None,
        "registry": registry_id or None,
    }


def write_gauge_unavailable(
    sequence_dir: Path,
    *,
    status: str,
    reason: str,
    camera_id: str | None,
    start_date: str,
    end_date: str,
    association: dict[str, Any] | None = None,
) -> None:
    """Save an explicit "no gauge evidence, and why" source file for a sequence."""

    payload = {
        "schema_version": GAUGE_SOURCE_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "retrieved_at_utc": datetime.now(tz=UTC).isoformat(),
        "camera_id": camera_id,
        "association": association,
        "parameter": None,
        "source_url": "",
        "start_date": start_date,
        "end_date": end_date,
        "rejected_reading_count": 0,
        "readings": [],
    }
    (sequence_dir / GAUGE_SOURCE_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
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
    camera_id: str | None = None,
    association_source: str | None = None,
    association_source_checked: str | None = None,
    registry_id: str | None = None,
) -> GageReadingsSummary:
    """Fetch gage data once and save the summary plus the readings themselves.

    Writes `gauge-readings-summary.json` (extremes and deltas) and
    `gauge-readings.json` (every valid reading with its USGS qualifiers,
    the station association and its source, and when it was retrieved).
    A validation run later matches images to those readings and freezes the
    result in its own folder; this sequence-level file is only the source
    that run reads from, never what a finished run displays.
    """

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
    association = _association_record(
        camera_id=camera_id,
        nwis_site_id=nwis_site_id,
        gage_relationship=gage_relationship,
        gage_relationship_note=gage_relationship_note,
        association_source=association_source,
        association_source_checked=association_source_checked,
        registry_id=registry_id,
    )

    series: GageSeries | None = None
    source_status = GAUGE_STATUS_AVAILABLE
    if gage_relationship == "unavailable":
        reason = "This site has no known matching or nearby USGS gage."
        summary = _with_reason(empty, reason)
        source_status = GAUGE_STATUS_NO_STATION
    else:
        try:
            series = fetch_gage_readings(nwis_site_id, start_date, end_date)
        except GageDataError as error:
            reason = str(error)
            summary = _with_reason(empty, reason)
            source_status = GAUGE_STATUS_SERVICE_UNAVAILABLE
        else:
            summary = _build_summary_from_series(series, empty, manifest_records)
            if not series.readings:
                source_status = GAUGE_STATUS_NO_READINGS
                reason = summary.unavailable_reason or "No readings in range."
            else:
                reason = ""

    (sequence_dir / "gauge-readings-summary.json").write_text(
        json.dumps(summary.to_dict(), indent=2) + "\n", encoding="utf-8"
    )

    if series is not None and series.readings:
        payload: dict[str, Any] = {
            "schema_version": GAUGE_SOURCE_SCHEMA_VERSION,
            "status": GAUGE_STATUS_AVAILABLE,
            "reason": None,
            "retrieved_at_utc": datetime.now(tz=UTC).isoformat(),
            "camera_id": camera_id,
            "association": association,
            "parameter": {
                "code": series.parameter_code,
                "label": series.parameter_label,
                "unit": series.unit,
                "used_fallback_discharge": series.used_fallback_discharge,
            },
            "source_url": series.source_url,
            "start_date": start_date,
            "end_date": end_date,
            "rejected_reading_count": series.rejected_reading_count,
            "readings": [
                {
                    "datetime_utc": reading.datetime_utc,
                    "value": reading.value,
                    "qualifiers": list(reading.qualifiers),
                    "quality_status": reading.quality_status,
                }
                for reading in series.readings
            ],
        }
        (sequence_dir / GAUGE_SOURCE_FILENAME).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    else:
        write_gauge_unavailable(
            sequence_dir,
            status=source_status,
            reason=reason,
            camera_id=camera_id,
            start_date=start_date,
            end_date=end_date,
            association=association,
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

    `readings` must already be sorted by time. For every reading `j`
    (as the end of a rise/fall), the largest rise ending there is
    `value[j] - min(value[i] for i in the trailing window)`, and the
    largest fall is `value[j] - max(...)` over the same window — not just
    the delta to the single farthest-back reading still in the window,
    which would miss an earlier, larger swing followed by a partial
    pullback still inside that same window. Uses the standard
    sliding-window min/max two-deque technique to keep this O(n) despite
    checking every possible pairing within each window.
    """

    if len(readings) < 2:
        return None, None
    window = timedelta(hours=window_hours)
    parsed = [(datetime.fromisoformat(reading.datetime_utc), reading.value) for reading in readings]
    n = len(parsed)
    best_increase: _DeltaCandidate | None = None
    best_decrease: _DeltaCandidate | None = None

    min_deque: deque[int] = deque()  # increasing values; front is the window's minimum.
    max_deque: deque[int] = deque()  # decreasing values; front is the window's maximum.
    left = 0
    for right in range(n):
        right_time, right_value = parsed[right]
        while parsed[left][0] < right_time - window:
            left += 1
        while min_deque and min_deque[0] < left:
            min_deque.popleft()
        while max_deque and max_deque[0] < left:
            max_deque.popleft()

        if min_deque:
            min_idx = min_deque[0]
            delta = right_value - parsed[min_idx][1]
            # A continuously falling series would otherwise report its
            # least-negative delta as a "largest increase" just because
            # nothing else was ever compared — only a genuine rise counts.
            if delta > 0 and (best_increase is None or delta > best_increase.delta_value):
                best_increase = _DeltaCandidate(
                    start_datetime_utc=readings[min_idx].datetime_utc,
                    end_datetime_utc=readings[right].datetime_utc,
                    delta_value=delta,
                )
        if max_deque:
            max_idx = max_deque[0]
            delta = right_value - parsed[max_idx][1]
            # Symmetric guard: only a genuine fall counts as a decrease.
            if delta < 0 and (best_decrease is None or delta < best_decrease.delta_value):
                best_decrease = _DeltaCandidate(
                    start_datetime_utc=readings[max_idx].datetime_utc,
                    end_datetime_utc=readings[right].datetime_utc,
                    delta_value=delta,
                )

        while min_deque and parsed[min_deque[-1]][1] >= right_value:
            min_deque.pop()
        min_deque.append(right)
        while max_deque and parsed[max_deque[-1]][1] <= right_value:
            max_deque.pop()
        max_deque.append(right)

    return best_increase, best_decrease


def _nearest_image(
    manifest_records: Sequence[Mapping[str, Any]], target_datetime_utc: str
) -> tuple[str | None, str | None]:
    """Find the downloaded image captured within the match window of a reading.

    Returns (None, None) when no image was captured within
    MATCH_TOLERANCE_SECONDS of the reading -- a peak must never be shown
    over an image from some other hour just because it was the closest one
    available. Equal distance prefers the earlier image.
    """

    try:
        target = datetime.fromisoformat(target_datetime_utc)
    except ValueError:
        return None, None
    if target.tzinfo is None:
        return None, None

    best_filename: str | None = None
    best_captured_at: str | None = None
    best_key: tuple[float, float] | None = None
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
        if captured.tzinfo is None:
            continue
        diff = abs((captured - target).total_seconds())
        if diff > MATCH_TOLERANCE_SECONDS:
            continue
        key = (diff, captured.timestamp())
        if best_key is None or key < best_key:
            best_key = key
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


# --- Per-run frozen gauge evidence -----------------------------------------

RUN_GAUGE_EVIDENCE_FILENAME = "gauge-evidence.json"
RUN_GAUGE_SCHEMA_VERSION = 1
MATCH_STATUS_NOT_AN_IMAGE = "image_not_downloaded"


def parse_gauge_source(raw: bytes) -> dict[str, Any] | None:
    """Parse already-read gauge source bytes (None if they are not a JSON object)."""

    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def load_gauge_source(sequence_dir: Path) -> dict[str, Any] | None:
    """Read a sequence's saved gauge source file, or None if none was ever saved."""

    path = sequence_dir / GAUGE_SOURCE_FILENAME
    try:
        return parse_gauge_source(path.read_bytes())
    except OSError:
        return None


def _readings_from_source(source: Mapping[str, Any]) -> list[GageReading]:
    readings: list[GageReading] = []
    raw = source.get("readings")
    if not isinstance(raw, list):
        return readings
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        value = entry.get("value")
        stamp = entry.get("datetime_utc")
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if not math.isfinite(float(value)) or not isinstance(stamp, str):
            continue
        qualifiers = entry.get("qualifiers")
        codes = tuple(str(code) for code in qualifiers) if isinstance(qualifiers, list) else ()
        readings.append(
            GageReading(
                datetime_utc=stamp,
                value=float(value),
                qualifiers=codes,
                # Re-interpreted from the saved original qualifiers, so the
                # status can never drift from what USGS actually reported.
                quality_status=interpret_quality(codes),
            )
        )
    return readings


def _reading_record(reading: GageReading, parameter: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "datetime_utc": reading.datetime_utc,
        "value": reading.value,
        "parameter_code": parameter.get("code"),
        "parameter_label": parameter.get("label"),
        "unit": parameter.get("unit"),
        "used_fallback_discharge": bool(parameter.get("used_fallback_discharge")),
        "qualifiers": list(reading.qualifiers),
        "quality_status": reading.quality_status,
    }


def build_run_gauge_evidence(
    source: Mapping[str, Any] | None,
    images: Sequence[Mapping[str, Any]],
    *,
    source_sha256: str | None,
) -> dict[str, Any]:
    """Match every image to its own gauge reading and return the record to freeze.

    `images` are this run's images, each with `filename`, `captured_at_utc`,
    `local_time`, `download_status`, `is_baseline`, and `change_score` (the
    score THIS run computed for that exact image, or None). Nothing here
    touches the network or the clock-of-the-data: a finished run's gauge
    evidence is exactly what this returns at run time, and a later download
    or corrected USGS value cannot change it.

    Every image gets a record, matched or not, so an absent reading is
    always an explicit state with a reason -- never a zero, a normal
    reading, or a quietly dropped row.
    """

    if source is None:
        return {
            "schema_version": RUN_GAUGE_SCHEMA_VERSION,
            "captured": False,
            "status": "not_captured",
            "reason": "No gauge data was saved for this image sequence when the run was made.",
            "matching_policy": MATCH_POLICY,
            "images": [_unmatched_image(image, "not_captured") for image in images],
            "peak_events": None,
        }

    status = str(source.get("status") or GAUGE_STATUS_NO_READINGS)
    parameter = source.get("parameter")
    parameter_info: Mapping[str, Any] = parameter if isinstance(parameter, Mapping) else {}
    readings = _readings_from_source(source) if status == GAUGE_STATUS_AVAILABLE else []
    index = GageReadingIndex(readings)

    image_records: list[dict[str, Any]] = []
    for image in images:
        if image.get("download_status") != "downloaded":
            image_records.append(_unmatched_image(image, MATCH_STATUS_NOT_AN_IMAGE))
            continue
        if status != GAUGE_STATUS_AVAILABLE or not index.readings:
            image_records.append(_unmatched_image(image, status, source.get("reason")))
            continue
        match = index.match(str(image.get("captured_at_utc") or ""))
        record = _unmatched_image(image, match.status, match.reason)
        record["candidates_in_window"] = match.candidates_in_window
        if match.reading is not None:
            record["reading"] = _reading_record(match.reading, parameter_info)
            record["time_difference_seconds"] = match.time_difference_seconds
        image_records.append(record)

    return {
        "schema_version": RUN_GAUGE_SCHEMA_VERSION,
        "captured": True,
        "status": status,
        "reason": source.get("reason"),
        "matching_policy": MATCH_POLICY,
        "gauge_data_retrieved_at_utc": source.get("retrieved_at_utc"),
        "source_file_sha256": source_sha256,
        "association": source.get("association"),
        "parameter": dict(parameter_info) if parameter_info else None,
        "source_url": source.get("source_url"),
        "start_date": source.get("start_date"),
        "end_date": source.get("end_date"),
        "rejected_reading_count": source.get("rejected_reading_count", 0),
        "images": image_records,
        "peak_events": _peak_events(index, image_records, parameter_info),
    }


def _unmatched_image(
    image: Mapping[str, Any], match_status: str, reason: Any = None
) -> dict[str, Any]:
    return {
        "filename": image.get("filename"),
        "captured_at_utc": image.get("captured_at_utc"),
        "local_time": image.get("local_time"),
        "is_baseline": bool(image.get("is_baseline")),
        "match_status": match_status,
        "reason": reason,
        "reading": None,
        "time_difference_seconds": None,
        "candidates_in_window": 0,
        "change_score": image.get("change_score"),
    }


def _peak_events(
    index: GageReadingIndex,
    image_records: Sequence[Mapping[str, Any]],
    parameter: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Highest and lowest reading, each with the image (if any) taken at that time.

    The reading that is the peak and the image's own nearest matched reading
    are kept as separate fields, since they can differ; an image is only
    paired when captured within the same match window as any other image,
    and its change score is only ever the one this run computed for it.
    """

    if not index.readings:
        return None
    highest = max(index.readings, key=lambda reading: reading.value)
    lowest = min(index.readings, key=lambda reading: reading.value)
    return {
        "highest": _peak_event(highest, image_records, parameter),
        "lowest": _peak_event(lowest, image_records, parameter),
    }


def _peak_event(
    reading: GageReading,
    image_records: Sequence[Mapping[str, Any]],
    parameter: Mapping[str, Any],
) -> dict[str, Any]:
    filename, captured_at = _nearest_image(
        [
            {
                "filename": record.get("filename"),
                "captured_at_utc": record.get("captured_at_utc"),
                "download_status": "downloaded"
                if record.get("match_status") != MATCH_STATUS_NOT_AN_IMAGE
                else "not_downloaded",
            }
            for record in image_records
        ],
        reading.datetime_utc,
    )
    event: dict[str, Any] = {
        "event_reading": _reading_record(reading, parameter),
        "image_filename": filename,
        "image_captured_at_utc": captured_at,
        "image_status": "matched" if filename else "no_matching_image",
        "image_matched_reading": None,
        "image_change_score": None,
        "image_change_score_status": "no_matching_image" if not filename else "not_scored_in_run",
    }
    if filename:
        for record in image_records:
            if record.get("filename") == filename:
                event["image_matched_reading"] = record.get("reading")
                score = record.get("change_score")
                if score is not None:
                    event["image_change_score"] = score
                    event["image_change_score_status"] = "scored"
                break
    return event


def merge_batch_into_gauge_source(
    sequence_dir: Path,
    *,
    series: GageSeries,
    batch_start_date: str,
    batch_end_date: str,
    association: dict[str, Any],
    manifest_records: Sequence[Mapping[str, Any]],
    gage_relationship: str,
    gage_relationship_note: str | None,
    batch_id: str,
) -> GageReadingsSummary:
    """Add one appended batch's readings to a sequence's gauge source, changing nothing old.

    Readings already in the source keep their exact saved value and qualifiers, even if
    USGS has since revised them: an earlier image's gauge evidence must not change as a
    side effect of appending later images. Only timestamps not yet present are added.
    The range widens to cover both, and the summary (extremes, rises, nearest images) is
    rebuilt from the merged readings and the whole current manifest.

    A source for a different parameter is refused (stage and discharge are never mixed).
    A missing or "unavailable" source is replaced, since there was no evidence to keep.
    """

    if series.parameter_code != PARAMETER_GAGE_HEIGHT or series.used_fallback_discharge:
        raise GageDataError("Only gauge-height readings can be added to a water-level sample.")
    existing = load_gauge_source(sequence_dir)
    kept: list[GageReading] = []
    start_date, end_date = batch_start_date, batch_end_date
    retrieved = datetime.now(tz=UTC).isoformat()
    appended: list[Any] = []
    rejected = series.rejected_reading_count
    source_url = series.source_url
    if existing is not None and existing.get("status") == GAUGE_STATUS_AVAILABLE:
        parameter = existing.get("parameter") or {}
        if parameter.get("code") != series.parameter_code:
            raise GageDataError(
                "This sequence's saved gauge data is for a different parameter, so gauge "
                "height cannot be added to it."
            )
        kept = _readings_from_source(existing)
        start_date = min(str(existing.get("start_date") or batch_start_date), batch_start_date)
        end_date = max(str(existing.get("end_date") or batch_end_date), batch_end_date)
        retrieved = str(existing.get("retrieved_at_utc") or retrieved)
        appended = list(existing.get("appended_batches") or [])
        rejected = int(existing.get("rejected_reading_count") or 0) + series.rejected_reading_count
        source_url = str(existing.get("source_url") or series.source_url)
    present = {reading.datetime_utc for reading in kept}
    added = [reading for reading in series.readings if reading.datetime_utc not in present]
    merged = dedupe_readings([*kept, *added])
    appended.append(
        {
            "batch_id": batch_id,
            "added_reading_count": len(added),
            "start_date": batch_start_date,
            "end_date": batch_end_date,
            "retrieved_at_utc": datetime.now(tz=UTC).isoformat(),
        }
    )
    payload: dict[str, Any] = {
        "schema_version": GAUGE_SOURCE_SCHEMA_VERSION,
        "status": GAUGE_STATUS_AVAILABLE,
        "reason": None,
        "retrieved_at_utc": retrieved,
        "camera_id": association.get("camera_id"),
        "association": association,
        "parameter": {
            "code": series.parameter_code,
            "label": series.parameter_label,
            "unit": series.unit,
            "used_fallback_discharge": False,
        },
        "source_url": source_url,
        "start_date": start_date,
        "end_date": end_date,
        "rejected_reading_count": rejected,
        "appended_batches": appended,
        "readings": [
            {
                "datetime_utc": reading.datetime_utc,
                "value": reading.value,
                "qualifiers": list(reading.qualifiers),
                "quality_status": reading.quality_status,
            }
            for reading in merged
        ],
    }
    merged_series = GageSeries(
        nwis_site_id=series.nwis_site_id,
        parameter_code=series.parameter_code,
        parameter_label=series.parameter_label,
        unit=series.unit,
        used_fallback_discharge=False,
        readings=merged,
        source_url=source_url,
        rejected_reading_count=rejected,
    )
    empty = GageReadingsSummary(
        nwis_site_id=series.nwis_site_id,
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
    summary = _build_summary_from_series(merged_series, empty, manifest_records)
    # The source is written first: the summary is derived from it, and a crash between the
    # two leaves a source that is still consistent (the summary is rebuilt on the next append).
    atomic_write_json(sequence_dir / GAUGE_SOURCE_FILENAME, payload)
    atomic_write_json(sequence_dir / "gauge-readings-summary.json", summary.to_dict())
    return summary

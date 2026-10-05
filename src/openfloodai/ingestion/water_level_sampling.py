"""Gauge-guided low / middle / high water-level image sampling (Issue #212 / OF-092).

Picks a small, varied set of images for human review by looking at one USGS
gauge's valid gauge-height readings for a date range, then finding archive images
within the same inclusive +/-15 minute window the run evidence uses (#208).

Low, middle, and high are RELATIVE collection groups for one station and one
date range. They are not flood thresholds, not human labels, and not machine
observations. High does not establish flooding, low does not establish a dry
river, and middle does not establish normal or safe conditions.

The policy below is deterministic: the same readings, images, and request
always give the same selection. `POLICY_VERSION` is saved with every
selection; change the number when any rule changes.

Policy `water-level-sampling-v1`
--------------------------------
Eligible readings   Valid gauge-height (00065) readings inside the requested
                    local-day range, after the same rejection and duplicate
                    rules as #208. Provisional readings stay eligible and keep
                    their qualifiers. Discharge is never used.
Group bands         Computed once from ALL eligible readings with the
                    nearest-rank method (index = ceil(q * n) - 1 on the sorted
                    values), so no interpolation:
                      low     value <= q20 and value < median
                      middle  q40 <= value <= q60
                      high    value >= q80 and value > median
                    Low and high require a strict gap from the median, so bands
                    cannot meet in a lumpy distribution.
Limited variation   If max - min is below `MIN_LEVEL_RANGE_FT`, no group is
                    filled: there is nothing meaningful to separate.
Ranking             low: lowest first. high: highest first. middle: nearest the
                    median first (the median, not the mean). Equal values go to
                    the earlier reading.
Spacing             A group never takes two readings whose local calendar dates
                    are fewer than `MIN_SPACING_DAYS` apart. This is a spacing
                    rule, NOT a claim that the picks are independent events.
Image match         The image must be within +/-15 minutes (inclusive) of the
                    motivating reading, nearest first, an equal distance going to
                    the earlier image. The window is never widened.
Re-check            The image's OWN nearest valid reading (same 15 minute rule)
                    must also fall in the group's band. Both readings are kept;
                    the group badge reflects the image's own reading.
Uniqueness          An image is never chosen twice, nor for two groups. Groups
                    are filled in the order low, middle, high.
Shortfall           A group that cannot reach the requested count is reported
                    with why. Counts are maxima, never guarantees.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from openfloodai.ingestion.river_images import (
    DEFAULT_DAYLIGHT_WINDOW_END_HOUR,
    DEFAULT_DAYLIGHT_WINDOW_START_HOUR,
    ImageSequenceCandidate,
)
from openfloodai.ingestion.usgs_gage_data import (
    MATCH_TOLERANCE_SECONDS,
    PARAMETER_GAGE_HEIGHT,
    GageMatch,
    GageReading,
    GageReadingIndex,
)

POLICY_VERSION = "water-level-sampling-v1"
GROUPS = ("low", "middle", "high")
DEFAULT_IMAGES_PER_GROUP = 3
MAX_IMAGES_PER_GROUP = 10
MIN_SPACING_DAYS = 3
MIN_LEVEL_RANGE_FT = 0.20
LOW_QUANTILE = 0.20
MIDDLE_LOW_QUANTILE = 0.40
MIDDLE_HIGH_QUANTILE = 0.60
HIGH_QUANTILE = 0.80
MAX_SKIP_EXAMPLES = 25
TIME_OF_DAY_ANY = "any"
TIME_OF_DAY_DAYTIME = "daytime"
TIME_OF_DAY_CHOICES = (TIME_OF_DAY_ANY, TIME_OF_DAY_DAYTIME)
# The same local daylight window the regular daylight sampling mode uses (inclusive).
DAYTIME_START_HOUR = DEFAULT_DAYLIGHT_WINDOW_START_HOUR
DAYTIME_END_HOUR = DEFAULT_DAYLIGHT_WINDOW_END_HOUR

SKIP_NO_IMAGE = "no_image_within_15_minutes"
SKIP_IMAGE_USED = "image_already_selected"
SKIP_IMAGE_EXCLUDED = "image_declined_by_reviewer"
SKIP_IMAGE_NO_READING = "image_has_no_matching_reading"
SKIP_IMAGE_OUTSIDE_GROUP = "image_reading_outside_group"
SKIP_SPACING = "too_close_to_a_selected_date"
SKIP_NOT_DAYTIME = "outside_daytime_window"

SHORTFALL_NO_READINGS = "no_valid_gauge_height_readings"
SHORTFALL_LIMITED_VARIATION = "limited_level_variation"
SHORTFALL_NO_ELIGIBLE = "no_reading_in_this_group"
SHORTFALL_NOT_ENOUGH = "not_enough_distinct_dates_with_images"
SHORTFALL_LOOKUP_LIMIT = "archive_lookup_limit_reached"
SHORTFALL_NO_DAYTIME = "no_daytime_reading_in_this_group"

NOTE_RELATIVE = (
    "Low, middle, and high are relative to this station and date range only. They are "
    "not flood thresholds, human labels, or machine observations."
)


class SamplingError(ValueError):
    """An invalid sampling request, or an approved sample that does not check out."""


@dataclass(frozen=True)
class LevelThresholds:
    """Group bands computed from one period's valid gauge-height readings."""

    count: int
    minimum: float
    maximum: float
    median: float
    low_max: float
    middle_min: float
    middle_max: float
    high_min: float

    @property
    def level_range(self) -> float:
        return self.maximum - self.minimum

    @property
    def limited_variation(self) -> bool:
        return self.level_range < MIN_LEVEL_RANGE_FT

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "range": self.level_range,
            "median": self.median,
            "low_at_or_below": self.low_max,
            "middle_from": self.middle_min,
            "middle_to": self.middle_max,
            "high_at_or_above": self.high_min,
            "limited_variation": self.limited_variation,
            "min_range_for_separation": MIN_LEVEL_RANGE_FT,
            "method": "nearest-rank quantiles on sorted valid readings; no interpolation",
        }


def nearest_rank(sorted_values: Sequence[float], quantile: float) -> float:
    """Nearest-rank quantile: the value at index ceil(q * n) - 1, clamped."""

    if not sorted_values:
        raise SamplingError("There are no readings to rank.")
    index = max(0, min(len(sorted_values) - 1, math.ceil(quantile * len(sorted_values)) - 1))
    return sorted_values[index]


def compute_thresholds(readings: Sequence[GageReading]) -> LevelThresholds:
    values = sorted(reading.value for reading in readings)
    if not values:
        raise SamplingError("There are no readings to rank.")
    middle = len(values) // 2
    median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    return LevelThresholds(
        count=len(values),
        minimum=values[0],
        maximum=values[-1],
        median=median,
        low_max=nearest_rank(values, LOW_QUANTILE),
        middle_min=nearest_rank(values, MIDDLE_LOW_QUANTILE),
        middle_max=nearest_rank(values, MIDDLE_HIGH_QUANTILE),
        high_min=nearest_rank(values, HIGH_QUANTILE),
    )


def group_accepts(group: str, value: float, thresholds: LevelThresholds) -> bool:
    if thresholds.limited_variation:
        return False
    if group == "low":
        return value <= thresholds.low_max and value < thresholds.median
    if group == "high":
        return value >= thresholds.high_min and value > thresholds.median
    if group == "middle":
        return thresholds.middle_min <= value <= thresholds.middle_max
    raise SamplingError(f"Unknown group: {group}")


def _epoch(value: str) -> float:
    return datetime.fromisoformat(value).astimezone(UTC).timestamp()


def _rank_key(group: str, thresholds: LevelThresholds, reading: GageReading) -> tuple[float, float]:
    when = _epoch(reading.datetime_utc)
    if group == "low":
        return (reading.value, when)
    if group == "high":
        return (-reading.value, when)
    return (abs(reading.value - thresholds.median), when)


class ImageIndex:
    """Archive images sorted by capture time, for nearest-in-window lookups."""

    def __init__(self, images: Iterable[ImageSequenceCandidate]) -> None:
        ordered = sorted(images, key=lambda image: (image.captured_utc, image.source_url))
        self.images = ordered
        self._epochs = [image.captured_utc.timestamp() for image in ordered]

    def within(
        self, reading_epoch: float, tolerance: int = MATCH_TOLERANCE_SECONDS
    ) -> list[ImageSequenceCandidate]:
        """Images within the inclusive tolerance, nearest first, earlier first on a tie."""

        low = bisect_left(self._epochs, reading_epoch - tolerance)
        found: list[tuple[float, float, ImageSequenceCandidate]] = []
        for index in range(low, len(self._epochs)):
            if self._epochs[index] > reading_epoch + tolerance:
                break
            found.append(
                (abs(self._epochs[index] - reading_epoch), self._epochs[index], self.images[index])
            )
        found.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in found]


ImageFinder = Callable[[float], list[ImageSequenceCandidate]]
"""Images within the match window of a reading's epoch, nearest first (earlier on a tie)."""


class LookupLimitReached(Exception):  # noqa: N818 -- a control-flow signal, not an error type
    """The archive finder stopped checking: too many separate days were needed."""


def as_finder(images: Sequence[ImageSequenceCandidate] | ImageFinder) -> ImageFinder:
    """Accept either a ready list of images or a lazy finder (so a big archive is never listed)."""

    if callable(images):
        return images
    return ImageIndex(images).within


def _reading_record(reading: GageReading, unit: str) -> dict[str, Any]:
    return {
        "datetime_utc": reading.datetime_utc,
        "value": reading.value,
        "unit": unit,
        "qualifiers": list(reading.qualifiers),
        "quality_status": reading.quality_status,
    }


@dataclass(frozen=True)
class SelectedSample:
    group: str
    reading: GageReading
    image: ImageSequenceCandidate
    gap_seconds: int  # motivating reading time minus image time
    image_match: GageMatch  # the image's OWN nearest valid reading
    unit: str

    @property
    def filename(self) -> str:
        return self.image.source_url.rsplit("/", 1)[-1]

    def to_dict(self) -> dict[str, Any]:
        matched = self.image_match.reading
        return {
            "group": self.group,
            "status": "selected",
            "motivating_reading": _reading_record(self.reading, self.unit),
            "image": {
                "filename": self.filename,
                "source_url": self.image.source_url,
                "captured_at_utc": self.image.captured_utc.isoformat(),
                "size_bytes": self.image.size_bytes,
            },
            "gap_seconds": self.gap_seconds,
            "image_reading": _reading_record(matched, self.unit) if matched else None,
            "image_reading_gap_seconds": self.image_match.time_difference_seconds,
            "readings_differ": bool(matched and matched.datetime_utc != self.reading.datetime_utc),
        }


@dataclass
class GroupResult:
    group: str
    requested: int
    selected: list[SelectedSample] = field(default_factory=list)
    skip_counts: dict[str, int] = field(default_factory=dict)
    skip_examples: list[dict[str, Any]] = field(default_factory=list)
    eligible_readings: int = 0
    shortfall_reason: str | None = None

    def skip(self, reason: str, reading: GageReading | None = None, unit: str = "") -> None:
        self.skip_counts[reason] = self.skip_counts.get(reason, 0) + 1
        if (
            reading is not None
            and reason != SKIP_SPACING
            and len(self.skip_examples) < MAX_SKIP_EXAMPLES
        ):
            self.skip_examples.append({"reason": reason, "reading": _reading_record(reading, unit)})

    def to_dict(self) -> dict[str, Any]:
        found = len(self.selected)
        return {
            "group": self.group,
            "requested": self.requested,
            "found": found,
            "eligible_readings": self.eligible_readings,
            "samples": [sample.to_dict() for sample in self.selected],
            "shortfall": (
                {"missing": self.requested - found, "reason": self.shortfall_reason}
                if found < self.requested
                else None
            ),
            "skipped": dict(sorted(self.skip_counts.items())),
            "skipped_examples": list(self.skip_examples),
        }


@dataclass(frozen=True)
class SelectionResult:
    groups: list[GroupResult]
    thresholds: LevelThresholds | None
    unit: str
    reading_count: int
    image_count: int | None
    time_of_day: str = TIME_OF_DAY_ANY

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": {
                "version": POLICY_VERSION,
                "min_spacing_days": MIN_SPACING_DAYS,
                "match_window_seconds": MATCH_TOLERANCE_SECONDS,
                "images_per_group_max": MAX_IMAGES_PER_GROUP,
                "time_of_day": time_of_day_description(self.time_of_day),
                "note": NOTE_RELATIVE,
            },
            "reading_count": self.reading_count,
            **({"archive_image_count": self.image_count} if self.image_count is not None else {}),
            "thresholds": self.thresholds.to_dict() if self.thresholds else None,
            "unit": self.unit,
            "groups": [group.to_dict() for group in self.groups],
        }

    def all_samples(self) -> list[SelectedSample]:
        return [sample for group in self.groups for sample in group.selected]


def validate_time_of_day(time_of_day: str) -> str:
    if time_of_day not in TIME_OF_DAY_CHOICES:
        raise SamplingError("Time of day must be 'any' or 'daytime'.")
    return time_of_day


def time_of_day_description(time_of_day: str) -> dict[str, Any]:
    daytime = time_of_day == TIME_OF_DAY_DAYTIME
    return {
        "mode": time_of_day,
        "window_local_hours": [DAYTIME_START_HOUR, DAYTIME_END_HOUR] if daytime else None,
    }


def _in_daytime(when: datetime, zone: ZoneInfo) -> bool:
    """Inside the local daylight window, ends included, by the time on the camera's clock."""

    local = when.astimezone(zone)
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    return DAYTIME_START_HOUR * 3600 <= seconds <= DAYTIME_END_HOUR * 3600


def _local_ordinal(reading: GageReading, zone: ZoneInfo) -> int:
    return datetime.fromisoformat(reading.datetime_utc).astimezone(zone).date().toordinal()


def _too_close(ordinal: int, taken: Sequence[int]) -> bool:
    return any(abs(ordinal - other) < MIN_SPACING_DAYS for other in taken)


def _evaluate(
    group: str,
    reading: GageReading,
    image: ImageSequenceCandidate,
    thresholds: LevelThresholds,
    readings: GageReadingIndex,
    unit: str,
) -> tuple[SelectedSample | None, str | None]:
    """Check one reading + image pair against the image's own nearest reading."""

    match = readings.match(image.captured_utc.isoformat())
    if match.status != "matched" or match.reading is None:
        return None, SKIP_IMAGE_NO_READING
    if not group_accepts(group, match.reading.value, thresholds):
        return None, SKIP_IMAGE_OUTSIDE_GROUP
    gap = round(_epoch(reading.datetime_utc) - image.captured_utc.timestamp())
    return SelectedSample(group, reading, image, gap, match, unit), None


def select_samples(
    readings: Sequence[GageReading],
    images: Sequence[ImageSequenceCandidate] | ImageFinder,
    *,
    groups: Sequence[str],
    images_per_group: int,
    timezone_name: str,
    unit: str = "ft",
    kept: Mapping[str, Sequence[SelectedSample]] | None = None,
    declined_images: frozenset[str] = frozenset(),
    time_of_day: str = TIME_OF_DAY_ANY,
) -> SelectionResult:
    """Choose up to `images_per_group` images for each requested group.

    `kept` holds samples a reviewer approved and wants to keep (already
    verified); they count toward the quota and the spacing rule. Images in
    `declined_images` (by file name) are never chosen. Used for replacements.
    """

    requested = [group for group in GROUPS if group in set(groups)]
    if not requested or any(group not in GROUPS for group in groups):
        raise SamplingError("Choose one or more of low, middle, and high.")
    if not 1 <= images_per_group <= MAX_IMAGES_PER_GROUP:
        raise SamplingError(f"Images per group must be from 1 to {MAX_IMAGES_PER_GROUP}.")
    validate_time_of_day(time_of_day)
    zone = ZoneInfo(timezone_name)
    kept = kept or {}
    index = GageReadingIndex(readings)
    valid = index.readings
    find_images = as_finder(images)
    image_count = None if callable(images) else len(images)
    results = [GroupResult(group, images_per_group) for group in requested]
    if not valid:
        for result in results:
            result.shortfall_reason = SHORTFALL_NO_READINGS
        return SelectionResult(results, None, unit, 0, image_count, time_of_day)
    thresholds = compute_thresholds(valid)

    used_images: set[str] = {
        sample.image.source_url for group in requested for sample in kept.get(group, ())
    }
    for result in results:
        result.selected.extend(kept.get(result.group, ())[:images_per_group])
        eligible = [
            reading for reading in valid if group_accepts(result.group, reading.value, thresholds)
        ]
        result.eligible_readings = len(eligible)
        if time_of_day == TIME_OF_DAY_DAYTIME and eligible:
            daytime = [
                r for r in eligible if _in_daytime(datetime.fromisoformat(r.datetime_utc), zone)
            ]
            outside = len(eligible) - len(daytime)
            if outside:
                result.skip_counts[SKIP_NOT_DAYTIME] = outside
            if not daytime and not thresholds.limited_variation:
                result.shortfall_reason = SHORTFALL_NO_DAYTIME
                continue
            eligible = daytime
        if thresholds.limited_variation:
            result.shortfall_reason = SHORTFALL_LIMITED_VARIATION
            result.selected.clear()
            continue
        if not eligible:
            result.shortfall_reason = SHORTFALL_NO_ELIGIBLE
            continue
        taken = [_local_ordinal(sample.reading, zone) for sample in result.selected]
        for reading in sorted(eligible, key=lambda r: _rank_key(result.group, thresholds, r)):
            if len(result.selected) >= images_per_group:
                break
            ordinal = _local_ordinal(reading, zone)
            if _too_close(ordinal, taken):
                result.skip(SKIP_SPACING)
                continue
            try:
                nearby = find_images(_epoch(reading.datetime_utc))
            except LookupLimitReached:
                result.shortfall_reason = SHORTFALL_LOOKUP_LIMIT
                break
            if not nearby:
                result.skip(SKIP_NO_IMAGE, reading, unit)
                continue
            chosen: SelectedSample | None = None
            last_reason = SKIP_NO_IMAGE
            for image in nearby:
                name = image.source_url.rsplit("/", 1)[-1]
                if name in declined_images:
                    last_reason = SKIP_IMAGE_EXCLUDED
                    continue
                if image.source_url in used_images:
                    last_reason = SKIP_IMAGE_USED
                    continue
                if time_of_day == TIME_OF_DAY_DAYTIME and not _in_daytime(image.captured_utc, zone):
                    last_reason = SKIP_NOT_DAYTIME
                    continue
                sample, reason = _evaluate(result.group, reading, image, thresholds, index, unit)
                if sample is not None:
                    chosen = sample
                    break
                last_reason = reason or last_reason
            if chosen is None:
                result.skip(last_reason, reading, unit)
                continue
            result.selected.append(chosen)
            used_images.add(chosen.image.source_url)
            taken.append(ordinal)
        if len(result.selected) < images_per_group and result.shortfall_reason is None:
            result.shortfall_reason = SHORTFALL_NOT_ENOUGH
    return SelectionResult(results, thresholds, unit, len(valid), image_count, time_of_day)


def validate_approved_against_request(
    approved: Sequence[Mapping[str, str]], groups: Sequence[str], images_per_group: int
) -> None:
    """Approved samples must fit the request they claim to answer.

    Every item's group must be one that was asked for, no group may exceed the
    requested count, and the request itself must be valid. Checked before any
    network call, so a changed form can never download a stale selection.
    """

    if not groups or any(group not in GROUPS for group in groups):
        raise SamplingError("Choose one or more of low, middle, and high.")
    if not 1 <= images_per_group <= MAX_IMAGES_PER_GROUP:
        raise SamplingError(f"Images per group must be from 1 to {MAX_IMAGES_PER_GROUP}.")
    counts: dict[str, int] = {}
    for item in approved:
        group = str(item.get("group", ""))
        if group not in groups:
            raise SamplingError(
                f"An approved sample is in the {group or 'unknown'} group, which was not "
                "requested. Run Find samples again."
            )
        counts[group] = counts.get(group, 0) + 1
    for group, count in counts.items():
        if count > images_per_group:
            raise SamplingError(
                f"{count} {group} samples were approved but {images_per_group} were requested. "
                "Run Find samples again."
            )


def verify_approved(
    approved: Sequence[Mapping[str, str]],
    readings: Sequence[GageReading],
    images: Sequence[ImageSequenceCandidate] | ImageFinder,
    *,
    timezone_name: str,
    unit: str = "ft",
    time_of_day: str = TIME_OF_DAY_ANY,
) -> list[SelectedSample]:
    """Re-derive approved samples from fresh data; never trust the browser's copy.

    Each item names only `group`, the motivating reading's `reading_datetime_utc`,
    and the image's `filename`. Everything else (values, gaps, qualifiers) is
    recomputed here. An item that no longer qualifies raises `SamplingError`.
    """

    index = GageReadingIndex(readings)
    if not index.readings:
        raise SamplingError("There are no valid gauge-height readings to verify against.")
    thresholds = compute_thresholds(index.readings)
    by_time = {reading.datetime_utc: reading for reading in index.readings}
    find_images = as_finder(images)
    validate_time_of_day(time_of_day)
    zone = ZoneInfo(timezone_name)
    verified: list[SelectedSample] = []
    seen_images: set[str] = set()
    taken: dict[str, list[int]] = {}
    for item in approved:
        group = str(item.get("group", ""))
        if group not in GROUPS:
            raise SamplingError(f"Unknown group: {group!r}.")
        reading = by_time.get(str(item.get("reading_datetime_utc", "")))
        if reading is None:
            raise SamplingError("An approved sample no longer matches the gauge or image data.")
        try:
            nearby = find_images(_epoch(reading.datetime_utc))
        except LookupLimitReached as error:
            raise SamplingError("Too many separate days to verify against the archive.") from error
        wanted = str(item.get("filename", ""))
        image = next((i for i in nearby if i.source_url.rsplit("/", 1)[-1] == wanted), None)
        if image is None:
            raise SamplingError(
                "An approved image is not in the archive within 15 minutes of its reading."
            )
        if not group_accepts(group, reading.value, thresholds):
            raise SamplingError(f"A reading no longer belongs to the {group} group.")
        if time_of_day == TIME_OF_DAY_DAYTIME and not (
            _in_daytime(datetime.fromisoformat(reading.datetime_utc), zone)
            and _in_daytime(image.captured_utc, zone)
        ):
            raise SamplingError("An approved sample is outside the daytime window requested.")
        if image.source_url in seen_images:
            raise SamplingError("The same image was approved more than once.")
        sample, reason = _evaluate(group, reading, image, thresholds, index, unit)
        if sample is None:
            raise SamplingError(f"An approved image failed the group re-check ({reason}).")
        ordinal = _local_ordinal(reading, zone)
        if _too_close(ordinal, taken.setdefault(group, [])):
            raise SamplingError(f"Two approved {group} samples are too close in date.")
        taken[group].append(ordinal)
        seen_images.add(image.source_url)
        verified.append(sample)
    return verified


def water_level_unavailable(parameter_code: str, used_fallback_discharge: bool) -> str | None:
    """Why water-level sampling cannot be used for this gauge series, or None if it can."""

    if parameter_code == PARAMETER_GAGE_HEIGHT and not used_fallback_discharge:
        return None
    if used_fallback_discharge:
        return (
            "This station reports flow (discharge) but no gauge height for this period. "
            "Water-level sampling needs gauge height, so it is unavailable; flow is never "
            "used in its place."
        )
    return "No valid gauge-height readings were found for this station and period."

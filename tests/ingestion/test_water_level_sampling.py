"""Water-level sampling policy on synthetic gauge series (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from openfloodai.ingestion import water_level_sampling as wls
from openfloodai.ingestion.river_images import ImageSequenceCandidate
from openfloodai.ingestion.usgs_gage_data import GageReading, interpret_quality

TZ = "America/Denver"


def reading(when: datetime, value: float, quals: tuple[str, ...] = ("A",)) -> GageReading:
    return GageReading(when.isoformat(), value, quals, interpret_quality(quals))


def image(when: datetime) -> ImageSequenceCandidate:
    stamp = when.strftime("%Y-%m-%dT%H-%M-%SZ")
    return ImageSequenceCandidate(f"https://example.test/720/cam/cam___{stamp}.jpg", when, 1000)


def day(n: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 3, 1, hour, minute, tzinfo=UTC) + timedelta(days=n - 1)


def daily(values: dict[int, float]) -> list[GageReading]:
    return [reading(day(d), v) for d, v in values.items()]


def ramp() -> tuple[list[GageReading], list[ImageSequenceCandidate]]:
    """Day n has gauge height n ft (n = 1..60); one image five minutes after each reading."""

    readings = daily({d: float(d) for d in range(1, 61)})
    images = [image(day(d, minute=5)) for d in range(1, 61)]
    return readings, images


def picked(result: wls.SelectionResult, group: str) -> list[int]:
    found = next(g for g in result.groups if g.group == group)
    return [int(s.reading.value) for s in found.selected]


def test_thresholds_use_nearest_rank_and_the_true_median() -> None:
    readings, _ = ramp()
    t = wls.compute_thresholds(readings)

    assert (t.minimum, t.maximum, t.count) == (1.0, 60.0, 60)
    assert t.median == 30.5  # even count: the two middle values averaged
    assert t.low_max == 12.0 and t.high_min == 48.0
    assert (t.middle_min, t.middle_max) == (24.0, 36.0)
    assert wls.compute_thresholds(daily({1: 1, 2: 9, 3: 5})).median == 5.0  # odd count
    assert (
        wls.nearest_rank([1, 2, 3, 4, 5], 0.2) == 1.0
        and wls.nearest_rank([1, 2, 3, 4, 5], 1.0) == 5.0
    )


def test_low_and_high_rank_from_their_own_end_and_keep_dates_apart() -> None:
    readings, images = ramp()

    result = wls.select_samples(
        readings, images, groups=["low", "high"], images_per_group=3, timezone_name=TZ
    )

    # lowest first with a 3-day minimum spacing: 1, 4, 7 (2 and 3 sit on the same trough)
    assert picked(result, "low") == [1, 4, 7]
    assert picked(result, "high") == [60, 57, 54]


def test_middle_is_centred_on_the_median_with_ties_going_to_the_earlier_reading() -> None:
    readings, images = ramp()

    result = wls.select_samples(
        readings, images, groups=["middle"], images_per_group=3, timezone_name=TZ
    )

    # median 30.5: 30 and 31 tie (earlier wins); then the spacing rule skips 31, 29, 32, 28
    assert picked(result, "middle") == [30, 33, 27]


def test_middle_follows_the_median_not_the_arithmetic_mean() -> None:
    # A few huge floods pull the mean far above the median.
    values = {d: float(d) for d in range(1, 41)}
    values.update({41: 500.0, 42: 600.0, 43: 700.0, 44: 800.0})
    readings = daily(values)
    images = [image(day(d, minute=5)) for d in values]
    thresholds = wls.compute_thresholds(readings)
    mean = sum(r.value for r in readings) / len(readings)
    assert thresholds.median < 25 < mean

    result = wls.select_samples(
        readings, images, groups=["middle"], images_per_group=1, timezone_name=TZ
    )

    assert abs(picked(result, "middle")[0] - thresholds.median) <= 1


def test_selection_is_deterministic_and_input_order_does_not_matter() -> None:
    readings, images = ramp()
    forward = wls.select_samples(
        readings, images, groups=list(wls.GROUPS), images_per_group=3, timezone_name=TZ
    )
    shuffled = wls.select_samples(
        list(reversed(readings)),
        list(reversed(images)),
        groups=list(wls.GROUPS),
        images_per_group=3,
        timezone_name=TZ,
    )

    assert forward.to_dict() == shuffled.to_dict()


def test_equal_readings_are_ordered_by_time() -> None:
    values = {d: 10.0 for d in range(1, 21)}
    values.update({d: float(d) for d in range(21, 31)})  # plateau of 10.0 then a rise
    values[2] = 1.0
    readings = daily(values)
    images = [image(day(d, minute=5)) for d in values]

    result = wls.select_samples(
        readings, images, groups=["low"], images_per_group=2, timezone_name=TZ
    )

    assert picked(result, "low")[0] == 1  # the single lowest value first
    chosen = [
        s.reading.datetime_utc for s in next(g for g in result.groups if g.group == "low").selected
    ]
    assert chosen == sorted(chosen)


def test_adjacent_readings_on_one_peak_cannot_fill_the_quota() -> None:
    # Hourly readings across one peak day, plus a quiet baseline elsewhere.
    readings = daily({d: float(d % 5) for d in range(1, 31)})
    peak_day = day(12)
    readings += [reading(peak_day + timedelta(hours=h - 12), 100.0 + h) for h in range(0, 24)]
    images = [
        image(r_time)
        for r_time in (
            datetime.fromisoformat(r.datetime_utc) + timedelta(minutes=2) for r in readings
        )
    ]

    result = wls.select_samples(
        readings, images, groups=["high"], images_per_group=3, timezone_name=TZ
    )

    high = next(g for g in result.groups if g.group == "high")
    assert len(high.selected) == 1  # all the peak-day readings are one date
    assert high.shortfall_reason == wls.SHORTFALL_NOT_ENOUGH
    assert high.skip_counts[wls.SKIP_SPACING] >= 10


def test_spacing_counts_local_calendar_days_not_utc_days() -> None:
    base = daily({d: float(d) for d in range(1, 31)})
    # 2026-06 is MDT (UTC-6). A is 23:59 local Jun 9; B is 00:00 local Jun 12: 3 local days apart
    # but only 2 UTC days apart. Both are the highest readings of the series.
    a = reading(datetime(2026, 6, 10, 5, 59, tzinfo=UTC), 1000.0)
    b = reading(datetime(2026, 6, 12, 6, 0, tzinfo=UTC), 900.0)
    readings = [*base, a, b]
    images = [
        *[image(day(d, minute=5)) for d in range(1, 31)],
        image(datetime(2026, 6, 10, 6, 1, tzinfo=UTC)),
        image(datetime(2026, 6, 12, 6, 1, tzinfo=UTC)),
    ]

    result = wls.select_samples(
        readings, images, groups=["high"], images_per_group=2, timezone_name=TZ
    )

    assert picked(result, "high") == [1000, 900]


def test_fifteen_minutes_inclusive_and_never_widened() -> None:
    readings, _ = ramp()
    top = day(60)
    for offset_seconds, expected in ((900, True), (901, False), (-900, True), (-901, False)):
        images = [image(day(d, minute=5)) for d in range(1, 60)] + [
            image(top + timedelta(seconds=offset_seconds))
        ]
        result = wls.select_samples(
            readings, images, groups=["high"], images_per_group=1, timezone_name=TZ
        )
        samples = next(g for g in result.groups if g.group == "high").selected
        assert (samples[0].reading.value == 60.0) is expected, offset_seconds


def test_the_window_is_correct_across_a_daylight_saving_change() -> None:
    # US spring-forward 2026-03-08: 09:00Z is 02:00 MST -> 03:00 MDT.
    when = datetime(2026, 3, 8, 9, 5, tzinfo=UTC)
    readings = daily({d: float(d) for d in range(1, 11)}) + [reading(when, 99.0)]
    near = [image(day(d, minute=5)) for d in range(1, 11)]

    inside = wls.select_samples(
        readings,
        [*near, image(when - timedelta(minutes=15))],
        groups=["high"],
        images_per_group=1,
        timezone_name=TZ,
    )
    outside = wls.select_samples(
        readings,
        [*near, image(when - timedelta(minutes=16))],
        groups=["high"],
        images_per_group=1,
        timezone_name=TZ,
    )

    assert picked(inside, "high") == [99]
    assert next(g for g in inside.groups).selected[0].gap_seconds == 900
    assert picked(outside, "high") != [99]


def test_a_missing_image_moves_to_the_next_eligible_candidate_not_a_distant_image() -> None:
    readings, images = ramp()
    images = [
        i for i in images if i.captured_utc.date() != day(60).date()
    ]  # no image for the top reading
    images.append(image(day(60) + timedelta(hours=5)))  # an image hours away must not be used

    result = wls.select_samples(
        readings, images, groups=["high"], images_per_group=2, timezone_name=TZ
    )

    high = next(g for g in result.groups if g.group == "high")
    assert [int(s.reading.value) for s in high.selected] == [59, 56]
    assert high.skip_counts[wls.SKIP_NO_IMAGE] >= 1
    assert all(abs(s.gap_seconds) <= 900 for s in high.selected)


def test_an_image_is_never_chosen_twice_or_for_two_groups() -> None:
    readings, images = ramp()
    # A middle-band reading (30.5, the median) sits 10 minutes after day 1's low reading, so
    # both are within 15 minutes of day 1's single image. Groups fill in the order low, middle.
    readings.append(reading(day(1, minute=10), 30.5))

    result = wls.select_samples(
        readings, images, groups=["low", "middle"], images_per_group=1, timezone_name=TZ
    )

    low = next(g for g in result.groups if g.group == "low")
    middle = next(g for g in result.groups if g.group == "middle")
    assert low.selected[0].filename == images[0].source_url.rsplit("/", 1)[-1]
    assert middle.skip_counts[wls.SKIP_IMAGE_USED] >= 1
    names = [s.filename for s in result.all_samples()]
    assert len(names) == len(set(names)) == 2


def test_the_image_reading_is_rechecked_and_both_readings_are_kept() -> None:
    # Reading 60 motivates the pick, but a closer reading exists to the image.
    readings, images = ramp()
    near_reading = reading(day(60, minute=13), 59.5)
    readings.append(near_reading)
    images = [i for i in images if i.captured_utc != day(60, minute=5)] + [
        image(day(60, minute=14))
    ]

    result = wls.select_samples(
        readings, images, groups=["high"], images_per_group=1, timezone_name=TZ
    )
    sample = next(g for g in result.groups if g.group == "high").selected[0]
    record = sample.to_dict()

    assert record["motivating_reading"]["value"] == 60.0
    assert record["image_reading"]["value"] == 59.5  # the image's OWN nearest reading
    assert record["readings_differ"] is True
    assert record["gap_seconds"] == -840 and record["image_reading_gap_seconds"] == -60


def test_a_pick_whose_own_reading_falls_outside_the_group_is_skipped_and_explained() -> None:
    readings, images = ramp()
    # Day 60's image is one minute after a LOW reading, so its own nearest reading is low:
    # a "high" badge would misrepresent it, even though the motivating reading (60) is high.
    readings.append(reading(day(60, minute=4), 1.0))

    result = wls.select_samples(
        readings, images, groups=["high"], images_per_group=1, timezone_name=TZ
    )

    high = next(g for g in result.groups if g.group == "high")
    assert high.selected[0].reading.value != 60.0
    assert wls.SKIP_IMAGE_OUTSIDE_GROUP in high.skip_counts


def test_provisional_readings_stay_visible() -> None:
    readings, images = ramp()
    readings = [
        reading(datetime.fromisoformat(r.datetime_utc), r.value, ("P",)) if r.value == 60.0 else r
        for r in readings
    ]

    result = wls.select_samples(
        readings, images, groups=["high"], images_per_group=1, timezone_name=TZ
    )
    record = next(g for g in result.groups).selected[0].to_dict()

    assert record["motivating_reading"]["quality_status"] == "provisional"
    assert record["motivating_reading"]["qualifiers"] == ["P"]
    assert record["image_reading"]["quality_status"] == "provisional"


def test_a_flat_series_reports_limited_variation_instead_of_inventing_groups() -> None:
    readings = daily({d: 5.0 + (0.01 if d % 2 else 0.0) for d in range(1, 31)})
    images = [image(day(d, minute=5)) for d in range(1, 31)]

    result = wls.select_samples(
        readings, images, groups=list(wls.GROUPS), images_per_group=3, timezone_name=TZ
    )

    assert result.thresholds is not None and result.thresholds.limited_variation
    for group in result.groups:
        assert group.selected == []
        assert group.shortfall_reason == wls.SHORTFALL_LIMITED_VARIATION


def test_too_few_distinct_dates_is_a_shortfall_not_padding() -> None:
    readings = daily({d: float(d) for d in range(1, 9)})
    images = [image(day(d, minute=5)) for d in range(1, 9)]

    result = wls.select_samples(
        readings, images, groups=["high"], images_per_group=5, timezone_name=TZ
    )

    high = next(g for g in result.groups if g.group == "high")
    assert 0 < len(high.selected) < 5
    assert high.shortfall_reason == wls.SHORTFALL_NOT_ENOUGH
    assert high.to_dict()["shortfall"]["missing"] == 5 - len(high.selected)


def test_no_readings_and_discharge_only_are_clear_states() -> None:
    result = wls.select_samples(
        [], [image(day(1))], groups=["low"], images_per_group=2, timezone_name=TZ
    )
    assert (
        result.groups[0].shortfall_reason == wls.SHORTFALL_NO_READINGS and result.thresholds is None
    )

    assert wls.water_level_unavailable("00065", False) is None
    message = wls.water_level_unavailable("00060", True)
    assert message is not None and "discharge" in message and "never" in message
    assert wls.water_level_unavailable("", False) is not None


def test_request_bounds_and_groups_are_validated() -> None:
    readings, images = ramp()
    for kwargs in (
        {"groups": [], "images_per_group": 3},
        {"groups": ["extreme"], "images_per_group": 3},
        {"groups": ["low"], "images_per_group": 0},
        {"groups": ["low"], "images_per_group": wls.MAX_IMAGES_PER_GROUP + 1},
    ):
        with pytest.raises(wls.SamplingError):
            wls.select_samples(readings, images, timezone_name=TZ, **kwargs)  # type: ignore[arg-type]
    subset = wls.select_samples(
        readings, images, groups=["high"], images_per_group=4, timezone_name=TZ
    )
    assert [g.group for g in subset.groups] == ["high"] and len(subset.groups[0].selected) == 4


def test_a_replacement_keeps_approved_samples_and_still_meets_group_and_spacing_rules() -> None:
    readings, images = ramp()
    first = wls.select_samples(
        readings, images, groups=["high"], images_per_group=3, timezone_name=TZ
    )
    chosen = next(g for g in first.groups).selected  # days 60, 57, 54
    kept = {"high": chosen[:2]}
    declined = frozenset({chosen[2].filename})

    redo = wls.select_samples(
        readings,
        images,
        groups=["high"],
        images_per_group=3,
        timezone_name=TZ,
        kept=kept,
        declined_images=declined,
    )

    high = next(g for g in redo.groups)
    assert [int(s.reading.value) for s in high.selected[:2]] == [60, 57]
    replacement = high.selected[2]
    assert replacement.filename != chosen[2].filename
    # 59, 58, 56 and 55 sit too close to a kept date and 54 was declined, so 53 is next
    assert replacement.reading.value == 53.0
    days_taken = [int(s.reading.value) for s in high.selected]
    assert all(
        abs(a - b) >= wls.MIN_SPACING_DAYS
        for i, a in enumerate(days_taken)
        for b in days_taken[i + 1 :]
    )


def verified(
    readings: list[GageReading], images: list[ImageSequenceCandidate], items: list[dict[str, str]]
) -> list[wls.SelectedSample]:
    return wls.verify_approved(items, readings, images, timezone_name=TZ)


def test_approved_samples_are_recomputed_from_fresh_data() -> None:
    readings, images = ramp()
    top = readings[-1]
    item = {
        "group": "high",
        "reading_datetime_utc": top.datetime_utc,
        "filename": images[-1].source_url.rsplit("/", 1)[-1],
    }

    [sample] = verified(readings, images, [item])

    assert sample.reading.value == 60.0 and sample.gap_seconds == -300


@pytest.mark.parametrize(
    "case",
    ["wrong_group", "unknown_reading", "unknown_image", "far_image", "duplicate", "too_close"],
)
def test_approved_samples_that_no_longer_qualify_are_rejected(case: str) -> None:
    readings, images = ramp()
    by_day = {int(r.value): r for r in readings}

    def name(d: int) -> str:
        return images[d - 1].source_url.rsplit("/", 1)[-1]

    good = {"group": "high", "reading_datetime_utc": by_day[60].datetime_utc, "filename": name(60)}
    items: list[dict[str, str]]
    if case == "wrong_group":
        items = [{**good, "group": "low"}]
    elif case == "unknown_reading":
        items = [{**good, "reading_datetime_utc": "2030-01-01T00:00:00+00:00"}]
    elif case == "unknown_image":
        items = [{**good, "filename": "nope.jpg"}]
    elif case == "far_image":
        items = [{**good, "filename": name(59)}]
    elif case == "duplicate":
        items = [good, good]
    else:
        items = [
            good,
            {
                "group": "high",
                "reading_datetime_utc": by_day[59].datetime_utc,
                "filename": name(59),
            },
        ]

    with pytest.raises(wls.SamplingError):
        verified(readings, images, items)


def test_a_lazy_image_finder_gives_the_same_picks_as_a_full_image_list() -> None:
    readings, images = ramp()
    kwargs = {"groups": list(wls.GROUPS), "images_per_group": 3, "timezone_name": TZ}

    eager = wls.select_samples(readings, images, **kwargs)  # type: ignore[arg-type]
    lazy = wls.select_samples(readings, wls.ImageIndex(images).within, **kwargs)  # type: ignore[arg-type]

    assert [s.to_dict() for s in lazy.all_samples()] == [s.to_dict() for s in eager.all_samples()]
    assert "archive_image_count" in eager.to_dict() and "archive_image_count" not in lazy.to_dict()


def ramp_at(hour: int) -> tuple[list[GageReading], list[ImageSequenceCandidate]]:
    """Like `ramp()`, but every reading is at `hour`:00 UTC with an image 5 minutes later."""

    readings = [reading(day(d, hour=hour), float(d)) for d in range(1, 61)]
    images = [image(day(d, hour=hour, minute=5)) for d in range(1, 61)]
    return readings, images


def test_any_time_of_day_is_the_default_and_unchanged() -> None:
    readings, images = ramp()  # 12:00 UTC is about 5-6 a.m. local: not daytime, still allowed

    default = wls.select_samples(
        readings, images, groups=["high"], images_per_group=3, timezone_name=TZ
    )
    explicit = wls.select_samples(
        readings, images, groups=["high"], images_per_group=3, timezone_name=TZ, time_of_day="any"
    )

    assert picked(default, "high") == [60, 57, 54] == picked(explicit, "high")
    assert default.to_dict()["policy"]["time_of_day"] == {"mode": "any", "window_local_hours": None}


def test_daytime_only_uses_the_local_daylight_window() -> None:
    readings, images = ramp_at(18)  # 18:00 UTC is 11:00 or 12:00 local (MDT/MST): daytime

    result = wls.select_samples(
        readings,
        images,
        groups=["high"],
        images_per_group=3,
        timezone_name=TZ,
        time_of_day="daytime",
    )

    assert picked(result, "high") == [60, 57, 54]
    assert result.to_dict()["policy"]["time_of_day"]["window_local_hours"] == [10, 14]


def test_daytime_only_skips_night_readings_and_says_why() -> None:
    # Values 51-60 are read at 12:00 UTC (early morning local); 1-50 at 18:00 UTC (daytime local).
    readings = [reading(day(d, hour=18 if d <= 50 else 12), float(d)) for d in range(1, 61)]
    images = [image(day(d, hour=18 if d <= 50 else 12, minute=5)) for d in range(1, 61)]

    result = wls.select_samples(
        readings,
        images,
        groups=["high"],
        images_per_group=2,
        timezone_name=TZ,
        time_of_day="daytime",
    )

    high = result.groups[0]
    # The band is still set by ALL readings (high is 48 and up); only daytime ones are used.
    assert picked(result, "high") == [50]
    assert high.skip_counts[wls.SKIP_NOT_DAYTIME] == 10  # readings 51..60
    assert high.shortfall_reason == wls.SHORTFALL_NOT_ENOUGH


def test_a_group_with_no_daytime_reading_is_a_shortfall_not_a_night_time_pick() -> None:
    readings, images = ramp()  # all early morning local time

    result = wls.select_samples(
        readings,
        images,
        groups=["high"],
        images_per_group=3,
        timezone_name=TZ,
        time_of_day="daytime",
    )

    high = result.groups[0]
    assert high.selected == [] and high.shortfall_reason == wls.SHORTFALL_NO_DAYTIME
    assert high.skip_counts[wls.SKIP_NOT_DAYTIME] == high.eligible_readings


def test_the_daytime_window_ends_are_included_and_dst_is_on_the_local_clock() -> None:
    zone = ZoneInfo(TZ)
    # 2026-03-07 is MST (UTC-7); 2026-03-09 is MDT (UTC-6).
    assert wls._in_daytime(datetime(2026, 3, 7, 17, 0, tzinfo=UTC), zone)  # 10:00 MST
    assert not wls._in_daytime(datetime(2026, 3, 7, 16, 59, 59, tzinfo=UTC), zone)  # 09:59:59
    assert wls._in_daytime(datetime(2026, 3, 9, 16, 0, tzinfo=UTC), zone)  # 10:00 MDT
    assert not wls._in_daytime(datetime(2026, 3, 7, 16, 0, tzinfo=UTC), zone)  # 09:00 MST
    assert wls._in_daytime(datetime(2026, 3, 9, 20, 0, tzinfo=UTC), zone)  # 14:00 MDT
    assert not wls._in_daytime(datetime(2026, 3, 9, 20, 0, 1, tzinfo=UTC), zone)  # 14:00:01


def test_a_daytime_reading_whose_image_falls_just_outside_the_window_is_skipped() -> None:
    readings = [reading(day(d, hour=18), float(d)) for d in range(1, 31)]
    images = [image(day(d, hour=18, minute=5)) for d in range(1, 31)]
    late = reading(datetime(2026, 4, 5, 19, 55, tzinfo=UTC), 99.0)  # 13:55 MDT: daytime
    readings.append(late)
    images.append(image(datetime(2026, 4, 5, 20, 10, tzinfo=UTC)))  # 14:10 MDT: outside the window

    result = wls.select_samples(
        readings,
        images,
        groups=["high"],
        images_per_group=1,
        timezone_name=TZ,
        time_of_day="daytime",
    )
    anytime = wls.select_samples(
        readings, images, groups=["high"], images_per_group=1, timezone_name=TZ
    )

    assert picked(anytime, "high") == [99]
    assert picked(result, "high") != [99]
    assert wls.SKIP_NOT_DAYTIME in result.groups[0].skip_counts


def test_approved_samples_are_rechecked_against_the_requested_time_of_day() -> None:
    readings, images = ramp()  # early-morning local readings
    top = readings[-1]
    item = {
        "group": "high",
        "reading_datetime_utc": top.datetime_utc,
        "filename": images[-1].source_url.rsplit("/", 1)[-1],
    }

    assert len(wls.verify_approved([item], readings, images, timezone_name=TZ)) == 1
    with pytest.raises(wls.SamplingError, match="daytime window"):
        wls.verify_approved([item], readings, images, timezone_name=TZ, time_of_day="daytime")


def test_an_unknown_time_of_day_is_rejected() -> None:
    readings, images = ramp()
    with pytest.raises(wls.SamplingError):
        wls.select_samples(
            readings,
            images,
            groups=["low"],
            images_per_group=1,
            timezone_name=TZ,
            time_of_day="night",
        )


def refs_for(group: str, count: int) -> list[dict[str, str]]:
    return [
        {"group": group, "reading_datetime_utc": f"t{n}", "filename": f"{group}{n}.jpg"}
        for n in range(count)
    ]


def test_approved_samples_must_fit_the_requested_groups_and_counts() -> None:
    wls.validate_approved_against_request(
        refs_for("low", 1) + refs_for("high", 3), ["low", "high"], 3
    )

    with pytest.raises(wls.SamplingError, match="not requested"):
        wls.validate_approved_against_request(refs_for("high", 3), ["low"], 3)
    with pytest.raises(
        wls.SamplingError, match="3 high samples were approved but 1 were requested"
    ):
        wls.validate_approved_against_request(refs_for("high", 3), ["high"], 1)
    with pytest.raises(wls.SamplingError):
        wls.validate_approved_against_request(refs_for("low", 1), [], 3)
    with pytest.raises(wls.SamplingError):
        wls.validate_approved_against_request(refs_for("low", 1), ["extreme"], 3)
    with pytest.raises(wls.SamplingError):
        wls.validate_approved_against_request(
            refs_for("low", 1), ["low"], wls.MAX_IMAGES_PER_GROUP + 1
        )
    with pytest.raises(wls.SamplingError, match="unknown"):
        wls.validate_approved_against_request([{"filename": "x.jpg"}], ["low"], 3)


def boundary_series() -> tuple[list[GageReading], datetime, datetime]:
    """Days 3..40 (value = day) give a distribution; the period is 2026-03-02 .. 2026-04-15 UTC."""

    start = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)
    end = datetime(2026, 4, 15, 0, 0, tzinfo=UTC)
    base = [reading(day(d), float(d)) for d in range(3, 41)]
    return base, start, end


def test_an_image_at_the_start_boundary_uses_the_nearer_reading_just_before_the_range() -> None:
    base, start, end = boundary_series()
    before = reading(
        datetime(2026, 3, 1, 23, 59, tzinfo=UTC), 1.0
    )  # outside the range, LOW, 2 min away
    inside = reading(
        datetime(2026, 3, 2, 0, 15, tzinfo=UTC), 99.0
    )  # inside the range, HIGH, 14 min away
    image_at = image(datetime(2026, 3, 2, 0, 1, tzinfo=UTC))
    readings = [*base, inside]
    images = [*[image(day(d, minute=5)) for d in range(3, 41)], image_at]
    kwargs = {
        "groups": ["high"],
        "images_per_group": 1,
        "timezone_name": "UTC",
        "period": (start, end),
    }

    # The old behaviour (matching only against in-range readings) mislabels the image as high.
    old = wls.select_samples(readings, images, **kwargs)  # type: ignore[arg-type]
    assert picked(old, "high") == [99]

    fixed = wls.select_samples(
        readings,
        images,
        matching_readings=[*readings, before],
        **kwargs,  # type: ignore[arg-type]
    )
    high = fixed.groups[0]
    assert picked(fixed, "high") != [99]
    assert wls.SKIP_IMAGE_OUTSIDE_GROUP in high.skip_counts


def test_an_image_at_the_end_boundary_uses_the_nearer_reading_just_after_the_range() -> None:
    base, start, end = boundary_series()
    inside = reading(datetime(2026, 4, 14, 23, 50, tzinfo=UTC), 99.0)  # in range, HIGH, 9 min away
    after = reading(
        datetime(2026, 4, 15, 0, 0, 30, tzinfo=UTC), 1.0
    )  # outside, LOW, 31 s from the image
    image_at = image(datetime(2026, 4, 14, 23, 59, 59, tzinfo=UTC))
    readings = [*base, inside]
    images = [*[image(day(d, minute=5)) for d in range(3, 41)], image_at]
    kwargs = {
        "groups": ["high"],
        "images_per_group": 1,
        "timezone_name": "UTC",
        "period": (start, end),
    }

    assert picked(wls.select_samples(readings, images, **kwargs), "high") == [99]  # type: ignore[arg-type]
    fixed = wls.select_samples(
        readings,
        images,
        matching_readings=[*readings, after],
        **kwargs,  # type: ignore[arg-type]
    )
    assert picked(fixed, "high") != [99]
    assert wls.SKIP_IMAGE_OUTSIDE_GROUP in fixed.groups[0].skip_counts


def test_group_bands_and_ranking_use_only_in_range_readings() -> None:
    base, start, end = boundary_series()
    outside_flood = reading(
        datetime(2026, 3, 1, 12, 0, tzinfo=UTC), 5000.0
    )  # outside: must not shift bands
    images = [image(day(d, minute=5)) for d in range(3, 41)]

    plain = wls.select_samples(
        base, images, groups=["high"], images_per_group=2, timezone_name="UTC", period=(start, end)
    )
    with_surround = wls.select_samples(
        base,
        images,
        groups=["high"],
        images_per_group=2,
        timezone_name="UTC",
        matching_readings=[*base, outside_flood],
        period=(start, end),
    )

    assert plain.thresholds == with_surround.thresholds
    assert picked(plain, "high") == picked(with_surround, "high") == [40, 37]


def test_an_image_outside_the_date_range_is_never_chosen() -> None:
    base, start, end = boundary_series()
    # The top reading is 5 minutes inside the range, but its only image is 5 minutes before it.
    top = reading(datetime(2026, 3, 2, 0, 5, tzinfo=UTC), 99.0)
    images = [
        *[image(day(d, minute=5)) for d in range(3, 41)],
        image(datetime(2026, 3, 1, 23, 58, tzinfo=UTC)),
    ]

    result = wls.select_samples(
        [*base, top],
        images,
        groups=["high"],
        images_per_group=1,
        timezone_name="UTC",
        period=(start, end),
    )

    assert picked(result, "high") != [99]
    assert wls.SKIP_IMAGE_OUT_OF_RANGE in result.groups[0].skip_counts


def test_approved_samples_are_verified_with_the_surrounding_readings_and_the_range() -> None:
    base, start, end = boundary_series()
    before = reading(datetime(2026, 3, 1, 23, 59, tzinfo=UTC), 1.0)
    inside = reading(datetime(2026, 3, 2, 0, 15, tzinfo=UTC), 99.0)
    image_at = image(datetime(2026, 3, 2, 0, 1, tzinfo=UTC))
    readings = [*base, inside]
    item = {
        "group": "high",
        "reading_datetime_utc": inside.datetime_utc,
        "filename": image_at.source_url.rsplit("/", 1)[-1],
    }
    images = [image_at]

    ok = wls.verify_approved([item], readings, images, timezone_name="UTC", period=(start, end))
    assert len(ok) == 1  # without the surrounding reading it looks valid
    with pytest.raises(wls.SamplingError, match="group re-check"):
        wls.verify_approved(
            [item],
            readings,
            images,
            timezone_name="UTC",
            period=(start, end),
            matching_readings=[*readings, before],
        )
    with pytest.raises(wls.SamplingError, match="date range"):
        wls.verify_approved(
            [item],
            readings,
            images,
            timezone_name="UTC",
            period=(datetime(2026, 3, 2, 0, 2, tzinfo=UTC), end),
        )

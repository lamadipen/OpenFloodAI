"""Image-to-gauge matching and reading-quality rules (issue #208)."""

from __future__ import annotations

from typing import Any

import pytest

from openfloodai.ingestion import usgs_gage_data as gage


def reading(stamp: str, value: float, qualifiers: tuple[str, ...] = ("A",)) -> gage.GageReading:
    return gage.GageReading(
        datetime_utc=stamp,
        value=value,
        qualifiers=qualifiers,
        quality_status=gage.interpret_quality(qualifiers),
    )


def match(readings: list[gage.GageReading], image_time: str) -> gage.GageMatch:
    return gage.GageReadingIndex(readings).match(image_time)


def test_exact_time_and_plus_minus_fifteen_minutes_match() -> None:
    image = "2026-09-01T10:00:00+00:00"
    for stamp, expected in [
        ("2026-09-01T10:00:00+00:00", 0),
        ("2026-09-01T10:15:00+00:00", 900),
        ("2026-09-01T09:45:00+00:00", -900),
    ]:
        result = match([reading(stamp, 4.0)], image)
        assert result.status == "matched"
        assert result.time_difference_seconds == expected


def test_readings_beyond_fifteen_minutes_do_not_match() -> None:
    for stamp in ("2026-09-01T10:16:00+00:00", "2026-09-01T09:44:00+00:00"):
        result = match([reading(stamp, 4.0)], "2026-09-01T10:00:00+00:00")
        assert result.status == "no_matching_reading"
        assert result.reading is None
        assert result.time_difference_seconds is None


def test_equidistant_readings_prefer_the_earlier_one() -> None:
    result = match(
        [
            reading("2026-09-01T10:10:00+00:00", 5.0),
            reading("2026-09-01T09:50:00+00:00", 4.0),
        ],
        "2026-09-01T10:00:00+00:00",
    )

    assert result.reading is not None
    assert result.reading.value == 4.0
    assert result.time_difference_seconds == -600


def test_nearest_in_window_reading_wins_over_a_farther_one() -> None:
    result = match(
        [
            reading("2026-09-01T09:50:00+00:00", 4.0),
            reading("2026-09-01T10:03:00+00:00", 4.5),
        ],
        "2026-09-01T10:00:00+00:00",
    )

    assert result.reading is not None and result.reading.value == 4.5
    assert result.candidates_in_window == 2


def test_never_interpolates_or_carries_an_older_reading_forward() -> None:
    # A reading 20 minutes earlier and another 20 minutes later: nothing is
    # averaged between them and neither is carried to the image's moment.
    result = match(
        [
            reading("2026-09-01T09:40:00+00:00", 4.0),
            reading("2026-09-01T10:20:00+00:00", 6.0),
        ],
        "2026-09-01T10:00:00+00:00",
    )

    assert result.status == "no_matching_reading"


def test_an_image_timestamp_without_a_zone_is_not_matched() -> None:
    result = match([reading("2026-09-01T10:00:00+00:00", 4.0)], "2026-09-01T10:00:00")
    assert result.status == "image_timestamp_invalid"
    assert match([], "not a time").status == "image_timestamp_invalid"


def test_matching_works_across_utc_midnight_and_local_offsets() -> None:
    # 23:55 UTC image, reading at 00:05 UTC next day: ten minutes apart.
    across = match([reading("2026-09-02T00:05:00+00:00", 4.0)], "2026-09-01T23:55:00+00:00")
    assert across.time_difference_seconds == 600
    # Image given in local time (-06:00), reading in UTC: same instant.
    local = match([reading("2026-09-01T16:00:00+00:00", 4.0)], "2026-09-01T10:00:00-06:00")
    assert local.status == "matched" and local.time_difference_seconds == 0


def test_matching_is_correct_across_a_daylight_saving_change() -> None:
    # US spring-forward, 2026-03-08: 01:50 MST is 08:50 UTC; 03:05 MDT is
    # 09:05 UTC -- fifteen real minutes apart despite a ~75 minute clock gap.
    result = match([reading("2026-03-08T09:05:00+00:00", 4.0)], "2026-03-08T01:50:00-07:00")
    assert result.status == "matched"
    assert result.time_difference_seconds == 900


def point(value: Any, stamp: str = "2026-09-01T10:00:00.000-06:00", **extra: Any) -> dict[str, Any]:
    return {"value": value, "dateTime": stamp, **extra}


@pytest.mark.parametrize(
    "bad_value", [None, "", "abc", "nan", "NaN", "inf", "-inf", "-999999", "-999999.0"]
)
def test_invalid_missing_nonfinite_and_no_data_values_are_rejected(bad_value: Any) -> None:
    assert gage._parse_reading_point(point(bad_value)) is None


def test_declared_series_no_data_value_is_rejected() -> None:
    assert gage._parse_reading_point(point("-9999"), no_data_value=-9999.0) is None
    assert gage._parse_reading_point(point("-9999")) is not None


def test_a_timestamp_without_an_offset_is_rejected() -> None:
    assert gage._parse_reading_point(point("3.0", "2026-09-01T10:00:00")) is None


def test_another_valid_in_window_reading_is_still_selected() -> None:
    raw = [
        point("-999999", "2026-09-01T09:59:00.000+00:00"),
        point("nan", "2026-09-01T10:00:00.000+00:00"),
        point("4.2", "2026-09-01T10:08:00.000+00:00", qualifiers=["P"]),
    ]
    readings = [gage._parse_reading_point(item) for item in raw]
    valid = [item for item in readings if item is not None]

    result = match(valid, "2026-09-01T10:00:00+00:00")

    assert len(valid) == 1
    assert result.reading is not None and result.reading.value == 4.2


def test_qualifiers_are_preserved_and_interpreted_without_upgrading_unknowns() -> None:
    assert gage.interpret_quality(["A"]) == "approved"
    assert gage.interpret_quality(["P"]) == "provisional"
    assert gage.interpret_quality(["P", "e"]) == "provisional"
    assert gage.interpret_quality([]) == "not_reported"
    assert gage.interpret_quality(["e"]) == "unknown"
    assert gage.interpret_quality(["Ice"]) == "unknown"
    parsed = gage._parse_reading_point(point("3.1", qualifiers=["e", "Ice"]))
    assert parsed is not None
    assert parsed.qualifiers == ("e", "Ice")
    assert parsed.quality_status == "unknown"


def test_a_provisional_reading_is_matchable_and_stays_marked_provisional() -> None:
    result = match([reading("2026-09-01T10:00:00+00:00", 4.0, ("P",))], "2026-09-01T10:00:00+00:00")
    assert result.reading is not None
    assert result.reading.quality_status == "provisional"
    assert result.reading.qualifiers == ("P",)


def test_duplicate_source_timestamps_resolve_deterministically() -> None:
    stamp = "2026-09-01T10:00:00+00:00"
    forward = [reading(stamp, 9.0, ("P",)), reading(stamp, 5.0, ("A",)), reading(stamp, 1.0, ())]
    backward = list(reversed(forward))

    kept_forward = gage.dedupe_readings(forward)
    kept_backward = gage.dedupe_readings(backward)

    assert kept_forward == kept_backward
    assert len(kept_forward) == 1
    # Approved beats provisional beats unreported, regardless of value.
    assert kept_forward[0].quality_status == "approved"


def test_series_only_reads_the_requested_station_and_parameter() -> None:
    payload = {
        "value": {
            "timeSeries": [
                {
                    "variable": {"variableCode": [{"value": "00060"}], "noDataValue": -999999.0},
                    "sourceInfo": {"siteCode": [{"value": "09095500"}]},
                    "values": [{"value": [point("450")]}],
                },
                {
                    "variable": {"variableCode": [{"value": "00065"}], "noDataValue": -999999.0},
                    "sourceInfo": {"siteCode": [{"value": "09095500"}]},
                    "values": [{"value": [point("3.5"), point("-999999")]}],
                },
                {
                    "variable": {"variableCode": [{"value": "00065"}]},
                    "sourceInfo": {"siteCode": [{"value": "OTHER"}]},
                    "values": [{"value": [point("77")]}],
                },
            ]
        }
    }

    readings, rejected = gage._parse_time_series(payload, "09095500", "00065")

    assert [item.value for item in readings] == [3.5]
    assert rejected == 1


def test_stage_and_discharge_stay_separately_identified_in_run_evidence() -> None:
    image = {
        "filename": "a.jpg",
        "captured_at_utc": "2026-09-01T10:00:00+00:00",
        "local_time": "2026-09-01T04:00:00-06:00",
        "download_status": "downloaded",
        "is_baseline": False,
        "change_score": 0.2,
    }
    for code, label, unit, fallback in [
        ("00065", "gage height", "ft", False),
        ("00060", "discharge", "ft3/s", True),
    ]:
        source = {
            "status": "available",
            "parameter": {
                "code": code,
                "label": label,
                "unit": unit,
                "used_fallback_discharge": fallback,
            },
            "readings": [
                {
                    "datetime_utc": "2026-09-01T10:00:00+00:00",
                    "value": 4.0,
                    "qualifiers": ["A"],
                }
            ],
        }

        evidence = gage.build_run_gauge_evidence(source, [image], source_sha256="abc")

        saved = evidence["images"][0]["reading"]
        assert (saved["parameter_code"], saved["parameter_label"], saved["unit"]) == (
            code,
            label,
            unit,
        )
        assert saved["used_fallback_discharge"] is fallback


def test_peak_event_with_no_image_in_window_says_so_and_keeps_its_own_reading() -> None:
    source = {
        "status": "available",
        "parameter": {"code": "00065", "label": "gage height", "unit": "ft"},
        "readings": [
            {"datetime_utc": "2026-09-01T10:00:00+00:00", "value": 9.0, "qualifiers": ["P"]},
            {"datetime_utc": "2026-09-01T10:30:00+00:00", "value": 2.0, "qualifiers": ["A"]},
        ],
    }
    images = [
        {
            "filename": "late.jpg",
            "captured_at_utc": "2026-09-01T10:20:00+00:00",
            "local_time": "x",
            "download_status": "downloaded",
            "is_baseline": False,
            "change_score": 0.9,
        }
    ]

    evidence = gage.build_run_gauge_evidence(source, images, source_sha256=None)

    highest = evidence["peak_events"]["highest"]
    # 20 minutes from the 10:00 peak: outside the window, so no image is shown
    # and no score is borrowed from the nearby-but-wrong one.
    assert highest["image_status"] == "no_matching_image"
    assert highest["image_filename"] is None
    assert highest["image_change_score"] is None
    assert highest["image_change_score_status"] == "no_matching_image"
    assert highest["event_reading"]["value"] == 9.0
    # The lowest reading (10:30) IS within 15 minutes of that image's 10:20.
    assert evidence["peak_events"]["lowest"]["image_filename"] == "late.jpg"

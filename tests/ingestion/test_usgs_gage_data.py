from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openfloodai.ingestion import usgs_gage_data as gage


def test_nwis_iv_url_uses_the_canonical_non_redirecting_host() -> None:
    # waterservices.usgs.gov permanently redirects to nwis.waterservices.usgs.gov,
    # and _NoRedirects refuses redirects outright for safety, so the base URL
    # must point straight at the canonical host or every request fails.
    assert gage.NWIS_IV_URL == "https://nwis.waterservices.usgs.gov/nwis/iv/"


def test_yearly_windows_splits_by_calendar_year_and_clips_ends() -> None:
    windows = gage.yearly_windows("2024-06-01", "2026-03-15")
    assert windows == [
        ("2024-06-01", "2024-12-31"),
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", "2026-03-15"),
    ]


def test_yearly_windows_single_year() -> None:
    assert gage.yearly_windows("2025-01-01", "2025-03-31") == [("2025-01-01", "2025-03-31")]


def test_yearly_windows_rejects_reversed_range() -> None:
    with pytest.raises(gage.GageDataError):
        gage.yearly_windows("2025-03-31", "2025-01-01")


def _series_payload(parameter_code: str, points: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "value": {
            "timeSeries": [
                {
                    "variable": {"variableCode": [{"value": parameter_code}]},
                    "values": [
                        {
                            "value": [
                                {"value": value, "dateTime": timestamp}
                                for timestamp, value in points
                            ]
                        }
                    ],
                }
            ]
        }
    }


def test_fetch_gage_readings_prefers_gage_height(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _series_payload(
        gage.PARAMETER_GAGE_HEIGHT,
        [
            ("2025-01-01T00:00:00.000-07:00", "3.45"),
            ("2025-01-01T06:00:00.000-07:00", "3.90"),
        ],
    )
    monkeypatch.setattr(gage, "_fetch_json", lambda url: payload)

    series = gage.fetch_gage_readings("09095500", "2025-01-01", "2025-01-31")

    assert series.parameter_code == gage.PARAMETER_GAGE_HEIGHT
    assert series.used_fallback_discharge is False
    assert len(series.readings) == 2
    assert series.readings[0].value == 3.45


def test_fetch_gage_readings_falls_back_to_discharge(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fetch(url: str) -> dict[str, Any]:
        calls.append(url)
        if "parameterCd=00065" in url:
            return {"value": {"timeSeries": []}}
        points = [("2025-01-01T00:00:00.000-07:00", "1200")]
        return _series_payload(gage.PARAMETER_DISCHARGE, points)

    monkeypatch.setattr(gage, "_fetch_json", fetch)

    series = gage.fetch_gage_readings("09095500", "2025-01-01", "2025-01-31")

    assert series.parameter_code == gage.PARAMETER_DISCHARGE
    assert series.used_fallback_discharge is True
    assert series.readings[0].value == 1200.0
    assert any("00065" in url for url in calls)
    assert any("00060" in url for url in calls)


def test_fetch_gage_readings_returns_unavailable_when_both_parameters_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gage, "_fetch_json", lambda url: {"value": {"timeSeries": []}})

    series = gage.fetch_gage_readings("09095500", "2025-01-01", "2025-01-31")

    assert series.readings == []
    assert series.parameter_label == "unavailable"


def test_fetch_gage_readings_rejects_blank_site_id() -> None:
    with pytest.raises(gage.GageDataError):
        gage.fetch_gage_readings("   ", "2025-01-01", "2025-01-31")


def test_largest_deltas_finds_rise_and_fall_within_window() -> None:
    readings = [
        gage.GageReading(datetime_utc="2025-01-01T00:00:00+00:00", value=1.0),
        gage.GageReading(datetime_utc="2025-01-01T04:00:00+00:00", value=4.0),
        gage.GageReading(datetime_utc="2025-01-01T08:00:00+00:00", value=1.5),
    ]

    increase, decrease = gage._largest_deltas(readings, window_hours=6)

    assert increase is not None and increase.delta_value == 3.0
    assert decrease is not None and decrease.delta_value == pytest.approx(-2.5)


def test_largest_deltas_handles_too_few_readings() -> None:
    single = [gage.GageReading(datetime_utc="2025-01-01T00:00:00+00:00", value=1.0)]
    assert gage._largest_deltas(single, 6) == (None, None)


def test_nearest_image_matches_closest_downloaded_record() -> None:
    manifest = [
        {
            "filename": "a.jpg",
            "captured_at_utc": "2025-01-01T00:00:00+00:00",
            "download_status": "downloaded",
        },
        {
            "filename": "b.jpg",
            "captured_at_utc": "2025-01-01T12:00:00+00:00",
            "download_status": "downloaded",
        },
        {
            "filename": "skipped.jpg",
            "captured_at_utc": "2025-01-01T12:01:00+00:00",
            "download_status": "missing",
        },
    ]

    filename, captured_at = gage._nearest_image(manifest, "2025-01-01T11:00:00+00:00")

    assert filename == "b.jpg"
    assert captured_at == "2025-01-01T12:00:00+00:00"


def test_summarize_gage_readings_builds_extremes_and_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _series_payload(
        gage.PARAMETER_GAGE_HEIGHT,
        [
            ("2025-01-01T00:00:00.000+00:00", "1.0"),
            ("2025-01-01T06:00:00.000+00:00", "4.0"),
            ("2025-01-01T12:00:00.000+00:00", "0.5"),
        ],
    )
    monkeypatch.setattr(gage, "_fetch_json", lambda url: payload)
    manifest = [
        {
            "filename": "high.jpg",
            "captured_at_utc": "2025-01-01T06:05:00+00:00",
            "download_status": "downloaded",
        },
    ]

    summary = gage.summarize_gage_readings(
        nwis_site_id="09095500",
        start_date="2025-01-01",
        end_date="2025-01-31",
        gage_relationship="same_site",
        gage_relationship_note=None,
        manifest_records=manifest,
    )

    assert summary.available is True
    assert summary.highest is not None and summary.highest.value == 4.0
    assert summary.highest.nearest_image_filename == "high.jpg"
    assert summary.lowest is not None and summary.lowest.value == 0.5
    assert any(delta.delta_value > 0 for delta in summary.largest_increases)
    assert any(delta.delta_value < 0 for delta in summary.largest_decreases)


def test_summarize_gage_readings_marks_unavailable_relationship_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_fetch(url: str) -> Any:
        raise AssertionError("must not fetch when gage_relationship is 'unavailable'")

    monkeypatch.setattr(gage, "_fetch_json", fail_fetch)

    summary = gage.summarize_gage_readings(
        nwis_site_id="09095500",
        start_date="2025-01-01",
        end_date="2025-01-31",
        gage_relationship="unavailable",
        gage_relationship_note=None,
        manifest_records=[],
    )

    assert summary.available is False
    assert summary.unavailable_reason


def test_summarize_gage_readings_never_raises_on_network_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_fetch(url: str) -> Any:
        raise gage.GageDataError("Could not reach USGS water-services. Try again later.")

    monkeypatch.setattr(gage, "_fetch_json", fail_fetch)

    summary = gage.summarize_gage_readings(
        nwis_site_id="09095500",
        start_date="2025-01-01",
        end_date="2025-01-31",
        gage_relationship="same_site",
        gage_relationship_note=None,
        manifest_records=[],
    )

    assert summary.available is False
    assert "USGS water-services" in (summary.unavailable_reason or "")


def test_summarize_gage_readings_requires_note_for_nearby_relationship() -> None:
    with pytest.raises(gage.GageDataError):
        gage.summarize_gage_readings(
            nwis_site_id="09095500",
            start_date="2025-01-01",
            end_date="2025-01-31",
            gage_relationship="nearby",
            gage_relationship_note=None,
            manifest_records=[],
        )


def test_summarize_gage_readings_rejects_invalid_relationship() -> None:
    with pytest.raises(gage.GageDataError):
        gage.summarize_gage_readings(
            nwis_site_id="09095500",
            start_date="2025-01-01",
            end_date="2025-01-31",
            gage_relationship="bogus",
            gage_relationship_note=None,
            manifest_records=[],
        )


def test_write_gauge_readings_summary_saves_json_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gage, "_fetch_json", lambda url: {"value": {"timeSeries": []}})

    summary = gage.write_gauge_readings_summary(
        tmp_path,
        nwis_site_id="09095500",
        start_date="2025-01-01",
        end_date="2025-01-31",
        gage_relationship="same_site",
        gage_relationship_note=None,
        manifest_records=[],
    )

    output_path = tmp_path / "gauge-readings-summary.json"
    assert output_path.exists()
    assert summary.available is False
    assert '"nwis_site_id": "09095500"' in output_path.read_text(encoding="utf-8")

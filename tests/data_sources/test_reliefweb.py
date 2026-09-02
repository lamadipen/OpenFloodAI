from __future__ import annotations

from openfloodai.data_sources.reliefweb import summarize_reports


def _report(
    title: str = "Test Report",
    countries: list[str] | None = None,
    disaster_types: list[str] | None = None,
    date_created: str = "2026-09-01T00:00:00+00:00",
) -> dict[str, object]:
    return {
        "title": title,
        "countries": countries or ["Nepal"],
        "disaster_types": disaster_types or ["Flood"],
        "date_created": date_created,
        "source": "UN OCHA",
    }


def test_empty_reports() -> None:
    result = summarize_reports([])
    assert result["report_count"] == 0
    assert result["report_state"] == "CLEAR"
    assert result["countries_affected"] == []
    assert result["latest_report"] is None


def test_single_report() -> None:
    result = summarize_reports([_report("Nepal Flood Update")])
    assert result["report_count"] == 1
    assert result["report_state"] == "ACTIVE_DISASTER"
    countries = result["countries_affected"]
    assert isinstance(countries, list) and "Nepal" in countries


def test_multiple_countries() -> None:
    reports = [
        _report("Nepal Report", countries=["Nepal"]),
        _report("Bangladesh Report", countries=["Bangladesh"]),
    ]
    result = summarize_reports(reports)
    assert result["report_count"] == 2
    countries = result["countries_affected"]
    assert isinstance(countries, list)
    assert "Nepal" in countries
    assert "Bangladesh" in countries


def test_latest_report_selected() -> None:
    reports = [
        _report("Old Report", date_created="2026-08-01T00:00:00+00:00"),
        _report("New Report", date_created="2026-09-01T00:00:00+00:00"),
    ]
    result = summarize_reports(reports)
    latest = result["latest_report"]
    assert isinstance(latest, dict)
    assert latest["title"] == "New Report"


def test_disaster_types_collected() -> None:
    reports = [
        _report(disaster_types=["Flood"]),
        _report(disaster_types=["Flash Flood", "Landslide"]),
    ]
    result = summarize_reports(reports)
    types = result["disaster_types"]
    assert isinstance(types, list)
    assert "Flood" in types
    assert "Flash Flood" in types
    assert "Landslide" in types


def test_many_reports_state() -> None:
    reports = [_report(f"Report {i}") for i in range(6)]
    result = summarize_reports(reports)
    assert result["report_count"] == 6
    assert result["report_state"] == "ACTIVE_DISASTER"

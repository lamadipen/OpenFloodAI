from pathlib import Path

import pytest

from openfloodai.validation.result_explanation import (
    explain_confirmed_reference,
    explain_result,
    explain_riverbank_evidence,
    read_result_explanations,
)

CONFIRMED = {
    "status": "confirmed",
    "video_id": "rising-001",
    "video_time_seconds": 5,
    "normal_condition": True,
}
DRAFT = {"status": "draft", "normal_condition": True}


def test_machine_finding_is_preserved_when_human_label_is_missing() -> None:
    result = explain_result("water_change_seen", "missing", "cannot_compare", "No label found.")
    assert result["status"] == "cannot_compare"
    assert "detected a visual change" in result["machine_observation"]
    assert result["human_observation"] == "No human label for comparison."
    assert "No human label for comparison" in result["reason"]
    assert "does not show whether water rose or fell" in result["machine_observation"]


def test_unclear_machine_and_human_are_both_explained() -> None:
    result = explain_result(
        "cannot_judge", "cannot_judge", "cannot_compare", "Too few usable frames."
    )
    assert "machine evidence is unclear" in result["reason"]
    assert "person could not judge" in result["reason"]
    assert "Too few usable frames" in result["reason"]
    assert "No human label" not in result["reason"]


def test_existing_report_keeps_separate_window_results(tmp_path: Path) -> None:
    path = tmp_path / "validation-report.md"
    path.write_text("""# Site Validation Report
## Detailed Results

### river-video
- Human label: mixed
- System result: mixed
- Per-window comparisons:
  - Window 1:
    - Human label: missing
    - System result: water_change_seen
    - Result: cannot_compare
    - Time window: missing
    - Note: No human label was found for this video.
  - Window 2:
    - Human label: no_clear_change
    - System result: no_clear_change
    - Result: agree
    - Time window: 10s to 20s
    - Note: Both saw no clear change.
## Safety Boundary
""")
    results = read_result_explanations(path)
    assert len(results) == 2
    assert results[0]["human_observation"] == "No human label for comparison."
    assert results[1]["time_window"] == "10s to 20s"
    assert "agree under" in results[1]["comparison_outcome"]


def test_missing_report_has_no_invented_results(tmp_path: Path) -> None:
    assert read_result_explanations(tmp_path / "missing.md") == []


def test_confirmed_reference_present_names_video_and_time() -> None:
    explanation = explain_confirmed_reference(CONFIRMED)

    assert explanation["available"] == "yes"
    assert "rising-001" in explanation["summary"]
    assert "5" in explanation["summary"]
    assert "normal condition confirmed: yes" in explanation["summary"]


def test_confirmed_reference_absent_is_plain() -> None:
    explanation = explain_confirmed_reference(None)

    assert explanation["available"] == "no"
    assert explanation["summary"].startswith("No confirmed reference yet.")


@pytest.mark.parametrize(
    ("label_record", "expected_text"),
    [
        ({"riverbank_visible": "yes"}, "was visible to the reviewer"),
        ({"riverbank_visible": "no"}, "was not visible to the reviewer"),
        ({"riverbank_visible": "unsure"}, "was unsure whether"),
        ({}, "was not recorded for this window"),
    ],
)
def test_riverbank_status_covers_each_value(
    label_record: dict[str, str], expected_text: str
) -> None:
    evidence = explain_riverbank_evidence(label_record, CONFIRMED, "no_clear_change")

    assert expected_text in evidence["riverbank_status"]


def test_riverbank_status_when_no_record_matched() -> None:
    evidence = explain_riverbank_evidence(None, CONFIRMED, "no_clear_change")

    assert "no reviewer notes" in evidence["riverbank_status"].lower()
    assert "unknown" in evidence["usable_reason"].lower()


@pytest.mark.parametrize(
    ("label_record", "confirmed_reference", "expected_snippet"),
    [
        ({"riverbank_visible": "no"}, CONFIRMED, "riverbank or stable reference is not visible"),
        ({"visibility_condition": "obstruction"}, CONFIRMED, "blocking the camera's view"),
        ({"camera_stable": "no"}, CONFIRMED, "camera does not appear stable"),
        ({"water_boundary_visible": "no"}, CONFIRMED, "water boundary is not clear enough"),
        ({"visibility_condition": "fog"}, CONFIRMED, "Visibility conditions"),
        ({}, DRAFT, "does not yet have a confirmed normal-condition"),
    ],
)
def test_usable_reason_covers_each_failure_code(
    label_record: dict[str, str], confirmed_reference: dict[str, object], expected_snippet: str
) -> None:
    evidence = explain_riverbank_evidence(label_record, confirmed_reference, "no_clear_change")

    assert "not usable for comparison" in evidence["usable_reason"]
    assert expected_snippet in evidence["usable_reason"]


def test_usable_reason_clean_case() -> None:
    label_record = {"riverbank_visible": "yes", "water_boundary_visible": "yes"}

    evidence = explain_riverbank_evidence(label_record, CONFIRMED, "no_clear_change")

    assert evidence["usable_reason"] == "This window's reference evidence is usable for comparison."


@pytest.mark.parametrize(
    ("system_result", "expected_snippet"),
    [
        ("water_change_seen", "cannot yet tell whether"),
        ("no_clear_change", "no sign of a coverage difference"),
        ("cannot_judge", "no coverage comparison can be made"),
        ("missing_system_output", "No machine result was available"),
    ],
)
def test_coverage_direction_is_honest_for_each_system_result(
    system_result: str, expected_snippet: str
) -> None:
    evidence = explain_riverbank_evidence({}, CONFIRMED, system_result)

    assert expected_snippet in evidence["coverage_direction"]


def test_coverage_direction_never_claims_more_or_less() -> None:
    evidence = explain_riverbank_evidence({}, CONFIRMED, "water_change_seen")

    assert "more or less" in evidence["coverage_direction"]
    assert "cannot yet tell" in evidence["coverage_direction"]

from pathlib import Path

from openfloodai.validation.result_explanation import explain_result, read_result_explanations


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

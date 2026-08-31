from __future__ import annotations

from openfloodai.review import build_operator_note


def test_normal_state_gives_calm_plain_language_note() -> None:
    note = build_operator_note(
        {
            "risk_state": "NORMAL",
            "reason_codes": ["NORMAL_CONDITIONS"],
        }
    )

    assert "looks calm" in note
    assert "normal conditions" in note
    assert "not an official public warning" in note


def test_watch_state_asks_for_continued_review() -> None:
    note = build_operator_note(
        {
            "risk_state": "WATCH",
            "reason_codes": ["ELEVATED_WATER_EVIDENCE"],
        }
    )

    assert "early concern" in note
    assert "keep reviewing" in note
    assert "not an official public warning" in note


def test_warning_candidate_state_says_human_review_is_needed() -> None:
    note = build_operator_note(
        {
            "risk_state": "WARNING_CANDIDATE",
            "reason_codes": ["HIGH_WATER_COVERAGE", "HUMAN_REVIEW_NEEDED"],
        }
    )

    assert "stronger concern" in note
    assert "person should review" in note
    assert "Human review is needed" in note
    assert "not an official public warning" in note


def test_unknown_state_says_system_could_not_judge_risk() -> None:
    note = build_operator_note(
        {
            "risk_state": "UNKNOWN",
            "reason_codes": ["CAMERA_OFFLINE", "DEGRADED_EVIDENCE_USED"],
        }
    )

    assert "could not judge risk" in note
    assert "Do not treat this as normal conditions" in note
    assert "camera or feed was not reachable" in note
    assert "not an official public warning" in note


def test_degraded_health_record_gets_clear_note_without_risk_state() -> None:
    note = build_operator_note(
        {
            "record_type": "camera_health_output",
            "input_quality_state": "UNKNOWN",
            "reason_codes": ["INPUT_UNKNOWN"],
        }
    )

    assert "camera or feed was not fully usable" in note
    assert "could not judge risk safely" in note
    assert "input was usable" in note
    assert "not an official public warning" in note


def test_unknown_reason_codes_do_not_crash_helper() -> None:
    note = build_operator_note(
        {
            "risk_state": "WATCH",
            "reason_codes": ["FUTURE_REASON_CODE"],
        }
    )

    assert "early concern" in note
    assert "not recognized" in note
    assert "not an official public warning" in note


def test_high_and_critical_documented_states_are_supported() -> None:
    high_note = build_operator_note(
        {
            "risk_state": "HIGH",
            "reason_codes": ["PERSISTENT_WATER_INCREASE"],
        }
    )
    critical_note = build_operator_note(
        {
            "risk_state": "CRITICAL",
            "reason_codes": ["CRITICAL_WATER_EVIDENCE"],
        }
    )

    assert "stronger concern" in high_note
    assert "severe concern" in critical_note
    assert "not an official public warning" in high_note
    assert "not an official public warning" in critical_note

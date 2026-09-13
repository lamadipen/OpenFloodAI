"""Plain-language descriptions of saved machine and human comparison results."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openfloodai.review.sample_quality import (
    compute_failure_reason,
    friendly_failure_reason,
    is_normal_baseline_confirmed,
)


def explain_result(machine: str, human: str, result: str, note: str) -> dict[str, str]:
    """Explain outcomes without changing comparison rules or hiding original notes."""

    machine_text = {
        "water_change_seen": (
            "The machine detected a visual change in the watched area. "
            "This does not show whether water rose or fell."
        ),
        "no_clear_change": "The machine did not detect a clear visual change in the watched area.",
        "cannot_judge": "The machine could not reach a clear result from the available evidence.",
        "missing_system_output": "No machine result was available for this video time window.",
    }.get(machine, f"Machine result: {machine}.")
    human_text = {
        "missing": "No human label for comparison.",
        "water_rising": "The person saw water rising.",
        "water_falling": "The person saw water falling.",
        "no_clear_change": "The person saw no clear water change.",
        "cannot_judge": "The person could not judge this video time window.",
        "camera_video_problem": "The person reported a camera or video problem.",
    }.get(human, f"Human label: {human}.")
    comparison_text = {
        "agree": "The machine evidence and human label agree under the current comparison rules.",
        "disagree": "The machine evidence and human label do not agree.",
        "cannot_compare": "A comparison could not be completed.",
    }.get(result, result)
    reasons = []
    if result == "cannot_compare":
        if human == "missing":
            reasons.append("No human label for comparison.")
        if machine == "missing_system_output":
            reasons.append("Machine output is missing for the reviewed time window.")
        if machine == "cannot_judge":
            reasons.append("The machine evidence is unclear or insufficient.")
        if human in {"cannot_judge", "camera_video_problem"}:
            reasons.append(human_text)
    if note:
        reasons.append(note)
    return {
        "status": result,
        "machine_observation": machine_text,
        "human_observation": human_text,
        "comparison_outcome": comparison_text,
        "reason": " ".join(reasons) or "No reason was recorded. Open the full report for details.",
    }


def explain_confirmed_reference(confirmed_reference: Mapping[str, Any] | None) -> dict[str, str]:
    """Explain the site's confirmed normal-condition reference, or its absence."""

    if confirmed_reference is None:
        return {
            "available": "no",
            "summary": (
                "No confirmed reference yet. This site does not yet have a confirmed "
                "normal-condition riverbank reference; comparisons below rely only on "
                "the machine's own before/after evidence for each video."
            ),
        }
    if not is_normal_baseline_confirmed(confirmed_reference):
        status = confirmed_reference.get("status", "unknown")
        video_id = confirmed_reference.get("video_id", "unknown")
        return {
            "available": "no",
            "summary": (
                f"Reference exists but is not confirmed. A reference for video "
                f"'{video_id}' is saved (status: {status}), but it is not yet a "
                f"confirmed normal-condition baseline; comparisons below rely only on "
                f"the machine's own before/after evidence for each video."
            ),
        }
    video_id = confirmed_reference.get("video_id", "unknown")
    video_time_seconds = confirmed_reference.get("video_time_seconds", "unknown")
    return {
        "available": "yes",
        "summary": (
            f"The confirmed normal-condition reference for this site is video "
            f"'{video_id}' at {video_time_seconds} seconds."
        ),
    }


_COVERAGE_DIRECTION_TEXT = {
    "water_change_seen": (
        "The machine detected a visual change in the watched area, but the system "
        "cannot yet tell whether this means more or less of the reference area is "
        "covered by water."
    ),
    "no_clear_change": (
        "The machine did not detect a clear visual change in this window; it has not "
        "measured coverage against the confirmed reference yet."
    ),
    "cannot_judge": (
        "The machine could not reach a clear result, so no coverage comparison can be made."
    ),
}


def explain_riverbank_evidence(
    label_record: Mapping[str, object] | None,
    confirmed_reference: Mapping[str, Any] | None,
    system_result: str,
) -> dict[str, str]:
    """Explain riverbank/reference usability and coverage-direction honesty for one window."""

    if label_record is None:
        riverbank_status = (
            "No reviewer notes were recorded for this window, so riverbank/reference "
            "visibility is unknown."
        )
        usable_reason = (
            "Reference evidence usability is unknown for this window; no reviewer "
            "record was matched."
        )
    else:
        riverbank_visible = label_record.get("riverbank_visible")
        riverbank_visible_key = riverbank_visible if isinstance(riverbank_visible, str) else ""
        riverbank_status = {
            "yes": "The riverbank/reference area was visible to the reviewer for this window.",
            "no": ("The riverbank/reference area was not visible to the reviewer for this window."),
            "unsure": (
                "The reviewer was unsure whether the riverbank/reference area was "
                "visible for this window."
            ),
        }.get(
            riverbank_visible_key,
            "Riverbank/reference visibility was not recorded for this window.",
        )
        failure_reason = compute_failure_reason(label_record, confirmed_reference)
        if failure_reason is None:
            usable_reason = "This window's reference evidence is usable for comparison."
        else:
            usable_reason = (
                f"This window's reference evidence is not usable for comparison: "
                f"{friendly_failure_reason(failure_reason)}"
            )
    coverage_direction = _COVERAGE_DIRECTION_TEXT.get(
        system_result,
        "No machine result was available, so no coverage comparison can be made.",
    )
    return {
        "riverbank_status": riverbank_status,
        "usable_reason": usable_reason,
        "coverage_direction": coverage_direction,
    }


def read_result_explanations(path: Path | None) -> list[dict[str, str]]:
    """Read per-window results from both existing and newly generated reports."""

    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    if "## Detailed Results" not in text:
        return []
    details = text.split("## Detailed Results", 1)[1].split("## Safety Boundary", 1)[0]
    results = []
    for section in details.split("\n### ")[1:]:
        video, _, body = section.partition("\n")
        windows = body.split("  - Window ")
        blocks = windows[1:] if len(windows) > 1 else [body]
        for block in blocks:
            fields = {}
            for line in block.splitlines():
                key, separator, value = line.strip().removeprefix("- ").partition(": ")
                if separator:
                    fields[key] = value
            if "System result" not in fields:
                continue
            item = explain_result(
                fields["System result"],
                fields.get("Human label", "missing"),
                fields.get("Result", "cannot_compare"),
                fields.get("Note", ""),
            )
            item["video_id"] = video.strip()
            item["time_window"] = fields.get("Time window", "Not recorded")
            results.append(item)
    return results

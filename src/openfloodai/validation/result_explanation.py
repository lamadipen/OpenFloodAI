"""Plain-language descriptions of saved machine and human comparison results."""

from pathlib import Path


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

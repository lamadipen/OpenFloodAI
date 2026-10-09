"""The pre-registered one-camera feasibility pilot for mask-based water change (Issue #222).

A pilot lives in one folder (``--pilot-dir``) and follows a fixed order that this module checks:

1. ``criteria.json``      people write tolerances, thresholds and stop conditions FIRST;
2. ``pairs.json``         the chosen ordered pairs (10-15), some marked held out;
3. ``judgments/*.json``   at least two reviewers judge the images blind to machine and gauge;
4. ``measurements/*.json`` the machine measurement (records the criteria hash it ran under);
5. ``report.json/.md``    errors AND unavailable counts, criteria checks, frozen gauge context
                          afterwards, and the limitations;
6. ``decision.json``      a person records proceed / revise / stop.

This tests feasibility. It is not an accuracy study and no production claim follows from it.
Held-out pairs are measured and scored only on explicit request, and every such evaluation is
logged, so they cannot be quietly tuned on.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openfloodai.curation.common import CurationError, sha256_file, utc_now
from openfloodai.water_change.pair import EndpointRef, measure_pair

CRITERIA_FILE = "criteria.json"
PAIRS_FILE = "pairs.json"
JUDGMENTS_DIR = "judgments"
MEASUREMENTS_DIR = "measurements"
HELD_OUT_LOG = "held-out-evaluations.jsonl"
DECISION_FILE = "decision.json"

CASE_TYPES = (
    "rising",
    "falling",
    "stable_high",
    "equal_area_different_shape",
    "difficult",
)
JUDGMENT_LABELS = ("more_water", "less_water", "about_same", "cannot_judge")
DECISIONS = ("proceed", "revise", "stop")
_PAIR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_REVIEWER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,63}$")

LIMITATIONS = (
    "A feasibility check on a handful of pairs from one camera. It is not an accuracy estimate "
    "and supports no production or warning claim.",
    "Coverage change is an image-space area, not physical water level, depth or flow speed. "
    "Narrow or deep channels can change height with little visible area change.",
    "Two endpoints cannot show an intermediate peak.",
    "Masks come from a hosted model and a person accepted them; errors beside the bank can "
    "reverse a small change. No mask editor exists.",
    "Framing is confirmed by a person; no automatic camera alignment was performed.",
    "Gauge values are instrument context, possibly from a nearby station. They are not labels, "
    "and disagreement needs investigation rather than automatic blame on the masks.",
)


class PilotError(CurationError):
    """A pilot file is missing or breaks the protocol."""


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PilotError(f"{what} not found: {path.name}") from error
    except ValueError as error:
        raise PilotError(f"{what} is not valid JSON: {path.name}") from error


def _aware(value: object, what: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as error:
        raise PilotError(f"{what} must be an ISO 8601 time with a time zone.") from error
    if parsed.tzinfo is None:
        raise PilotError(f"{what} must include a time zone.")
    return parsed


def _number(data: dict[str, Any], key: str, low: float, high: float | None = None) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PilotError(f"criteria '{key}' must be a number.")
    if value < low or (high is not None and value > high):
        raise PilotError(f"criteria '{key}' is out of range.")
    return float(value)


@dataclass(frozen=True)
class Criteria:
    written_by: str
    written_at: datetime
    stable_tolerance_pp: float
    min_pairs: int
    max_unavailable_rate: float
    min_consensus_pairs: int
    min_machine_agreement: float
    machine_vs_human_margin: float
    gauge_stable_tolerance: float
    stop_conditions: tuple[str, ...]
    sha256: str
    raw: dict[str, Any]


def load_criteria(pilot_dir: Path) -> Criteria:
    path = pilot_dir / CRITERIA_FILE
    data = _read_json(path, "The pilot criteria")
    if not isinstance(data, dict):
        raise PilotError("The pilot criteria must be a JSON object.")
    written_by = str(data.get("written_by") or "").strip()
    if not written_by:
        raise PilotError("criteria must name who wrote them ('written_by').")
    stops = data.get("stop_conditions")
    if not isinstance(stops, list) or not stops or not all(isinstance(s, str) and s for s in stops):
        raise PilotError("criteria must list at least one written stop condition.")
    return Criteria(
        written_by=written_by,
        written_at=_aware(data.get("written_at_utc"), "criteria 'written_at_utc'"),
        stable_tolerance_pp=_number(data, "stable_tolerance_pp", 0),
        min_pairs=int(_number(data, "min_pairs", 1)),
        max_unavailable_rate=_number(data, "max_unavailable_rate", 0, 1),
        min_consensus_pairs=int(_number(data, "min_consensus_pairs", 1)),
        min_machine_agreement=_number(data, "min_machine_agreement", 0, 1),
        machine_vs_human_margin=_number(data, "machine_vs_human_margin", 0, 1),
        gauge_stable_tolerance=_number(data, "gauge_stable_tolerance", 0),
        stop_conditions=tuple(stops),
        sha256=sha256_file(path),
        raw=data,
    )


@dataclass(frozen=True)
class PilotPair:
    pair_id: str
    earlier: EndpointRef
    later: EndpointRef
    case_type: str
    held_out: bool
    framing_confirmed_by: str


def _ref(data: object, what: str) -> EndpointRef:
    if not isinstance(data, dict) or not data.get("run_id") or not data.get("filename"):
        raise PilotError(f"{what} needs a run_id and a filename.")
    return EndpointRef(
        str(data["run_id"]),
        str(data["filename"]),
        str(data["mask_run_id"]) if data.get("mask_run_id") else None,
        str(data["mask_result_id"]) if data.get("mask_result_id") else None,
    )


def load_pairs(pilot_dir: Path) -> tuple[str, list[PilotPair]]:
    data = _read_json(pilot_dir / PAIRS_FILE, "The pilot pairs file")
    folder = str(data.get("site_folder") or "") if isinstance(data, dict) else ""
    rows = data.get("pairs") if isinstance(data, dict) else None
    if not folder or not isinstance(rows, list) or not rows:
        raise PilotError("pairs.json needs a 'site_folder' (one camera) and a list of 'pairs'.")
    pairs: list[PilotPair] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not _PAIR_ID.fullmatch(str(row.get("pair_id", ""))):
            raise PilotError("Every pair needs a simple 'pair_id'.")
        pair_id = str(row["pair_id"])
        if pair_id in seen:
            raise PilotError(f"Pair id '{pair_id}' is used twice.")
        seen.add(pair_id)
        if row.get("case_type") not in CASE_TYPES:
            raise PilotError(f"Pair '{pair_id}' needs a case_type from {list(CASE_TYPES)}.")
        framing = str(row.get("framing_confirmed_by") or "").strip()
        pairs.append(
            PilotPair(
                pair_id=pair_id,
                earlier=_ref(row.get("earlier"), f"Pair '{pair_id}' earlier"),
                later=_ref(row.get("later"), f"Pair '{pair_id}' later"),
                case_type=str(row["case_type"]),
                held_out=bool(row.get("held_out", False)),
                framing_confirmed_by=framing,
            )
        )
    return folder, pairs


# ---------------------------------------------------------------- measuring


def run_measurements(
    pilot_dir: Path, sites_dir: Path, *, include_held_out: bool = False
) -> dict[str, Any]:
    """Measure the pilot's pairs under the written criteria and save one timestamped file.

    Held-out pairs are skipped unless explicitly requested; a request is logged.
    """

    criteria = load_criteria(pilot_dir)
    folder, pairs = load_pairs(pilot_dir)
    chosen = [p for p in pairs if include_held_out or not p.held_out]
    if include_held_out:
        _log_held_out(pilot_dir, criteria.sha256, "measure")
    results = []
    for pair in chosen:
        measured = measure_pair(
            sites_dir,
            folder,
            pair.earlier,
            pair.later,
            framing_confirmed_by=pair.framing_confirmed_by or None,
        )
        results.append(
            {
                "pair_id": pair.pair_id,
                "case_type": pair.case_type,
                "held_out": pair.held_out,
                "pair_key": measured["pair_key"],
                "frozen_path": measured["path"],
                "evidence": measured["evidence"],
                "context": measured["context"],
            }
        )
    measured_at = utc_now()
    payload = {
        "measured_at_utc": measured_at,
        "criteria_sha256": criteria.sha256,
        "site_folder": folder,
        "scope": "development_and_held_out" if include_held_out else "development",
        "results": results,
    }
    out = pilot_dir / MEASUREMENTS_DIR
    out.mkdir(exist_ok=True)
    stamp = re.sub(r"[^0-9A-Za-z]", "", measured_at)
    with (out / f"{stamp}.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")
    return payload


def _log_held_out(pilot_dir: Path, criteria_sha: str, action: str) -> None:
    with (pilot_dir / HELD_OUT_LOG).open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"at_utc": utc_now(), "action": action, "criteria_sha256": criteria_sha})
            + "\n"
        )


def _read_measurements(pilot_dir: Path) -> list[dict[str, Any]]:
    files = sorted((pilot_dir / MEASUREMENTS_DIR).glob("*.json"))
    return [_read_json(path, "A measurement file") for path in files]


# ---------------------------------------------------------------- judgments


def _load_judgments(
    pilot_dir: Path, first_measured_at: datetime | None
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    """Valid judgments by reviewer, and a list of files that were set aside, with the reason."""

    valid: dict[str, dict[str, str]] = {}
    rejected: list[dict[str, str]] = []
    for path in sorted((pilot_dir / JUDGMENTS_DIR).glob("*.json")):
        try:
            data = _read_json(path, "A judgment file")
            reviewer = str(data.get("reviewer") or "").strip()
            if not _REVIEWER.fullmatch(reviewer):
                raise PilotError("no usable reviewer name")
            if not (
                data.get("blind_to_machine_results") is True and data.get("blind_to_gauge") is True
            ):
                raise PilotError(
                    "reviewer did not confirm judging blind to machine results and gauge"
                )
            judged_at = _aware(data.get("judged_at_utc"), "'judged_at_utc'")
            if first_measured_at is not None and judged_at >= first_measured_at:
                raise PilotError("judged after the first machine measurement existed")
            labels: dict[str, str] = {}
            for pair_id, entry in (data.get("judgments") or {}).items():
                label = entry.get("later_vs_earlier") if isinstance(entry, dict) else None
                if label not in JUDGMENT_LABELS:
                    raise PilotError(f"pair '{pair_id}' has no valid label")
                labels[str(pair_id)] = str(label)
            if reviewer in valid:
                raise PilotError("a second file for the same reviewer")
            valid[reviewer] = labels
        except (PilotError, AttributeError) as error:
            rejected.append({"file": path.name, "reason": str(error)})
    return valid, rejected


# ---------------------------------------------------------------- report


def machine_direction(delta_pp: float, tolerance_pp: float) -> str:
    if delta_pp > tolerance_pp:
        return "more_water"
    if delta_pp < -tolerance_pp:
        return "less_water"
    return "about_same"


def _gauge_direction(
    context: dict[str, Any], tolerance: float
) -> tuple[str | None, float | None, str]:
    earlier, later = context.get("earlier_gauge"), context.get("later_gauge")
    if not earlier or not later or not earlier.get("usable") or not later.get("usable"):
        return None, None, "no usable matched gauge reading at both ends"
    if earlier.get("unit") != later.get("unit"):
        return None, None, "gauge units differ"
    change = float(later["value"]) - float(earlier["value"])
    if change > tolerance:
        return "higher", change, ""
    if change < -tolerance:
        return "lower", change, ""
    return "about_same", change, ""


_GAUGE_TO_WATER = {"higher": "more_water", "lower": "less_water", "about_same": "about_same"}


def _split_metrics(
    rows: list[dict[str, Any]], reviewers: dict[str, dict[str, str]], criteria: Criteria
) -> dict[str, Any]:
    total = len(rows)
    unavailable = [r for r in rows if r["evidence"]["status"] != "available"]
    available = [r for r in rows if r["evidence"]["status"] == "available"]
    reasons: dict[str, int] = {}
    for row in unavailable:
        for code in row["evidence"]["reason_codes"]:
            reasons[code] = reasons.get(code, 0) + 1
    names = sorted(reviewers)
    consensus: dict[str, str] = {}
    pair_ids = [r["pair_id"] for r in rows]
    human_pairs = human_agree = 0
    for pair_id in pair_ids:
        labels = [reviewers[n].get(pair_id) for n in names]
        usable = [lab for lab in labels if lab and lab != "cannot_judge"]
        if len(names) >= 2 and len(usable) == len(names):
            human_pairs += 1
            if len(set(usable)) == 1:
                human_agree += 1
                consensus[pair_id] = usable[0]
    scored = errors = 0
    disagreements = []
    for row in available:
        expected = consensus.get(row["pair_id"])
        if expected is None:
            continue
        got = machine_direction(row["evidence"]["value"], criteria.stable_tolerance_pp)
        scored += 1
        if got != expected:
            errors += 1
            disagreements.append(
                {
                    "pair_id": row["pair_id"],
                    "machine": got,
                    "humans": expected,
                    "delta_percentage_points": row["evidence"]["value"],
                }
            )
    human_rate = human_agree / human_pairs if human_pairs else None
    machine_rate = (scored - errors) / scored if scored else None
    unavailable_rate = len(unavailable) / total if total else None
    checks = _checks(total, unavailable_rate, scored, machine_rate, human_rate, criteria)
    return {
        "pairs": total,
        "available": len(available),
        "unavailable": len(unavailable),
        "unavailable_rate": unavailable_rate,
        "unavailable_reasons": reasons,
        "pairs_where_all_reviewers_could_judge": human_pairs,
        "human_human_agreement": human_rate,
        "consensus_pairs": len(consensus),
        "machine_scored_pairs": scored,
        "machine_errors": errors,
        "machine_agreement_with_consensus": machine_rate,
        "machine_disagreements": disagreements,
        "checks": checks,
        "criteria_met": all(c["passed"] for c in checks),
    }


def _checks(
    total: int,
    unavailable_rate: float | None,
    scored: int,
    machine_rate: float | None,
    human_rate: float | None,
    criteria: Criteria,
) -> list[dict[str, Any]]:
    def check(name: str, passed: bool, detail: str) -> dict[str, Any]:
        return {"check": name, "passed": passed, "detail": detail}

    margin_ok = (
        machine_rate is not None
        and human_rate is not None
        and machine_rate >= human_rate - criteria.machine_vs_human_margin
    )
    return [
        check(
            "enough_pairs", total >= criteria.min_pairs, f"{total} pairs, need {criteria.min_pairs}"
        ),
        check(
            "unavailable_rate_within_limit",
            unavailable_rate is not None and unavailable_rate <= criteria.max_unavailable_rate,
            f"unavailable {unavailable_rate}, limit {criteria.max_unavailable_rate}",
        ),
        check(
            "enough_pairs_with_reviewer_consensus",
            scored >= criteria.min_consensus_pairs,
            f"{scored} scored pairs, need {criteria.min_consensus_pairs}",
        ),
        check(
            "machine_agreement_high_enough",
            machine_rate is not None and machine_rate >= criteria.min_machine_agreement,
            f"machine agreement {machine_rate}, need {criteria.min_machine_agreement}",
        ),
        check(
            "machine_as_consistent_as_people",
            margin_ok,
            f"machine {machine_rate} vs people {human_rate}, "
            f"margin {criteria.machine_vs_human_margin}",
        ),
    ]


def _gauge_review(rows: list[dict[str, Any]], criteria: Criteria) -> list[dict[str, Any]]:
    """Frozen gauge context AFTER machine results; every disagreement is flagged to investigate."""

    out = []
    for row in rows:
        if row["evidence"]["status"] != "available":
            continue
        direction, change, why = _gauge_direction(row["context"], criteria.gauge_stable_tolerance)
        machine = machine_direction(row["evidence"]["value"], criteria.stable_tolerance_pp)
        entry: dict[str, Any] = {
            "pair_id": row["pair_id"],
            "machine": machine,
            "gauge_change": change,
            "gauge_direction": direction,
            "note": why or None,
        }
        entry["investigate"] = bool(direction and _GAUGE_TO_WATER[direction] != machine)
        out.append(entry)
    return out


def build_report(pilot_dir: Path, *, evaluate_held_out: bool = False) -> dict[str, Any]:
    criteria = load_criteria(pilot_dir)
    _, pairs = load_pairs(pilot_dir)
    measurements = _read_measurements(pilot_dir)
    if not measurements:
        raise PilotError("No measurements yet. Run the measure step first.")
    protocol: list[str] = []
    first_time = _aware(measurements[0]["measured_at_utc"], "first measurement time")
    if criteria.written_at >= first_time:
        protocol.append("criteria were written after the first machine measurement")
    if any(m["criteria_sha256"] != criteria.sha256 for m in measurements):
        protocol.append("criteria changed after a measurement was made")
    reviewers, rejected = _load_judgments(pilot_dir, first_time)
    if len(reviewers) < 2:
        protocol.append("fewer than two valid blind reviewers")
    latest: dict[str, dict[str, Any]] = {}
    for measurement in measurements:  # a later measurement of the same pair replaces an earlier one
        for row in measurement["results"]:
            latest[row["pair_id"]] = row
    dev_rows = [latest[p.pair_id] for p in pairs if not p.held_out and p.pair_id in latest]
    held_rows = [latest[p.pair_id] for p in pairs if p.held_out and p.pair_id in latest]
    report: dict[str, Any] = {
        "generated_at_utc": utc_now(),
        "criteria_sha256": criteria.sha256,
        "criteria_written_by": criteria.written_by,
        "protocol_problems": protocol,
        "reviewers_counted": sorted(reviewers),
        "judgment_files_set_aside": rejected,
        "case_types_covered": sorted({p.case_type for p in pairs}),
        "case_types_missing": [c for c in CASE_TYPES if c not in {p.case_type for p in pairs}],
        "development": _split_metrics(dev_rows, reviewers, criteria),
        "gauge_context_after_machine_results": _gauge_review(dev_rows, criteria),
        "held_out": {"status": "not evaluated", "pairs_reserved": len(held_rows)},
        "stop_conditions_written_before_running": list(criteria.stop_conditions),
        "limitations": list(LIMITATIONS),
    }
    if evaluate_held_out:
        _log_held_out(pilot_dir, criteria.sha256, "report")
        report["held_out"] = {
            "status": "evaluated",
            "evaluations_so_far": _held_out_count(pilot_dir),
            **_split_metrics(held_rows, reviewers, criteria),
            "gauge_context_after_machine_results": _gauge_review(held_rows, criteria),
        }
    elif held_rows:
        report["held_out"]["note"] = "Measured but not scored. Do not tune on these pairs."
    report["mechanical_status"] = _status(report, evaluate_held_out)
    report["decision_required"] = (
        "A named person must record proceed / revise / stop in decision.json. This status is "
        "mechanical and is not that decision."
    )
    (pilot_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (pilot_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def _held_out_count(pilot_dir: Path) -> int:
    path = pilot_dir / HELD_OUT_LOG
    return len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0


def _status(report: dict[str, Any], evaluated_held_out: bool) -> str:
    if report["protocol_problems"]:
        return "protocol_not_followed"
    dev = report["development"]
    if not dev["criteria_met"]:
        return "criteria_not_met"
    if evaluated_held_out and not report["held_out"].get("criteria_met"):
        return "criteria_not_met_on_held_out"
    return "criteria_met_on_held_out" if evaluated_held_out else "criteria_met_held_out_not_checked"


def render_markdown(report: dict[str, Any]) -> str:
    def pct(value: object) -> str:
        return "n/a" if value is None else f"{float(value) * 100:.0f}%"  # type: ignore[arg-type]

    dev = report["development"]
    lines = [
        "# Water-change pilot report",
        "",
        f"Mechanical status: **{report['mechanical_status']}** "
        "(not the decision; see decision.json)",
        "",
    ]
    if report["protocol_problems"]:
        lines += ["## Protocol problems", *[f"- {p}" for p in report["protocol_problems"]], ""]
    lines += [
        "## Development pairs",
        f"- Pairs: {dev['pairs']}; available {dev['available']}; unavailable {dev['unavailable']} "
        f"({pct(dev['unavailable_rate'])})",
        f"- Reviewers counted: {', '.join(report['reviewers_counted']) or 'none'}",
        f"- People agree with each other: {pct(dev['human_human_agreement'])} "
        f"on {dev['pairs_where_all_reviewers_could_judge']} pairs both could judge",
        "- Machine agrees with unanimous reviewers: "
        f"{pct(dev['machine_agreement_with_consensus'])} "
        f"on {dev['machine_scored_pairs']} pairs ({dev['machine_errors']} errors)",
        "",
        "### Unavailable reasons",
        *[f"- {code}: {count}" for code, count in sorted(dev["unavailable_reasons"].items())],
        "",
        "### Checks written before the run",
        *[
            f"- {'PASS' if c['passed'] else 'FAIL'} {c['check']}: {c['detail']}"
            for c in dev["checks"]
        ],
        "",
        "### Machine disagreements",
        *[
            f"- {d['pair_id']}: machine {d['machine']}, people {d['humans']} "
            f"({d['delta_percentage_points']:.1f} pp)"
            for d in dev["machine_disagreements"]
        ],
        "",
        "## Gauge context (shown after machine results; investigate every flag)",
        *[
            f"- {g['pair_id']}: machine {g['machine']}, gauge {g['gauge_direction']} "
            f"({g['gauge_change']}){'  <- INVESTIGATE' if g['investigate'] else ''}"
            for g in report["gauge_context_after_machine_results"]
        ],
        "",
        f"## Held-out pairs: {report['held_out']['status']}",
        "",
        "## Stop conditions written before running",
        *[f"- {s}" for s in report["stop_conditions_written_before_running"]],
        "",
        "## Limitations",
        *[f"- {s}" for s in report["limitations"]],
        "",
    ]
    return "\n".join(lines)


def record_decision(
    pilot_dir: Path, decision: str, decided_by: str, rationale: str, limitations: str
) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise PilotError(f"decision must be one of {list(DECISIONS)}.")
    if not decided_by.strip() or not rationale.strip() or not limitations.strip():
        raise PilotError("A decision needs who decided, the reasoning and the known limitations.")
    report_path = pilot_dir / "report.json"
    report = _read_json(report_path, "The pilot report (run the report step first)")
    entry = {
        "decision": decision,
        "decided_by": decided_by.strip(),
        "decided_at_utc": utc_now(),
        "rationale": rationale.strip(),
        "limitations_acknowledged": limitations.strip(),
        "report_sha256": sha256_file(report_path),
        "mechanical_status_at_decision": report.get("mechanical_status"),
        "claim": "Feasibility decision only. No production accuracy claim follows.",
    }
    with (pilot_dir / DECISION_FILE).open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, indent=2) + "\n")
    return entry

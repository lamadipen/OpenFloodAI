"""Multi-source risk evaluator combining visual signals with external data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import uuid4

from openfloodai.risk_engine.rule_based import (
    RiskEvaluationError,
    RiskThresholds,
    evaluate_risk_state,
)

# Ordered from lowest to highest severity so comparisons are straightforward.
_RISK_STATE_LEVELS: dict[str, int] = {
    "NORMAL": 0,
    "WATCH": 1,
    "WARNING_CANDIDATE": 2,
    "UNKNOWN": -1,
}


@dataclass(frozen=True)
class MultiSourceThresholds(RiskThresholds):
    """Extended thresholds for the multi-source risk evaluator."""

    gauge_watch_ratio: float = 0.7
    gauge_warning_ratio: float = 0.9
    precipitation_watch_mm: float = 25.0
    precipitation_warning_mm: float = 50.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 0.0 < self.gauge_watch_ratio < self.gauge_warning_ratio <= 1.0:
            raise RiskEvaluationError(
                "Gauge ratios must satisfy 0.0 < gauge_watch_ratio < gauge_warning_ratio <= 1.0"
            )
        if not 0.0 < self.precipitation_watch_mm < self.precipitation_warning_mm:
            raise RiskEvaluationError(
                "Precipitation thresholds must satisfy 0.0 < precipitation_watch_mm "
                "< precipitation_warning_mm"
            )


def evaluate_multi_source_risk(
    health_record: Mapping[str, object],
    visual_signal_record: Mapping[str, object],
    *,
    water_conditions: Mapping[str, object] | None = None,
    flood_alerts: Mapping[str, object] | None = None,
    precipitation: Mapping[str, object] | None = None,
    seismic_risk: Mapping[str, object] | None = None,
    eonet_summary: Mapping[str, object] | None = None,
    reliefweb_summary: Mapping[str, object] | None = None,
    thresholds: MultiSourceThresholds | None = None,
) -> dict[str, object]:
    """Evaluate a risk state by combining visual signals with external data.

    Starts with the base visual risk from :func:`evaluate_risk_state` and
    then enriches it with USGS water conditions, NWS flood alerts,
    precipitation forecasts, seismic activity, NASA EONET events, and
    ReliefWeb disaster reports when those are provided.  Sources that are
    ``None`` are silently skipped (graceful degradation).

    Returns a record with ``record_type="multi_source_risk_output"``.
    """

    active_thresholds = thresholds or MultiSourceThresholds()
    base_thresholds = RiskThresholds(
        watch_threshold=active_thresholds.watch_threshold,
        warning_candidate_threshold=active_thresholds.warning_candidate_threshold,
    )

    base_result = evaluate_risk_state(
        health_record, visual_signal_record, thresholds=base_thresholds
    )

    data_sources_used: list[str] = ["visual"]
    source_signals: dict[str, object] = {
        "visual": {
            "risk_state": base_result["risk_state"],
            "confidence": base_result["confidence"],
        },
    }
    escalation_reasons: list[str] = []
    escalated_state = str(base_result["risk_state"])

    # --- USGS water conditions -------------------------------------------
    if water_conditions is not None:
        data_sources_used.append("usgs")
        usgs_signal = _assess_usgs(water_conditions, active_thresholds)
        source_signals["usgs"] = usgs_signal
        if usgs_signal["suggested_state"] is not None:
            suggested = str(usgs_signal["suggested_state"])
            if _level(suggested) > _level(escalated_state):
                escalated_state = suggested
                reasons = usgs_signal.get("reasons")
                for reason in reasons if isinstance(reasons, list) else []:
                    escalation_reasons.append(str(reason))

    # --- NWS flood alerts ------------------------------------------------
    if flood_alerts is not None:
        data_sources_used.append("nws")
        nws_signal = _assess_nws(flood_alerts, precipitation)
        source_signals["nws"] = nws_signal
        if nws_signal["suggested_state"] is not None:
            suggested = str(nws_signal["suggested_state"])
            if _level(suggested) > _level(escalated_state):
                escalated_state = suggested
                reasons = nws_signal.get("reasons")
                for reason in reasons if isinstance(reasons, list) else []:
                    escalation_reasons.append(str(reason))

    # --- Precipitation ---------------------------------------------------
    if precipitation is not None:
        if "precipitation" not in data_sources_used:
            data_sources_used.append("precipitation")
        precip_signal = _assess_precipitation(precipitation, active_thresholds)
        source_signals["precipitation"] = precip_signal
        if precip_signal["suggested_state"] is not None:
            suggested = str(precip_signal["suggested_state"])
            if _level(suggested) > _level(escalated_state):
                escalated_state = suggested
                reasons = precip_signal.get("reasons")
                for reason in reasons if isinstance(reasons, list) else []:
                    escalation_reasons.append(str(reason))

    # --- Seismic activity ------------------------------------------------
    if seismic_risk is not None:
        data_sources_used.append("earthquake")
        eq_signal = _assess_seismic(seismic_risk)
        source_signals["earthquake"] = eq_signal
        if eq_signal["suggested_state"] is not None:
            suggested = str(eq_signal["suggested_state"])
            if _level(suggested) > _level(escalated_state):
                escalated_state = suggested
                reasons = eq_signal.get("reasons")
                for reason in reasons if isinstance(reasons, list) else []:
                    escalation_reasons.append(str(reason))

    # --- NASA EONET events -----------------------------------------------
    if eonet_summary is not None:
        data_sources_used.append("eonet")
        eonet_signal = _assess_eonet(eonet_summary)
        source_signals["eonet"] = eonet_signal
        if eonet_signal["suggested_state"] is not None:
            suggested = str(eonet_signal["suggested_state"])
            if _level(suggested) > _level(escalated_state):
                escalated_state = suggested
                reasons = eonet_signal.get("reasons")
                for reason in reasons if isinstance(reasons, list) else []:
                    escalation_reasons.append(str(reason))

    # --- ReliefWeb disaster reports --------------------------------------
    if reliefweb_summary is not None:
        data_sources_used.append("reliefweb")
        rw_signal = _assess_reliefweb(reliefweb_summary)
        source_signals["reliefweb"] = rw_signal
        if rw_signal["suggested_state"] is not None:
            suggested = str(rw_signal["suggested_state"])
            if _level(suggested) > _level(escalated_state):
                escalated_state = suggested
                reasons = rw_signal.get("reasons")
                for reason in reasons if isinstance(reasons, list) else []:
                    escalation_reasons.append(str(reason))

    # Never de-escalate below the visual-only assessment.
    if _level(escalated_state) < _level(str(base_result["risk_state"])):
        escalated_state = str(base_result["risk_state"])

    return {
        "contract_version": "v1",
        "record_id": f"multi-source-risk-{uuid4()}",
        "record_type": "multi_source_risk_output",
        "site_id": base_result["site_id"],
        "camera_id": base_result["camera_id"],
        "timestamp": base_result["timestamp"],
        "base_risk_state": base_result["risk_state"],
        "base_confidence": base_result["confidence"],
        "base_reason_codes": base_result["reason_codes"],
        "base_human_summary": base_result["human_summary"],
        "data_sources_used": data_sources_used,
        "source_signals": source_signals,
        "escalation_reasons": escalation_reasons,
        "final_risk_state": escalated_state,
    }


# ---------------------------------------------------------------------------
# Internal assessment helpers
# ---------------------------------------------------------------------------


def _level(risk_state: str) -> int:
    """Return a numeric severity level for a risk state string."""
    return _RISK_STATE_LEVELS.get(risk_state, -1)


def _assess_usgs(
    water_conditions: Mapping[str, object],
    thresholds: MultiSourceThresholds,
) -> dict[str, object]:
    """Derive a suggested risk state from USGS water conditions."""

    gage_height = _optional_float(water_conditions.get("gage_height_ft"))
    flood_stage = _optional_float(water_conditions.get("flood_stage_ft"))

    signal: dict[str, object] = {
        "gage_height_ft": gage_height,
        "flood_stage_ft": flood_stage,
        "suggested_state": None,
        "reasons": [],
    }

    if gage_height is None or flood_stage is None or flood_stage <= 0.0:
        return signal

    ratio = gage_height / flood_stage
    signal["flood_proximity_ratio"] = round(ratio, 4)
    reasons: list[str] = []

    if ratio >= thresholds.gauge_warning_ratio:
        signal["suggested_state"] = "WARNING_CANDIDATE"
        reasons.append(
            f"USGS gage height {gage_height} ft is {ratio:.0%} of flood stage ({flood_stage} ft)"
        )
    elif ratio >= thresholds.gauge_watch_ratio:
        signal["suggested_state"] = "WATCH"
        reasons.append(
            f"USGS gage height {gage_height} ft is {ratio:.0%} of flood stage ({flood_stage} ft)"
        )

    signal["reasons"] = reasons
    return signal


def _assess_nws(
    flood_alerts: Mapping[str, object],
    precipitation: Mapping[str, object] | None,
) -> dict[str, object]:
    """Derive a suggested risk state from NWS flood alerts."""

    alert_type = str(flood_alerts.get("alert_type", "")).strip().upper()
    event = str(flood_alerts.get("event", "")).strip().upper()
    severity = str(flood_alerts.get("severity", "")).strip().upper()

    signal: dict[str, object] = {
        "alert_type": alert_type or event or None,
        "severity": severity or None,
        "suggested_state": None,
        "reasons": [],
    }
    reasons: list[str] = []

    is_warning = (
        _matches_any(alert_type, event, targets={"WARNING", "FLOOD WARNING"})
        or severity == "SEVERE"
    )

    is_watch = _matches_any(alert_type, event, targets={"WATCH", "FLOOD WATCH", "FLOOD ADVISORY"})

    if is_warning:
        signal["suggested_state"] = "WARNING_CANDIDATE"
        reasons.append("Active NWS flood warning")
    elif is_watch:
        # A watch alone escalates to WATCH, but combined with high
        # precipitation it stays as-is (precipitation handler can escalate
        # further if needed).
        has_high_precip = False
        if precipitation is not None:
            total_mm = _total_precipitation_mm(precipitation)
            if total_mm is not None and total_mm > 0:
                has_high_precip = True

        if has_high_precip:
            signal["suggested_state"] = "WATCH"
            reasons.append("NWS flood watch combined with precipitation forecast")
        else:
            signal["suggested_state"] = "WATCH"
            reasons.append("Active NWS flood watch")

    signal["reasons"] = reasons
    return signal


def _assess_precipitation(
    precipitation: Mapping[str, object],
    thresholds: MultiSourceThresholds,
) -> dict[str, object]:
    """Derive a suggested risk state from precipitation data."""

    total_mm = _total_precipitation_mm(precipitation)

    signal: dict[str, object] = {
        "total_precipitation_mm": total_mm,
        "suggested_state": None,
        "reasons": [],
    }
    reasons: list[str] = []

    if total_mm is None:
        return signal

    if total_mm >= thresholds.precipitation_warning_mm:
        signal["suggested_state"] = "WATCH"
        reasons.append(
            f"Precipitation total {total_mm:.1f} mm exceeds "
            f"warning threshold ({thresholds.precipitation_warning_mm} mm)"
        )
    elif total_mm >= thresholds.precipitation_watch_mm:
        signal["suggested_state"] = "WATCH"
        reasons.append(
            f"Precipitation total {total_mm:.1f} mm exceeds "
            f"watch threshold ({thresholds.precipitation_watch_mm} mm)"
        )

    signal["reasons"] = reasons
    return signal


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _optional_float(value: object) -> float | None:
    """Try to convert *value* to a float; return ``None`` on failure."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def _total_precipitation_mm(precipitation: Mapping[str, object]) -> float | None:
    """Extract total precipitation in mm from a precipitation record.

    Supports records with a ``precipitation_sum_mm`` field (Open-Meteo
    daily response) as well as records with a list of ``daily``
    precipitation values that should be summed.
    """

    # Direct total field.
    direct = _optional_float(precipitation.get("precipitation_sum_mm"))
    if direct is not None:
        return direct

    # Sum from a daily list.
    daily = precipitation.get("daily")
    if isinstance(daily, dict):
        sums = daily.get("precipitation_sum")
        if isinstance(sums, list):
            total = 0.0
            for value in sums:
                parsed = _optional_float(value)
                if parsed is not None:
                    total += parsed
            return total if total > 0.0 else None

    # Sum from a top-level list.
    sums_top = precipitation.get("precipitation_sum")
    if isinstance(sums_top, list):
        total = 0.0
        for value in sums_top:
            parsed = _optional_float(value)
            if parsed is not None:
                total += parsed
        return total if total > 0.0 else None

    return None


def _assess_seismic(
    seismic_risk: Mapping[str, object],
) -> dict[str, object]:
    """Derive a suggested risk state from seismic activity data."""

    risk_state = str(seismic_risk.get("seismic_risk_state", "NONE")).upper()
    max_mag = _optional_float(seismic_risk.get("max_magnitude")) or 0.0
    eq_count = seismic_risk.get("earthquake_count", 0)

    signal: dict[str, object] = {
        "seismic_risk_state": risk_state,
        "max_magnitude": max_mag,
        "earthquake_count": eq_count,
        "suggested_state": None,
        "reasons": [],
    }
    reasons: list[str] = []

    if risk_state in {"EXTREME", "HIGH"}:
        signal["suggested_state"] = "WARNING_CANDIDATE"
        reasons.append(
            f"M{max_mag} earthquake detected nearby -- landslide dam and GLOF risk elevated"
        )
    elif risk_state == "MODERATE":
        signal["suggested_state"] = "WATCH"
        reasons.append(
            f"M{max_mag} earthquake detected nearby -- monitoring for secondary flooding"
        )

    signal["reasons"] = reasons
    return signal


def _assess_eonet(
    eonet_summary: Mapping[str, object],
) -> dict[str, object]:
    """Derive a suggested risk state from NASA EONET event summary."""

    event_state = str(eonet_summary.get("event_state", "CLEAR")).upper()
    flood_count = eonet_summary.get("flood_count", 0)
    landslide_count = eonet_summary.get("landslide_count", 0)
    storm_count = eonet_summary.get("storm_count", 0)
    event_count = eonet_summary.get("event_count", 0)

    signal: dict[str, object] = {
        "event_state": event_state,
        "event_count": event_count,
        "suggested_state": None,
        "reasons": [],
    }
    reasons: list[str] = []

    if isinstance(flood_count, int) and flood_count > 0:
        signal["suggested_state"] = "WARNING_CANDIDATE"
        reasons.append(f"NASA EONET tracking {flood_count} active flood event(s) nearby")
    elif isinstance(landslide_count, int) and landslide_count > 0:
        signal["suggested_state"] = "WATCH"
        reasons.append(
            f"NASA EONET tracking {landslide_count} landslide event(s) nearby "
            "-- secondary flood risk"
        )
    elif isinstance(storm_count, int) and storm_count > 0:
        signal["suggested_state"] = "WATCH"
        reasons.append(f"NASA EONET tracking {storm_count} severe storm(s) nearby")

    signal["reasons"] = reasons
    return signal


def _assess_reliefweb(
    reliefweb_summary: Mapping[str, object],
) -> dict[str, object]:
    """Derive a suggested risk state from ReliefWeb disaster reports."""

    report_state = str(reliefweb_summary.get("report_state", "CLEAR")).upper()
    report_count = reliefweb_summary.get("report_count", 0)
    countries = reliefweb_summary.get("countries_affected", [])

    signal: dict[str, object] = {
        "report_state": report_state,
        "report_count": report_count,
        "suggested_state": None,
        "reasons": [],
    }
    reasons: list[str] = []

    if report_state == "ACTIVE_DISASTER":
        country_str = ""
        if isinstance(countries, list) and countries:
            country_str = f" in {', '.join(str(c) for c in countries[:3])}"
        if isinstance(report_count, int) and report_count >= 5:
            signal["suggested_state"] = "WARNING_CANDIDATE"
            reasons.append(
                f"ReliefWeb tracking {report_count} humanitarian reports{country_str} "
                "-- major flood disaster in progress"
            )
        else:
            signal["suggested_state"] = "WATCH"
            reasons.append(
                f"ReliefWeb tracking {report_count} humanitarian report(s){country_str}"
            )

    signal["reasons"] = reasons
    return signal


def _matches_any(*values: str, targets: set[str]) -> bool:
    """Return True if any of the given values matches one of the targets."""
    return any(v in targets for v in values if v)

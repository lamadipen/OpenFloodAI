"""Plain-language notes for local POC output records."""

from __future__ import annotations

from collections.abc import Mapping

PUBLIC_WARNING_BOUNDARY = "This is not an official public warning."

RISK_STATE_NOTES = {
    "NORMAL": "The current POC output looks calm based on the available test evidence.",
    "WATCH": "The current POC output shows early concern, so a person should keep reviewing it.",
    "ELEVATED": "The current POC output shows early concern, so a person should keep reviewing it.",
    "WARNING_CANDIDATE": (
        "The current POC output shows a stronger concern. A person should review it before "
        "any action is taken."
    ),
    "HIGH": (
        "The current POC output shows a stronger concern. A person should review it before "
        "any action is taken."
    ),
    "CRITICAL": (
        "The current POC output shows severe concern. Urgent human review is needed before "
        "any public action is taken."
    ),
    "UNKNOWN": (
        "The system could not judge risk from the available evidence. Do not treat this as "
        "normal conditions."
    ),
    "UNKNOWN_DEGRADED": (
        "The system could not judge risk because evidence was missing or unreliable. Do not "
        "treat this as normal conditions."
    ),
}

REASON_CODE_NOTES = {
    "INPUT_USABLE": "The input looked usable for this local review.",
    "INPUT_DEGRADED": "The input existed, but quality was reduced.",
    "INPUT_UNKNOWN": "The system could not tell if the input was usable.",
    "BAD_TIMESTAMP": "The frame time was missing, wrong, or not trusted.",
    "MISSING_FRAME": "An expected frame was missing.",
    "LOW_CONFIDENCE": "The evidence was weak or uncertain.",
    "CAMERA_OFFLINE": "The camera or feed was not reachable.",
    "STREAM_DISCONNECTED": "The video stream disconnected.",
    "STALE_FRAMES": "The same old frame appeared to repeat.",
    "LOW_VISIBILITY": "The river view was hard to see.",
    "CAMERA_OBSTRUCTED": "Something may have blocked the camera view.",
    "NIGHT_OR_LOW_LIGHT": "The scene was too dark to trust fully.",
    "HEAVY_RAIN_ON_LENS": "Rain on the lens may have made the image hard to use.",
    "CAMERA_MOVED": "The camera view may have moved from the expected scene.",
    "WATER_REGION_VISIBLE": "The water or river area appeared visible.",
    "WATER_COVERAGE_INCREASED": "Water appeared to cover more of the watched area.",
    "WATER_NEAR_REFERENCE_LINE": "Water appeared close to a configured reference line.",
    "WATER_ABOVE_REFERENCE_LINE": "Water appeared above a configured reference line.",
    "SCENE_CHANGED": "The scene changed enough that past comparison may be less reliable.",
    "MODEL_UNCERTAIN": "The model or visual method was unsure.",
    "PERSISTENT_WATER_INCREASE": "Water increase appeared to last across the review window.",
    "RAPID_WATER_RISE": "Water appeared to rise quickly.",
    "SHORT_SPIKE_ONLY": "A brief change happened, but it may not have lasted.",
    "INSUFFICIENT_HISTORY": "There was not enough past evidence to judge change.",
    "MISSING_TIME_WINDOW": "The expected time window was incomplete.",
    "NORMAL_CONDITIONS": "The available evidence supported normal conditions.",
    "ELEVATED_WATER_EVIDENCE": "The evidence suggested early concern.",
    "HIGH_WATER_COVERAGE": "Water coverage was high enough to require review.",
    "CRITICAL_WATER_EVIDENCE": "The evidence was severe enough to require urgent review.",
    "DEGRADED_EVIDENCE_USED": "Some evidence was poor quality and affected the result.",
    "RISK_STATE_CHANGED": "The risk state changed from the previous result.",
    "RISK_STATE_UNCHANGED": "The risk state stayed the same.",
    "HUMAN_REVIEW_NEEDED": "Human review is needed before any public action.",
    "ALERT_CANDIDATE_CREATED": "A review candidate was created for operators.",
    "ALERT_CANDIDATE_SUPPRESSED": "A candidate was not created because rules did not allow it.",
    "DUPLICATE_CANDIDATE_SUPPRESSED": "A repeated candidate was suppressed.",
    "OFFICIAL_WARNING_NOT_CREATED": "OpenFloodAI did not create an official warning.",
    "NETWORK_OFFLINE": "Cloud or internet access was unavailable.",
    "LOCAL_RECORD_QUEUED": "A record was stored locally for later handling.",
    "LOCAL_UPLOAD_PENDING": "Upload had not happened yet.",
    "LOCAL_STORAGE_LOW": "Local disk space was low.",
    "LOCAL_STORAGE_FAILED": "Local storage failed.",
    "EXACT_LOCATION_RESTRICTED": "Exact location details should stay restricted.",
    "PUBLIC_LOCATION_ONLY": "Only broad public location details should be shown.",
    "RAW_VIDEO_NOT_STORED": "Raw video was not stored.",
    "EVENT_CLIP_STORED": "A short event clip was stored under site policy.",
    "SENSITIVE_VIEW_DETECTED": "The camera view may include sensitive details.",
}

UNKNOWN_REASON_NOTE = "Some technical reason codes were not recognized by this helper."


def build_operator_note(record: Mapping[str, object]) -> str:
    """Build a short plain-language note for a POC output record."""

    risk_state = _normalized_text(record.get("risk_state"))
    reason_codes = _reason_codes(record)

    sentences: list[str] = []
    if risk_state:
        sentences.append(
            RISK_STATE_NOTES.get(
                risk_state,
                "The current POC output used a risk state this helper does not recognize yet.",
            )
        )
    elif _has_degraded_input(record, reason_codes):
        sentences.append(
            "The camera or feed was not fully usable, so the system could not judge risk safely."
        )
    else:
        sentences.append("This record was saved for local review.")

    reason_notes = _reason_notes(reason_codes)
    if reason_notes:
        sentences.append("Why: " + " ".join(reason_notes))

    sentences.append(PUBLIC_WARNING_BOUNDARY)
    return " ".join(sentences)


def _normalized_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _reason_codes(record: Mapping[str, object]) -> list[str]:
    value = record.get("reason_codes")
    if not isinstance(value, list):
        return []

    return [_normalized_text(item) for item in value if isinstance(item, str) and item.strip()]


def _has_degraded_input(record: Mapping[str, object], reason_codes: list[str]) -> bool:
    input_quality_state = _normalized_text(record.get("input_quality_state"))
    if input_quality_state in {"UNKNOWN", "DEGRADED"}:
        return True

    return any(
        reason_code in {"INPUT_UNKNOWN", "INPUT_DEGRADED", "DEGRADED_EVIDENCE_USED"}
        for reason_code in reason_codes
    )


def _reason_notes(reason_codes: list[str]) -> list[str]:
    if not reason_codes:
        return []

    notes: list[str] = []
    has_unknown_reason = False
    seen_notes: set[str] = set()

    for reason_code in reason_codes:
        note = REASON_CODE_NOTES.get(reason_code)
        if note is None:
            has_unknown_reason = True
            continue
        if note in seen_notes:
            continue

        notes.append(note)
        seen_notes.add(note)

    if has_unknown_reason:
        notes.append(UNKNOWN_REASON_NOTE)

    return notes

# OpenFloodAI V1 Reason Codes and Risk-State Rules

## 1. Purpose

This document defines the first V1 reason codes for OpenFloodAI.

Reason codes explain why the system chose a risk state such as `NORMAL`, `HIGH`, or `UNKNOWN_DEGRADED`.

This is planning documentation only. It does not add risk-engine code, ML code, camera ingestion, alert delivery, database storage, dashboard UI, public warning logic, or training code.

## 2. Plain-Language Summary

A reason code is a short label that explains what happened.

Simple example: if the camera is offline, the system can record `CAMERA_OFFLINE`. That is clearer than a long vague message like “something may be wrong.”

Reason codes help operators, developers, and QA reviewers understand the system later. They should explain evidence, not give emergency instructions.

## 3. Risk States

OpenFloodAI V1 uses these risk states:

| Risk State | Simple Meaning |
| --- | --- |
| `NORMAL` | No concerning flood evidence is currently detected. |
| `ELEVATED` | Water evidence is higher than usual or starting to change. |
| `HIGH` | Strong evidence suggests flood risk may be developing. |
| `CRITICAL` | Severe evidence suggests urgent human review is needed. |
| `UNKNOWN_DEGRADED` | The system cannot safely judge risk because input is missing, stale, blocked, or unreliable. |

Simple example: if the camera is frozen, the risk state should be `UNKNOWN_DEGRADED`, not `NORMAL`.

## 4. Input-Quality Reason Codes

Input-quality reason codes describe whether evidence is good enough to use.

| Reason Code | Simple Meaning |
| --- | --- |
| `INPUT_USABLE` | The input looks good enough for analysis. |
| `INPUT_DEGRADED` | The input exists, but quality is reduced. |
| `INPUT_UNKNOWN` | The system cannot tell if the input is usable. |
| `BAD_TIMESTAMP` | The frame time is missing, wrong, or not trusted. |
| `MISSING_FRAME` | An expected frame was not received. |
| `LOW_CONFIDENCE` | The system has weak confidence in the evidence. |

Simple example: if a video frame arrives without a usable timestamp, record `BAD_TIMESTAMP`.

## 5. Camera / Feed Reason Codes

Camera/feed reason codes describe camera and video-stream problems.

| Reason Code | Simple Meaning |
| --- | --- |
| `CAMERA_OFFLINE` | The camera is not reachable. |
| `STREAM_DISCONNECTED` | The video stream disconnected. |
| `STALE_FRAMES` | The same old frame appears to repeat. |
| `LOW_VISIBILITY` | The river view is hard to see. |
| `CAMERA_OBSTRUCTED` | Something blocks the camera view. |
| `NIGHT_OR_LOW_LIGHT` | The scene is too dark or has too little light. |
| `HEAVY_RAIN_ON_LENS` | Rain on the lens makes the image hard to use. |
| `CAMERA_MOVED` | The camera view changed from the expected scene. |

Simple example: if the camera points away from the river after strong wind, record `CAMERA_MOVED`.

## 6. Vision / ML Reason Codes

Vision/ML reason codes describe what the vision module thinks it sees.

These codes are evidence only. They are not ground truth and are not public warning instructions.

| Reason Code | Simple Meaning |
| --- | --- |
| `WATER_REGION_VISIBLE` | The river or water area is visible. |
| `WATER_COVERAGE_INCREASED` | Water appears to cover more of the watched area. |
| `WATER_NEAR_REFERENCE_LINE` | Water appears close to a configured reference line. |
| `WATER_ABOVE_REFERENCE_LINE` | Water appears above a configured reference line. |
| `SCENE_CHANGED` | The scene changed enough that past comparison may be less reliable. |
| `MODEL_UNCERTAIN` | The model or visual method is unsure. |

Simple example: if water appears above a painted marker on a bridge support, record `WATER_ABOVE_REFERENCE_LINE`.

## 7. Temporal-Change Reason Codes

Temporal-change reason codes describe what happened over time.

| Reason Code | Simple Meaning |
| --- | --- |
| `PERSISTENT_WATER_INCREASE` | Water increase lasted across the evidence window. |
| `RAPID_WATER_RISE` | Water appears to be rising quickly. |
| `SHORT_SPIKE_ONLY` | A brief change happened but did not last. |
| `INSUFFICIENT_HISTORY` | There is not enough past evidence to judge change. |
| `MISSING_TIME_WINDOW` | The expected time window is incomplete. |

Simple example: one splash may be `SHORT_SPIKE_ONLY`. Water rising for several minutes may be `PERSISTENT_WATER_INCREASE`.

## 8. Risk-Engine Reason Codes

Risk-engine reason codes explain how the risk state was selected.

| Reason Code | Simple Meaning |
| --- | --- |
| `NORMAL_CONDITIONS` | Current evidence supports normal conditions. |
| `ELEVATED_WATER_EVIDENCE` | Evidence suggests early concern. |
| `HIGH_WATER_COVERAGE` | Water coverage is high enough to support a high-risk state. |
| `CRITICAL_WATER_EVIDENCE` | Evidence is severe enough to support urgent review. |
| `DEGRADED_EVIDENCE_USED` | Some evidence was poor quality and affected the decision. |
| `RISK_STATE_CHANGED` | The risk state changed from the previous state. |
| `RISK_STATE_UNCHANGED` | The risk state stayed the same. |

Simple example: a `HIGH` output might include `HIGH_WATER_COVERAGE`, `PERSISTENT_WATER_INCREASE`, and `RISK_STATE_CHANGED`.

## 9. Alert-Candidate Reason Codes

Alert-candidate reason codes explain what happened to an alert candidate.

| Reason Code | Simple Meaning |
| --- | --- |
| `HUMAN_REVIEW_NEEDED` | A person or approved local process should review the situation. |
| `ALERT_CANDIDATE_CREATED` | An alert candidate was created. |
| `ALERT_CANDIDATE_SUPPRESSED` | A candidate was not created because rules did not allow it. |
| `DUPLICATE_CANDIDATE_SUPPRESSED` | A repeated candidate was suppressed. |
| `OFFICIAL_WARNING_NOT_CREATED` | No official public warning was created by OpenFloodAI. |

Simple example: if a `HIGH` state already created a candidate two minutes ago, a duplicate may be suppressed with `DUPLICATE_CANDIDATE_SUPPRESSED`.

## 10. Offline / Local-Storage Reason Codes

Offline/local-storage reason codes describe network and edge storage behavior.

| Reason Code | Simple Meaning |
| --- | --- |
| `NETWORK_OFFLINE` | Cloud or internet access is unavailable. |
| `LOCAL_RECORD_QUEUED` | A record was stored locally for later upload. |
| `LOCAL_UPLOAD_PENDING` | Upload has not happened yet. |
| `LOCAL_STORAGE_LOW` | Local disk space is low. |
| `LOCAL_STORAGE_FAILED` | Local storage failed. |

Simple example: if the edge node cannot reach the cloud, it may record `NETWORK_OFFLINE` and `LOCAL_RECORD_QUEUED`.

## 11. Privacy / Safety Reason Codes

Privacy/safety reason codes explain sensitive-data handling and safety boundaries.

| Reason Code | Simple Meaning |
| --- | --- |
| `EXACT_LOCATION_RESTRICTED` | Exact GPS or placement details are restricted. |
| `PUBLIC_LOCATION_ONLY` | Only broad location information should be shown publicly. |
| `RAW_VIDEO_NOT_STORED` | Raw video was not stored. |
| `EVENT_CLIP_STORED` | A short event clip was stored under site policy. |
| `SENSITIVE_VIEW_DETECTED` | The view may include people, homes, roads, vehicles, or license plates. |

Simple example: if a road appears in the camera view, record `SENSITIVE_VIEW_DETECTED` and consider masking or cropping before public deployment.

## 12. How Multiple Reason Codes Should Be Combined

A record may include more than one reason code.

Use multiple codes when they explain different parts of the decision:

- Use input-quality codes to explain whether the video can be trusted.
- Use camera/feed codes to explain camera problems.
- Use vision/ML codes to explain visual evidence.
- Use temporal-change codes to explain what happened over time.
- Use risk-engine codes to explain the selected risk state.
- Use alert-candidate codes to explain alert-candidate behavior.
- Use privacy/safety codes to explain sensitive-data handling.

Rules:

- Include at least one reason code in every risk-engine output.
- Put the most important reason first when order is meaningful.
- Do not use reason codes as full public warning text.
- Do not hide degraded evidence behind a normal-looking result.
- Keep reason codes stable once event records depend on them.

Simple example: a record may include `HIGH_WATER_COVERAGE`, `PERSISTENT_WATER_INCREASE`, and `HUMAN_REVIEW_NEEDED`.

## 13. How Reason Codes Should Appear in Event / Audit Records

Reason codes should appear in event and audit records as an array of strings.

Example:

```json
{
  "record_type": "event_audit_record",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:00+05:45",
  "risk_state": "HIGH",
  "reason_codes": [
    "HIGH_WATER_COVERAGE",
    "PERSISTENT_WATER_INCREASE",
    "RISK_STATE_CHANGED",
    "ALERT_CANDIDATE_CREATED"
  ]
}
```

Audit records should also include the evidence window, software version, config version, and model version if a model was used.

Simple example: months later, a reviewer should be able to see that an alert candidate happened because water coverage was high and stayed high, not because of a random single frame.

## 14. Validation and Testability Expectations

Future tests should check reason-code behavior.

Test expectations:

- `CAMERA_OFFLINE` should lead to `UNKNOWN_DEGRADED`.
- `STALE_FRAMES` should not produce `NORMAL`.
- `HIGH_WATER_COVERAGE` plus `PERSISTENT_WATER_INCREASE` can support `HIGH`.
- `CRITICAL_WATER_EVIDENCE` can support `CRITICAL`.
- `LOW_CONFIDENCE` should be visible in audit records.
- Every risk-engine output should include at least one reason code.
- Public-facing records should not include private location or camera-secret details.
- Alert candidates should include review-oriented codes, not evacuation instructions.

Simple example: a unit test can give the future risk engine fake input with `CAMERA_OFFLINE` and check that the output state is `UNKNOWN_DEGRADED`.

## 15. Known Unknowns

The following are not settled yet:

- Final numeric thresholds for `ELEVATED`, `HIGH`, and `CRITICAL`.
- Final site-specific reference lines or baseline definitions.
- Full reason-code list for every future component.
- Whether some reason codes should have severity levels.
- Whether reason-code ordering should be required.
- How reason codes should be translated for operator dashboards.
- Which reason codes should be public versus restricted.
- How long deprecated reason codes should remain supported.

These unknowns should become future issues, schemas, tests, or ADRs.

## Risk-State Rule Guidance

These are simple guidance rules for future implementation. They are not final algorithms.

- If the camera is offline or frames are stale, use `UNKNOWN_DEGRADED`, not `NORMAL`.
- If video quality is poor enough that the river cannot be judged, use `UNKNOWN_DEGRADED`.
- If water evidence is mildly higher but not persistent, the system may use `ELEVATED`.
- If water evidence is high and persistent, the system may use `HIGH`.
- If water evidence is severe or rapidly rising, the system may use `CRITICAL`.
- If evidence is unclear, say so with reason codes such as `LOW_CONFIDENCE`, `MODEL_UNCERTAIN`, or `INSUFFICIENT_HISTORY`.
- If an alert candidate is created, include `ALERT_CANDIDATE_CREATED` and `HUMAN_REVIEW_NEEDED`.
- If OpenFloodAI does not create an official warning, use `OFFICIAL_WARNING_NOT_CREATED` when that boundary needs to be visible.

Simple example: high water in one frame may be noise. High water plus several minutes of persistent rise is stronger evidence.

## Safety Boundaries

Reason codes explain evidence.

Reason codes are not official emergency instructions.

OpenFloodAI V1 should create alert candidates for review, not public evacuation orders.

Missing or bad camera data must never be treated as normal by default.

ML/vision output must remain evidence, not ground truth.

Simple example: `CRITICAL_WATER_EVIDENCE` means urgent human review is needed. It does not mean OpenFloodAI has officially ordered an evacuation.

## Architect Review Notes

Reviewed conceptually using the senior flood AI architect guidance.

Architecture decisions supported by these reason codes:

- Observation, risk assessment, alert candidates, and public warnings remain separate.
- Risk-engine outputs can explain state changes with auditable reason codes.
- Degraded evidence is explicit instead of silently becoming `NORMAL`.
- ML/vision reason codes are evidence only.
- Offline and privacy behavior can be recorded in the same audit trail.

Main architecture caution:

- Future code should not treat one reason code, one model output, one frame, or one camera as enough to issue an official public warning.

## QA Challenge Notes

Challenged conceptually using the senior flood QA guidance.

QA concerns to test in future stories:

- Missing reason codes should fail validation for risk-engine outputs.
- Camera/feed failure codes should produce visible degraded states.
- Risk-state rule tests should cover normal, elevated, high, critical, and unknown/degraded paths.
- Audit records should preserve reason codes, versions, timestamps, and evidence windows.
- Public-facing records should be checked so private location and camera-secret details do not leak.
- False alert candidates and missed dangerous events should both become measurable test concerns.

QA recommendation:

- This reason-code list is a useful V1 baseline, but it is not a production-safety claim. Future work needs schemas, validation tests, replay tests, and field evidence.

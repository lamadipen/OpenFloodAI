# OpenFloodAI V1 Data Contracts

## 1. Purpose

This document defines the first shared data records for OpenFloodAI V1.

The goal is simple: every part of the system should use the same words for the same things. A camera record, a risk result, and an alert candidate should mean the same thing everywhere.

This is a planning document. It does not add camera ingestion, ML, risk-engine logic, storage code, alerting code, dashboard code, or deployment code.

## 2. Plain-Language Summary

OpenFloodAI watches a river camera and creates records about what it sees.

Some records describe the place. Some describe the camera. Some describe video quality. Some describe water-change evidence. Some describe risk state and alert candidates.

Simple example: instead of writing “big water problem” in one place and “high river” somewhere else, the system should use a clear risk state like `HIGH` plus reason codes that explain why.

## Quick Reference Table

| Record Type | What It Means | Who Uses It |
| --- | --- | --- |
| `site` | The river monitoring place. | Operators, dashboard, audit records. |
| `camera` | One camera at a site. | Camera setup, health checks, event tracing. |
| `video_frame_metadata` | Information about a frame without storing the image itself. | Vision module, audit/replay tools. |
| `camera_health_output` | Whether the camera/video feed is usable. | Risk engine, operators, audit records. |
| `vision_signal_output` | What the ML/vision module thinks it sees. | Temporal analysis and risk engine. |
| `temporal_analysis_output` | How evidence changes across time. | Risk engine and audit review. |
| `risk_engine_input` | Evidence sent into the risk engine. | Risk engine tests and decision logic. |
| `risk_engine_output` | The selected risk state and reasons. | Alert candidate logic, audit records. |
| `alert_candidate` | A request for human or approved local review. | Operators or review workflow. |
| `event_audit_record` | Long-term record of an important event. | QA, debugging, field review. |
| `delivery_result` | Whether a notification attempt worked. | Audit and operations review. |

## State Meaning Table

| State | Simple Meaning |
| --- | --- |
| `USABLE` | The camera/video evidence is good enough to use. |
| `DEGRADED` | Evidence exists, but it is poor quality or partly blocked. |
| `UNKNOWN` | The system cannot tell what is happening. |
| `UNKNOWN_DEGRADED` | Risk must not be treated as normal because evidence is missing or unreliable. |

## 3. Data Contract Principles

V1 records should follow these principles:

- Records must be easy to understand.
- Required fields must be clearly separated from optional fields.
- Records must be traceable later for audit and review.
- Missing or unreliable evidence must be represented clearly.
- `UNKNOWN / DEGRADED` states must be explicit.
- ML output must be treated as evidence, not ground truth.
- Alert candidates must stay separate from official public warnings.
- Raw video and exact location data must be handled carefully.
- Camera credentials must never appear in records that may be logged or shared.

Simple example: if the camera is offline, the record should say the camera is offline. It should not leave the field blank and make people guess.

## 4. Common Fields Used Across Records

Many records should share these fields.

Required fields:

- `contract_version`: version of this data contract.
- `record_id`: unique ID for the record.
- `record_type`: kind of record, such as `camera_health_output` or `risk_engine_output`.
- `site_id`: stable ID for the river site.
- `camera_id`: stable ID for the camera, when the record is camera-specific.
- `timestamp`: time the record was created or observed, in ISO 8601 format.

Optional fields:

- `software_version`: version of OpenFloodAI that produced the record.
- `config_version`: version of the configuration used.
- `model_version`: version of the model used, if a model was used.
- `source_record_ids`: IDs of earlier records used to create this record.
- `notes`: short human-readable note.

Example:

```json
{
  "contract_version": "v1",
  "record_id": "event-20260827-bridge-01-0001",
  "record_type": "event_audit_record",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:00+05:45"
}
```

Privacy or safety concern:

- `site_id` and `camera_id` are needed for traceability.
- Exact location details should be referenced through site and camera records instead of repeated in every event.

## 5. Site Record

A site record describes the river monitoring location.

What it is used for:

- Helps operators know which river place needs attention.
- Links cameras, events, and alert candidates to one monitoring site.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `site`
- `site_id`
- `site_name`
- `river_name`
- `timezone`
- `country`
- `location_visibility`

Optional fields:

- `nearby_landmark`
- `municipality`
- `district`
- `province_or_state`
- `latitude`
- `longitude`
- `coordinate_precision`
- `public_location_label`
- `restricted_location_notes`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "site-record-bridge-01",
  "record_type": "site",
  "site_id": "site-bridge-01",
  "site_name": "Bridge 01 River Watch",
  "river_name": "Example River",
  "timezone": "Asia/Kathmandu",
  "country": "Nepal",
  "location_visibility": "restricted",
  "nearby_landmark": "Old footbridge"
}
```

Privacy or safety concern:

- Public views may show `river_name` or `nearby_landmark`.
- Exact coordinates should be restricted when they expose homes, private property, camera positions, or critical infrastructure.

## 6. Camera Record

A camera record describes one camera at a site.

What it is used for:

- Helps the system know which camera produced a frame, signal, or event.
- Stores non-secret camera setup details.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `camera`
- `site_id`
- `camera_id`
- `camera_name`
- `camera_status`
- `timezone`

Optional fields:

- `stream_type`, such as `file`, `rtsp`, or `cctv`
- `view_description`
- `installation_notes`
- `expected_scene`
- `public_view_allowed`
- `has_people_or_road_in_view`
- `retention_policy_id`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "camera-record-bridge-01-main",
  "record_type": "camera",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "camera_name": "Main bridge camera",
  "camera_status": "active",
  "timezone": "Asia/Kathmandu",
  "stream_type": "rtsp",
  "has_people_or_road_in_view": true
}
```

Privacy or safety concern:

- Camera URLs, usernames, passwords, and tokens must not be stored in general camera records.
- Secrets should be stored only in a protected secrets system.

## 7. Location and GPS Fields

Location fields help people understand where an event happened.

Required traceability fields:

- `site_id`
- `camera_id`

Optional location fields:

- `site_name`
- `river_name`
- `nearby_landmark`
- `municipality`
- `district`
- `province_or_state`
- `country`
- `latitude`
- `longitude`
- `coordinate_precision`
- `timezone`
- `location_visibility`

Recommended values for `location_visibility`:

- `public`: safe to show publicly.
- `restricted`: only trusted users should see it.
- `private`: highly sensitive; do not expose in public records.

Example:

```json
{
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "river_name": "Example River",
  "nearby_landmark": "Old footbridge",
  "latitude": 27.7172,
  "longitude": 85.324,
  "coordinate_precision": "approximate",
  "location_visibility": "restricted"
}
```

Privacy or safety concern:

- Exact GPS coordinates are optional.
- Exact GPS coordinates and camera placement details should not be public by default.
- Public records should use a coarse location, such as river name or nearby landmark, when exact coordinates are not needed.

Simple example: the public may need to know “near Old footbridge.” They may not need the exact camera pole location.

## 8. Video Frame Metadata Record

A video frame metadata record describes a frame without storing the image itself.

What it is used for:

- Helps trace which frame or time window produced later signals.
- Helps detect stale or delayed frames.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `video_frame_metadata`
- `site_id`
- `camera_id`
- `timestamp`
- `frame_id`

Optional fields:

- `frame_width`
- `frame_height`
- `frame_rate`
- `source_timestamp`
- `frame_hash`
- `clip_reference`
- `snapshot_reference`
- `dropped_frame_count`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "frame-meta-000123",
  "record_type": "video_frame_metadata",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:00+05:45",
  "frame_id": "frame-000123",
  "frame_width": 1280,
  "frame_height": 720
}
```

Privacy or safety concern:

- This record should point to a clip or snapshot only when storage is allowed by site policy.
- A frame hash can help detect repeated frames without storing the image.

## 9. Camera / Feed Health Output

A camera/feed health output says whether the video is usable.

What it is used for:

- Prevents the system from treating missing or bad video as normal river conditions.
- Gives the risk engine input quality evidence.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `camera_health_output`
- `site_id`
- `camera_id`
- `timestamp`
- `input_quality_state`
- `is_usable`
- `reason_codes`

Optional fields:

- `frame_id`
- `evidence_window`
- `visibility_score`
- `stale_frame_detected`
- `obstruction_detected`
- `failure_detail`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "health-bridge-01-140500",
  "record_type": "camera_health_output",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:00+05:45",
  "input_quality_state": "DEGRADED",
  "is_usable": false,
  "reason_codes": ["STALE_FRAMES"]
}
```

Privacy or safety concern:

- Failure messages should not include camera passwords, tokens, or private stream URLs.

## 10. Vision / ML Signal Output

A vision/ML signal output contains visual evidence from the image.

What it is used for:

- Describes what the vision module thinks it sees.
- Sends evidence to temporal analysis and the risk engine.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `vision_signal_output`
- `site_id`
- `camera_id`
- `timestamp`
- `input_quality_state`
- `signal_state`
- `reason_codes`

Optional fields:

- `frame_id`
- `model_version`
- `water_coverage_ratio`
- `relative_level`
- `confidence`
- `uncertainty`
- `region_reference`
- `debug_artifact_reference`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "vision-bridge-01-140500",
  "record_type": "vision_signal_output",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:00+05:45",
  "input_quality_state": "USABLE",
  "signal_state": "WATER_COVERAGE_INCREASED",
  "water_coverage_ratio": 0.72,
  "confidence": 0.81,
  "reason_codes": ["WATER_REGION_VISIBLE"]
}
```

Privacy or safety concern:

- This is evidence, not ground truth.
- Debug images should follow the site retention policy.

Simple example: the vision record may say, “water covers about 72 percent of the watched river area.” It does not say, “evacuate.”

## 11. Temporal Analysis Output

A temporal analysis output summarizes change across time.

What it is used for:

- Helps avoid decisions based on one odd frame.
- Shows whether water evidence persisted or changed quickly.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `temporal_analysis_output`
- `site_id`
- `camera_id`
- `timestamp`
- `evidence_window`
- `temporal_state`
- `reason_codes`

Optional fields:

- `source_record_ids`
- `rate_of_change`
- `persistence_duration_seconds`
- `missing_frame_count`
- `confidence`
- `uncertainty`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "temporal-bridge-01-140500",
  "record_type": "temporal_analysis_output",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:00+05:45",
  "evidence_window": {
    "start": "2026-08-27T13:59:00+05:45",
    "end": "2026-08-27T14:05:00+05:45",
    "duration_seconds": 360
  },
  "temporal_state": "SUSTAINED_RISE",
  "reason_codes": ["PERSISTENT_WATER_INCREASE"]
}
```

Privacy or safety concern:

- Time windows must be accurate enough for audit.
- Bad clocks should produce degraded time-integrity records.

## 12. Risk-Engine Input

A risk-engine input is the package of evidence sent to the risk engine.

What it is used for:

- Keeps the risk engine separate from the ML module.
- Allows tests to pass fake evidence to the risk engine without using a real camera.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `risk_engine_input`
- `site_id`
- `camera_id`
- `timestamp`
- `config_version`
- `input_quality_state`
- `component_signals`
- `evidence_window`

Optional fields:

- `source_record_ids`
- `model_version`
- `confidence`
- `uncertainty`
- `operator_context`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "risk-input-bridge-01-140500",
  "record_type": "risk_engine_input",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:00+05:45",
  "config_version": "config-2026-08-27-a",
  "input_quality_state": "USABLE",
  "component_signals": {
    "water_coverage_ratio": 0.72,
    "temporal_state": "SUSTAINED_RISE"
  },
  "evidence_window": {
    "start": "2026-08-27T13:59:00+05:45",
    "end": "2026-08-27T14:05:00+05:45",
    "duration_seconds": 360
  }
}
```

Privacy or safety concern:

- The input should reference site and camera IDs instead of repeating exact restricted location details.

## 13. Risk-Engine Output

A risk-engine output is the risk state and explanation produced by the risk engine.

What it is used for:

- Tells the rest of the system what risk state was selected.
- Explains why the state changed or stayed the same.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `risk_engine_output`
- `site_id`
- `camera_id`
- `timestamp`
- `risk_state`
- `reason_codes`
- `evidence_window`
- `config_version`

Optional fields:

- `source_record_ids`
- `previous_risk_state`
- `confidence`
- `uncertainty`
- `recommended_next_step`

Allowed initial values for `risk_state`:

- `NORMAL`
- `ELEVATED`
- `HIGH`
- `CRITICAL`
- `UNKNOWN_DEGRADED`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "risk-output-bridge-01-140500",
  "record_type": "risk_engine_output",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:00+05:45",
  "risk_state": "HIGH",
  "previous_risk_state": "ELEVATED",
  "reason_codes": ["SUSTAINED_RISE", "HIGH_WATER_COVERAGE"],
  "config_version": "config-2026-08-27-a",
  "evidence_window": {
    "start": "2026-08-27T13:59:00+05:45",
    "end": "2026-08-27T14:05:00+05:45",
    "duration_seconds": 360
  }
}
```

Privacy or safety concern:

- A risk-engine output is not an official public warning.

## 14. Alert-Candidate Record

An alert-candidate record says that a human or approved local process should review the situation.

What it is used for:

- Routes a concerning risk state to review.
- Keeps alert candidates separate from official public warnings.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `alert_candidate`
- `site_id`
- `camera_id`
- `timestamp`
- `risk_state`
- `reason_codes`
- `evidence_window`
- `input_quality_state`
- `software_version`
- `config_version`

Optional fields:

- `model_version`
- `component_signals`
- `confidence`
- `uncertainty`
- `candidate_status`
- `operator_notes`
- `delivery_result_id`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "candidate-bridge-01-140500",
  "record_type": "alert_candidate",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:00+05:45",
  "risk_state": "HIGH",
  "reason_codes": ["SUSTAINED_RISE", "HIGH_WATER_COVERAGE"],
  "input_quality_state": "USABLE",
  "software_version": "0.1.0",
  "config_version": "config-2026-08-27-a",
  "evidence_window": {
    "start": "2026-08-27T13:59:00+05:45",
    "end": "2026-08-27T14:05:00+05:45",
    "duration_seconds": 360
  },
  "candidate_status": "needs_review"
}
```

Privacy or safety concern:

- This record must not say an evacuation is required.
- Public-warning decisions stay outside OpenFloodAI V1 authority during development and early pilots.

Simple example: it can say “please review this camera now.” It should not say “everyone must leave now.”

## 15. Event / Audit Record

An event/audit record is the long-term record of something important that happened.

What it is used for:

- Supports later review, debugging, field-pilot analysis, and accountability.
- Helps answer why an alert candidate was or was not created.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `event_audit_record`
- `site_id`
- `camera_id`
- `timestamp`
- `event_type`
- `software_version`
- `config_version`
- `input_quality_state`
- `risk_state`
- `reason_codes`
- `evidence_window`

Optional fields:

- `model_version`
- `source_record_ids`
- `component_signals`
- `alert_action_taken`
- `delivery_result`
- `local_storage_state`
- `public_fields`
- `restricted_fields`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "event-bridge-01-140500",
  "record_type": "event_audit_record",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:00+05:45",
  "event_type": "risk_state_changed",
  "software_version": "0.1.0",
  "config_version": "config-2026-08-27-a",
  "input_quality_state": "USABLE",
  "risk_state": "HIGH",
  "reason_codes": ["SUSTAINED_RISE", "HIGH_WATER_COVERAGE"],
  "evidence_window": {
    "start": "2026-08-27T13:59:00+05:45",
    "end": "2026-08-27T14:05:00+05:45",
    "duration_seconds": 360
  },
  "alert_action_taken": "alert_candidate_created"
}
```

Privacy or safety concern:

- Use site/camera references instead of copying exact GPS details into every event.
- Raw video references should be included only when allowed by site policy.

## 16. Delivery Result Record

A delivery result record is used if a notification is attempted.

What it is used for:

- Records whether an alert candidate was delivered to an operator or review channel.
- Supports audit when delivery fails.

Required fields:

- `contract_version`
- `record_id`
- `record_type`: `delivery_result`
- `site_id`
- `camera_id`
- `timestamp`
- `alert_candidate_id`
- `delivery_channel`
- `delivery_status`

Optional fields:

- `recipient_role`
- `attempt_count`
- `provider_message_id`
- `failure_reason`
- `acknowledged_at`
- `acknowledged_by_role`

Example:

```json
{
  "contract_version": "v1",
  "record_id": "delivery-bridge-01-140501",
  "record_type": "delivery_result",
  "site_id": "site-bridge-01",
  "camera_id": "camera-bridge-01-main",
  "timestamp": "2026-08-27T14:05:01+05:45",
  "alert_candidate_id": "candidate-bridge-01-140500",
  "delivery_channel": "operator_dashboard",
  "delivery_status": "delivered",
  "recipient_role": "operator"
}
```

Privacy or safety concern:

- Avoid storing personal phone numbers, emails, or names unless a future access-control design allows it.
- Prefer role labels such as `operator` when possible.

## 17. Offline / Local Storage Expectations

The edge node should store important records locally when cloud or network access is unavailable.

Expected local records:

- Camera/feed health outputs.
- Vision/ML signal outputs when useful for audit.
- Temporal analysis outputs when useful for audit.
- Risk-engine outputs.
- Alert-candidate records.
- Delivery results, if notification is attempted.
- System degraded/failure events.

During network loss:

- Local detection can continue if video, power, storage, and local configuration are available.
- Records should be queued locally for later upload if upload is configured.
- Upload may resume after connectivity returns.

During low disk:

- The system should report degraded storage health.
- It should preserve the most important audit records where possible.
- It should avoid claiming that audit storage is healthy.

Simple example: if the internet is down, the edge node should still remember that a `HIGH` alert candidate happened at 14:05.

## 18. Privacy and Sensitive-Data Rules

OpenFloodAI should avoid storing sensitive data unless there is a clear reason.

Rules:

- Raw video retention must be configurable by site.
- The default should avoid storing raw video unless needed for review, research, or debugging.
- Short clips or snapshots around important events should follow site retention policy.
- If people, homes, roads, vehicles, or license plates appear in view, masking or cropping should be considered before public deployment.
- Camera URLs, usernames, passwords, and tokens must not be written into logs or general records.
- Exact GPS coordinates are optional and should be restricted by default.
- Public event fields should avoid exact coordinates and camera placement details.
- Restricted fields should require access control in future implementation.

Recommended split:

- Public fields: coarse site name, river name, broad risk state, general timestamp, non-sensitive reason codes.
- Restricted fields: exact GPS, camera placement notes, raw video references, private contact details, sensitive infrastructure details.

Simple example: a public dashboard might show “Example River near Old footbridge: HIGH candidate.” It should not show the camera password or exact camera pole location.

## 19. Versioning Rules

Records should include versions so future reviewers can understand how the record was produced.

Version fields:

- `contract_version`: the data contract version, such as `v1`.
- `software_version`: the OpenFloodAI software version.
- `config_version`: the configuration version used for thresholds and settings.
- `model_version`: the model version, if a model is used.

Why this matters:

- A future reviewer can see which code, model, and configuration produced an event.
- Tests can replay old events with the correct versions.
- If a model or config was wrong, maintainers can find affected records.

Simple example: if a bad config caused too many false alert candidates, `config_version` helps identify which events used that config.

## 20. Validation and Testability Expectations

Future implementation stories should test these contracts.

Validation expectations:

- Required fields are present.
- `record_type` has an expected value.
- `risk_state` uses the allowed V1 values.
- Timestamps are valid and include timezone information.
- `site_id` and `camera_id` are present for camera-specific records.
- Required version fields are present where relevant.
- `UNKNOWN_DEGRADED` is allowed and testable.
- Sensitive fields do not appear in public records or logs.

Future test examples:

- A risk-engine output without `reason_codes` should fail validation.
- An alert candidate without `evidence_window` should fail validation.
- A camera-offline event should use `UNKNOWN_DEGRADED`, not `NORMAL`.
- A public event record should not include a camera password or exact private GPS field.
- A delivery result should record failure if notification delivery fails.

Machine-readable schema:

- `schemas/event.schema.json` provides a first simple schema for event/audit records.
- Example records live in `examples/events/`.
- Validation tests live in `tests/schema/`.
- The schema is intentionally focused on event/audit records and should grow only when implementation stories need stricter validation.

## 21. Known Unknowns

The following are not settled yet:

- Final field names may change after implementation starts.
- The exact list of reason codes is not defined yet.
- The exact evidence-window format may need adjustment during replay testing.
- Public versus restricted field rules need a full access-control design.
- Raw video, snapshot, and clip reference formats are not finalized.
- Model metadata fields may change after model packaging is designed.
- Location privacy rules may need site-specific policy review.
- Offline queue ordering and retry behavior are not defined in detail yet.
- Final JSON schemas for every record type are not created yet.

These unknowns should become future issues, ADRs, schemas, or tests.

Future issue candidates:

- Add stricter schemas for more record types.
- Add a public-event schema that blocks exact GPS, camera secrets, and private details from public output.

Reason-code details now live in [reason-codes.md](reason-codes.md).

## Architect Review Notes

Reviewed conceptually using the senior flood AI architect guidance.

Architecture decisions supported by these contracts:

- Events are traceable to site, camera, time, software, config, model, evidence, risk state, and reason codes.
- Risk-engine records are separate from vision/ML records.
- Alert candidates are separate from official public warnings.
- Degraded and unknown states are explicit.
- Raw video and exact location fields are handled as sensitive data.

Main architecture caution:

- Do not let future implementation hide sensitive details in logs or repeat exact GPS and camera-placement details in every event.

## QA Challenge Notes

Challenged conceptually using the senior flood QA guidance.

QA concerns to test in future stories:

- Missing required fields must fail validation.
- Bad or missing timestamps must be visible because event order matters.
- Camera-offline, stale-frame, and obstruction records must clearly become degraded evidence.
- Risk-engine tests must use fake inputs so they do not depend on ML.
- Event replay must preserve software, config, model, and contract versions.
- Public records must be checked for sensitive fields.
- Delivery failure must be recorded when notification is attempted.

QA recommendation:

- These contracts are a good V1 starting point, but they are not complete production schemas. Future work should add stricter schemas, validation tests, reason-code lists, and replay evidence.

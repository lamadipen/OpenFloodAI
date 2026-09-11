# OpenFloodAI V1 Product Requirements

## 1. Product Mission

OpenFloodAI V1 helps people watch river conditions using a fixed camera.

It looks for visual signs that water may be rising fast or becoming unusually high. When the evidence stays concerning over time, the system creates an alert candidate for a human or operator to review.

OpenFloodAI V1 is warning-support software. It does not make official evacuation decisions by itself.

Simple example: if a camera usually sees a riverbank, but now the water covers much more of that bank for several minutes, OpenFloodAI may create an alert candidate.

## 2. Problem Statement

Many communities cannot afford expensive river monitoring equipment at every risky location. Some places may already have a camera, a low-cost edge device, and limited internet.

OpenFloodAI V1 tries to help by using camera video to notice dangerous-looking river changes earlier and more consistently.

The main problem is not just seeing water. The system must also handle real-world problems such as rain, fog, darkness, a dirty lens, lost internet, or a camera that stops working.

Simple example: if the camera freezes and keeps showing the same old image, the system should not pretend the river is normal. It should mark the situation as degraded or unknown.

## 3. Target Users and Stakeholders

Primary users:

- Local flood monitoring teams
- Municipal or community emergency staff
- River watchers and trained volunteers
- Operators who review alert candidates

Other stakeholders:

- People living near rivers
- Local government and disaster response teams
- NGOs or researchers supporting flood-risk projects
- System maintainers and open-source contributors

OpenFloodAI should be understandable to technical and non-technical users. A user should be able to see why an alert candidate was created.

## 4. Primary V1 Use Case

The primary V1 use case is monitoring one fixed camera pointed at one river area.

Flow:

```text
Fixed Camera / CCTV
-> Video Stream
-> Camera Health Checks
-> Water Detection
-> Relative Water-Level or Water-Coverage Change
-> Temporal Analysis
-> Risk Engine
-> Alert Candidate
-> Notification or Operator Layer
```

Simple example: a camera watches a bridge. Over time, the system sees that water is covering more of the bridge support area than usual. If that change lasts long enough, the system raises the risk state and creates an alert candidate with the reason.

## 5. Functional Requirements

OpenFloodAI V1 must:

- Support prerecorded video before live camera streams.
- Treat live RTSP/CCTV stream support as planned for V1 and track it as a separate implementation story.
- Check whether the camera feed is usable.
- Detect possible river or water regions in the image.
- Estimate relative water-level or water-coverage change over time.
- Look for fast changes, not only a single high-looking frame.
- Combine evidence over time before changing risk state.
- Create explainable risk states with reason codes.
- Include the evidence window used for each risk-state change.
- Create alert candidates with reason codes and supporting evidence.
- Record events so people can review what happened later.
- Continue core detection on the edge device during cloud/network loss when video, power, storage, and local configuration are available.
- Support different fixed cameras when their video quality and viewpoint are suitable for river monitoring.

Simple example: the system should be able to say, “Risk is HIGH because water coverage increased quickly and stayed high for several minutes,” instead of only saying, “Alert.”

## 6. Non-Functional Requirements

OpenFloodAI V1 should be:

- Edge-first: core detection should run near the camera.
- Low-cost: it should aim to work on affordable hardware where practical.
- Reliable: it should show degraded states instead of failing silently.
- Explainable: operators should see the evidence behind an alert candidate.
- Auditable: events should include time, camera, version, state, and reason.
- Maintainable: components should be separated and independently testable.
- Privacy-aware: it should avoid unnecessary storage of sensitive imagery.
- Cloud-optional for core detection: internet loss should not stop local monitoring when the edge device still has video and power.

Simple example: if internet goes down but the camera and edge device still work, local detection should continue and store events for later upload if configured.

## 7. V1 System Boundary

OpenFloodAI V1 includes:

- Camera/video ingestion for fixed cameras or prerecorded video.
- Camera and feed health checks.
- Vision-based water-region and change signals.
- Temporal aggregation of visual evidence.
- A risk engine that can be tested separately from the ML model.
- Alert-candidate creation.
- Event recording for review and audit.
- Basic notification or operator handoff layer.

OpenFloodAI V1 does not include:

- Official public warning authority.
- Autonomous evacuation decisions.
- Weather forecasting.
- Hydraulic simulation.
- Nationwide flood monitoring.

Boundary example: OpenFloodAI can say, “This camera shows signs of critical river change.” It cannot say, “Evacuate this town now” as an official authority.

## 8. In-Scope Capabilities

The following are in scope for V1:

- Prerecorded video.
- Fixed-camera streams, tracked as a separate V1 implementation story.
- River or water-region detection.
- Relative water-level or water-coverage change estimation.
- Rapid rise or rate-of-change analysis.
- Camera/feed health checks.
- Obstruction detection, such as a blocked or dirty lens.
- Stale-frame detection.
- Loss-of-feed detection.
- Temporal evidence aggregation.
- Explainable risk states.
- Alert candidates with reason codes.
- Low-cost edge inference.
- Offline or degraded operation for core detection.
- Event recording for analysis and audit.
- Camera and hardware flexibility when video quality, viewpoint, and edge-device capacity are suitable.

Simple example: if heavy rain blurs the image so the river cannot be seen clearly, the system should report degraded confidence instead of guessing.

## 9. Explicitly Out-of-Scope Capabilities

The following are out of scope for V1:

- Rainfall or weather forecasting.
- Flood prediction hours or days ahead.
- Satellite flood mapping.
- Dam management.
- Hydraulic simulation.
- Exact river-discharge measurement from video alone.
- Nationwide monitoring.
- Autonomous evacuation decisions.
- Official public-warning decisions made directly by ML.
- Facial identification.
- Person tracking.
- Vehicle or license-plate recognition.
- Training a large foundation model from scratch.

Simple example: OpenFloodAI V1 may notice that visible water is rising in a camera view. It should not predict tomorrow's flood level from rainfall maps.

## 10. Risk-State Model

OpenFloodAI V1 uses these initial risk states:

- `NORMAL`: the river appears stable and the camera is usable.
- `ELEVATED`: the river shows early concerning change.
- `HIGH`: the river shows strong concerning change.
- `CRITICAL`: the river shows sustained, dangerous-looking change.
- `UNKNOWN / DEGRADED`: the system cannot make a reliable assessment.

The risk engine must be testable without the ML model. It should accept evidence, apply rules, and produce a risk state and reasons.

Risk-state transitions must be based on:

- Water coverage or water-level change over time.
- Rate of change.
- Camera/feed health.
- Confidence or uncertainty.
- Persistence across multiple frames or time windows.

The exact numeric thresholds are unknown for now. They must be set after dataset research, baseline experiments, and field evidence.

Simple example: if the camera is offline, the state should become `UNKNOWN / DEGRADED`, not `NORMAL`.

## 11. Alert-Candidate Concept

An alert candidate is a message that says, “This may need attention.”

It is not the same as an official public warning. A human, operator, or approved local process must decide what action to take.

Each alert candidate should record:

- Site/camera ID.
- Timestamp.
- Software version.
- Model version, if a model is used.
- Config version.
- Input quality state.
- Risk state.
- Reason codes.
- Main component signals.
- Confidence or uncertainty.
- Evidence window, such as sustained water-coverage change over several minutes.
- System health state.
- Alert action taken.
- Delivery result, if notification is attempted.

Simple example: “Camera bridge-01 is HIGH because water coverage increased quickly for 6 minutes. Camera feed is healthy.”

## 12. Edge and Offline Requirements

OpenFloodAI V1 should run core detection near the camera.

The edge device should:

- Keep processing video if cloud access is lost but local video, power, storage, and local configuration are available.
- Store important events locally when it cannot send them right away.
- Report degraded status when camera, power, disk, clock, or network problems affect reliability.
- Use local cached configuration when cloud configuration is not reachable.
- Avoid depending on a cloud service for the basic act of detecting concerning visual change.

During cloud/network loss:

- Local detection should continue if video, power, storage, and local configuration are available.
- Events should be stored locally.
- Upload may resume after connectivity returns.

During camera loss, unusable video, low disk, bad clock, or missing configuration:

- The system must show `UNKNOWN / DEGRADED`.
- It must not silently report `NORMAL`.
- It must record the failure reason where possible.

Simple example: if the internet is down for 30 minutes, the edge device should keep watching the river and save local events. When the internet returns, it may upload the saved events if configured.

## 13. Initial Success Metrics

V1 must define and measure metrics before setting final numeric release thresholds.

Initial metrics:

- Dangerous-event recall: how often the system catches real dangerous events.
- False alerts per camera-day: how often it creates unnecessary alert candidates.
- Time-to-detect: how long it takes to notice a dangerous change.
- Edge inference latency: how long the vision step takes on target hardware.
- End-to-end pipeline latency: how long from frame capture to alert candidate.
- Camera-health detection effectiveness: how well it detects camera problems.
- System uptime: how often monitoring is available.
- Offline/degraded behavior: whether the system behaves clearly during outages.
- Slice performance: how it performs in day, night, rain, fog, glare, obstruction, and other hard conditions.

No final numeric gates are set in this document. Those should come after dataset research, baseline experiments, and field evidence.

Simple example: we should first measure false alerts per camera-day. We should not invent a target like “less than X false alerts” before seeing real data.

## 14. Safety Assumptions

Safety assumptions for V1:

- Missing a dangerous event is a critical failure.
- Too many false alerts are also serious because people may stop trusting the system.
- ML output is evidence, not ground truth.
- One frame, one model, or one signal must not directly create an official public warning.
- Initial field use should be shadow mode or decision support.
- Degraded states must be visible and auditable.
- A human or approved local process remains responsible for public warning decisions.

Simple example: if one single frame looks flooded because of glare, that frame alone should not trigger a public warning.

## 15. Failure and Degraded-State Expectations

OpenFloodAI V1 must handle failure openly.

The system should detect and report:

- Camera offline.
- Frozen or stale frames.
- Blocked or dirty lens.
- Heavy rain, fog, glare, darkness, or poor visibility.
- Camera shake or changed camera angle.
- Dropped or corrupt video frames.
- Edge device restart.
- Low disk space.
- Network loss and recovery.
- Cloud service unavailable.
- Bad or missing configuration.
- Clock or timestamp problems.

Expected behavior:

- Do not silently show `NORMAL` when evidence is missing or unreliable.
- Use `UNKNOWN / DEGRADED` when the system cannot judge river conditions.
- Record enough information for later review.
- Recover when the failed dependency becomes healthy again.

Simple example: if leaves cover the camera lens, the system should say the camera view is obstructed instead of claiming the river is safe.

## 16. Privacy Considerations

OpenFloodAI should collect only what is needed for river monitoring.

Privacy expectations:

- Avoid face, person, vehicle, or license-plate recognition.
- Raw video retention must be configurable by site.
- The default should avoid storing raw video unless needed for review, research, or debugging.
- Prefer storing events, summaries, and cropped river-focused evidence where practical.
- Protect camera URLs, credentials, and location details.
- Do not write camera credentials into logs.
- Document who can access stored video or event evidence.
- Consider masking or cropping before public deployment if people, roads, homes, vehicles, or license plates appear in view.

Simple example: if a camera view includes a road near the river, the system should not analyze license plates. The project is about flood risk, not tracking people or vehicles.

## 17. Known Unknowns

The following are not settled yet:

- Which camera types and edge devices are best for low-cost pilots.
- Minimum video quality needed for reliable detection.
- How to define site-specific normal water coverage.
- How much historical video is needed for useful baseline experiments.
- How risk thresholds should be tuned for different rivers.
- Which visual methods work best across day, night, rain, fog, glare, and debris.
- How much event evidence should be stored without creating privacy risk.
- Which notification channels are practical for early pilots.
- What final numeric release gates should be.

These unknowns should become research tasks, experiments, ADRs, or test plans before production claims are made.

## 18. Future Capabilities

Possible future capabilities after V1:

- Multi-camera support for one site.
- Sensor fusion with river gauges, rainfall sensors, or official hydrology data.
- Dashboard for fleet monitoring.
- Stronger notification workflows with acknowledgement and escalation.
- Historical-event replay test harness.
- Model comparison and rollback tooling.
- Site calibration tools.
- Advanced privacy masking.
- Public-facing status page controlled by local authorities.

Future example: a later version may combine a camera signal with an official river gauge. V1 should not require that extra sensor to work.

## Testability Notes

Future implementation stories should include tests for:

- Normal river conditions.
- Gradual rise.
- Rapid rise.
- High or flood-like water.
- Water receding.
- Rain, fog, darkness, glare, and obstruction.
- Frozen frames.
- Dropped or corrupt frames.
- Camera offline.
- Network loss and recovery.
- Low disk.
- Bad clock or time.
- Bad or missing configuration.

Each major requirement should be linked to a future test, replay scenario, or field-pilot evidence item.

Simple example: before trusting the system in a pilot, we should replay videos of normal water, fast-rising water, and a blocked camera to check that each case produces the expected state.

## Architect Review Notes

Reviewed using the senior flood AI architect guidance.

Key decisions:

- Observation, risk assessment, and public warning are separated.
- The risk engine remains independently testable from ML.
- Edge operation is required for core detection where practical.
- Degraded states are part of normal system behavior, not an afterthought.
- The document avoids unsupported production-safety claims.

Main architecture risk:

- If alert candidates are later connected directly to public warning tools without human review, the system boundary would be violated.

## QA Challenge Notes

Independently challenged using the senior flood QA guidance.

Requirements that need future test evidence:

- Dangerous-event recall must be measured at event level, not only frame level.
- False alerts must be measured per camera-day.
- Offline and degraded behavior must be tested with failure injection.
- Camera-health checks must include stale frames, obstruction, poor visibility, and feed loss.
- Critical condition slices must include day, night, rain, fog, glare, obstruction, and camera shake.

QA concern:

- Many V1 requirements depend on future datasets, replay tests, and field pilots. This document records that uncertainty instead of hiding it.

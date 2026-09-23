# Decision: Modular Evidence and Plugin Architecture

Status: agreed architecture direction; incremental implementation pending. This
is a documentation-only decision, not a claim that a plugin API or every
capability below already exists.

## Context and decision

**OpenFloodAI is an evidence-fusion platform, not a single-model application.**
Models, detectors, sensors, and external data sources contribute evidence through
stable contracts. The core owns the pipeline and completes a reviewable result
using the evidence available. No plugin owns the pipeline or issues warnings.

This extends the [V1 architecture](v1-architecture.md),
[data contracts](data-contracts.md), and [reason codes](reason-codes.md).
Existing record formats remain authoritative until a separately scoped change
introduces an adapter or contract revision. The fields below are a target
contract, not a migration of saved records.

Decision drivers are camera-first operation, low-cost edge deployment, honest
uncertainty, repeatable review, and replacing individual capabilities without
rewriting ingestion, storage, risk logic, or the review workflow.

Options considered:

- A single model that owns the end-to-end decision: initially simple, but couples
  availability and output meaning to that model and obscures missing evidence.
- A stable core with small evidence adapters: selected because capabilities can
  evolve independently while preserving auditability and degraded outcomes.
- A large generic plugin framework: deferred because current workflows do not
  justify discovery infrastructure, a marketplace, or a general execution platform.

## Stable core pipeline

```text
Camera / local video / image sequence
                  |
                  v
        Core ingestion + time windows
                  |
                  v
    Core input validation + health status
                  |
       +----------+------------+----------------+
       |                       |                |
       v                       v                v
 Observation plugins     Quality plugins   Context plugins
 pixel change            camera health     riverbank reference
 water segmentation      reference quality USGS gauge
       |                       |                |
       +-----------------------+----------------+
                               |
                               v
              Local evidence store + availability records
                               |
                               v
             Evidence fusion / temporal preparation
                               |
                               v
                 Deterministic risk engine
                               |
                               v
             Saved result + reasons + evidence links
                               |
                               v
                 Human review / warning support
```

The core owns scheduling, input identity and time integrity, contract validation,
capability status, local evidence persistence, fusion, deterministic risk policy,
and review-result assembly. Basic input checks and recording unavailable evidence
remain core responsibilities even when no optional quality plugin is enabled.
Specialized quality assessments can be added as plugins.

Plugins receive explicit inputs and configuration and return evidence or a
structured unavailable/failure outcome. They do not change other plugins, mutate
risk state, or control whether the pipeline reaches review. A plugin needing
another capability declares that dependency; if it is absent, only the dependent
capability becomes unavailable.

The completion guarantee applies to optional plugin loss while the core and local
resources remain functional. Power loss, unusable storage, or a core failure can
prevent completion; these must never be presented as a successfully saved result.

## Plugin families and concrete examples

| Family | Responsibility | Examples and limits |
| --- | --- | --- |
| Observation | Describe a measured change or feature in the scene. | Existing pixel-change logic is the first adapter candidate. Its score measures appearance change, not confirmed water rise or calibrated depth. Future water segmentation contributes masks or coverage, not a flood verdict. |
| Quality | Describe whether an input or observation is usable. | Existing camera-health checks contribute quality evidence. Later checks can cover obstruction, movement, glare, or reference visibility; do not imply all are implemented today. |
| Context | Supply reference information that helps interpret observations. | A human-confirmed riverbank/normal-waterline reference supplies site geometry and baseline provenance. A USGS gauge adapter supplies optional external level/trend context with station, units, timestamps, and site association. |

A riverbank reference is Context; checking whether it is visible and aligned is
Quality; measuring water relative to that reference is Observation. Preserve
these meanings even if one small module initially performs more than one role.
A missing or unconfirmed reference cannot silently become a valid normal baseline.

USGS observations may represent another location or time. Record the association
and any known limitations; disagreement with camera evidence remains visible.
Gauge context is neither a requirement for the camera MVP nor automatic ground
truth for the camera scene. Future segmentation remains subject to the existing
[ML readiness gate](../product/ml-readiness.md).

## Common evidence contract

Each adapter should eventually emit a small versioned envelope around its typed
payload, reusing existing records where possible. These are conceptual field
names; introduce concrete schemas only when a roadmap step needs them.

| Field | Meaning and rule |
| --- | --- |
| `contract_version`, `record_id`, `record_type` | Identify the schema and immutable evidence record. |
| `plugin_id`, `plugin_version`, `plugin_family` | Identify the producer and its Observation, Quality, or Context role. |
| `site_id`, `camera_id` | Identify the site and camera when applicable; gauge evidence also identifies its source station. |
| `timestamp`, `window_start`, `window_end`, `produced_at` | Distinguish observation time/window from processing time; use explicit time zones and record untrusted timing. |
| `evidence_type`, `value`, `units` | State what was measured and its meaning. Values may be scalar, structured, or references to local artifacts. Missing is not zero. |
| `status` | Distinguish available, disabled, unavailable, failed, stale, and invalid outcomes. These are proposed availability labels, not new risk states. |
| `confidence` | Producer confidence, including its meaning/calibration, or explicit unknown. Do not invent confidence for a deterministic score or compare unrelated model scores as probabilities. |
| `quality` | Usability of the input and evidence, using existing quality vocabulary where applicable. Confidence does not override poor quality. |
| `reason_codes` | Explain the outcome using existing codes when applicable; new codes need a deliberate contract update. Preserve distinctions between pipeline codes and human sample-review reasons. |
| `provenance` | Source record/input IDs, baseline/reference IDs, artifact references or hashes, software/config/model versions as applicable, preprocessing version, and source identity. |

Identity, status, timing, quality, and reasons must still be recorded when no
measurement exists. Unavailable outcomes have no fabricated measurement or
confidence. Provenance should let a reviewer reproduce the comparison without
embedding credentials or duplicating private imagery.

## Capability discovery and independent failure

Start with an explicit local configuration/list of known adapters. At startup,
check configured capabilities, compatible contract versions, required inputs,
local model assets, and dependencies. Record enabled, disabled, ready, and
unavailable capabilities with reasons. Refresh actual outcomes per time window;
startup availability does not guarantee a usable result later.

The core requests evidence by capability and contract, rather than by a particular
model class. A small adapter translates implementation-specific output into that
contract. No dynamic installation, runtime code downloading, or hot swapping is
required; changing configuration and restarting a run is sufficient initially.

Each invocation needs bounded work/time and a recorded outcome. Catch a plugin's
failure at its boundary, reject malformed output, and continue with independent
capabilities. Timeouts, missing weights, external API failures, and incompatible
versions must not erase already collected evidence or block review indefinitely.
Retries, if needed, are bounded. Stronger process isolation is a later decision
if native crashes or resource contention require it; exception handling alone
cannot contain every process failure.

## Missing evidence is not normal evidence

**Missing evidence != normal evidence.** Availability and risk are separate.
A disabled plugin, timeout, stale frame, absent gauge reading, or missing model
cannot produce a zero-change measurement or a vote for `NORMAL`.

```text
Pixel change + quality + optional context
                 -> fuse usable evidence -> risk result -> human review

Segmentation unavailable; pixel change still available
                 -> report missing capability + assess remaining evidence
                 -> qualified result or UNKNOWN_DEGRADED -> human review

No usable observation plugins / no usable camera evidence
                 -> record insufficiency -> UNKNOWN_DEGRADED -> human review
```

Every completed window includes what ran, what was excluded and why, what is
missing, and whether remaining evidence meets the configured policy. An optional
plugin's absence does not necessarily invalidate sufficient remaining evidence,
but it must remain visible. Never lower risk automatically because an alarming
source stopped reporting. If current evidence is insufficient, show
`UNKNOWN_DEGRADED` and retain the previous assessment as explicitly historical,
not as a fresh measurement or an implicit return to normal.

Zero plugins is a supported completion path, not a useful river assessment: the
core still produces a reviewable insufficiency/health result. Even `NORMAL`
requires adequate, fresh, usable evidence under the versioned risk policy and
must not be read as a guarantee of safety.

## Evidence fusion and deterministic risk

Fusion aligns records to the site, camera, reference, and time window; validates
units and freshness; applies quality exclusions; and prepares temporal summaries
with source links. Preserve conflicting evidence and shared provenance. Two
outputs derived from the same image or model are not two independent confirmations.
Do not average incompatible confidence scores or invent physical water depth
from an uncalibrated pixel-change score.

Fusion feeds the existing `risk_engine_input` boundary. The deterministic risk
engine remains the single owner of sufficiency rules, risk states, persistence,
hysteresis, transitions, and reasons. Fusion must not become a second risk engine.
The same evidence, prior state, and policy/configuration version should reproduce
the same decision. Plugin-specific inference stays outside that decision logic.

The review result links component evidence, exclusions, capability status,
configuration, versions, uncertainty, and the decision rationale. A reviewer can
inspect a strong observation alongside a failed quality check rather than seeing
only an unexplained combined score.

## Camera-first and offline operation

Local video/images, local configuration, available local adapters, evidence
storage, risk evaluation, and human review must work without cloud services or a
live gauge API. Internet loss marks remote context unavailable; cached context
retains its original observation time and expires under the configured policy.
It must never appear fresh merely because it was read from cache.

Offline operation still requires accessible camera/input files, power, adequate
storage, and valid configuration. A network-only camera or image source cannot
supply new frames during its own outage. Record missing input honestly and keep
local review of existing evidence available. Buffer records locally for later
synchronization where supported; pending upload or delivery is not success.

## Human-review and warning-support boundary

Observation is not ground truth. Risk assessment is not an official warning.
The final stage is a saved review result or alert candidate for human assessment,
including insufficient-evidence results. No plugin, fused score, or single camera
may directly trigger sirens, evacuation instructions, or public warnings.

OpenFloodAI remains a local validation and warning-support proof of concept.
Any future public-warning integration requires separately approved governance,
independent validation, and field evidence. This decision neither authorizes
public alerting nor claims production flood-detection accuracy.

## Incremental adoption through Steps 00–05

**Do not build a large generic plugin framework yet. Introduce abstractions
incrementally as Steps 00–05 require them.** This document constrains that work;
it does not redefine the steps, add implementation tasks, or assert completion.

- Keep existing pixel-change and health behavior. Add the smallest adapter when
  a step first needs a common evidence boundary; reuse existing contracts/storage.
- Add reference and gauge envelopes when their consumers need them, preserving
  optionality and explicit missing states.
- Extract shared discovery or lifecycle code only after concrete capabilities
  demonstrate duplication. A configured list and ordinary function interfaces
  are enough initially.
- Add segmentation behind the same boundary when the ML readiness gate and
  evaluation evidence support it. Do not require it to complete the workflow.

```text
Pixel-change implementation A -- adapter --+
                                          +--> stable evidence contract
Segmentation model B ----------- adapter --+             |
                                                        v
                                    unchanged core pipeline and review flow
```

Swapping a model or implementation means updating its adapter, assets, and
versioned configuration, then verifying evidence semantics. A matching field
shape alone is insufficient: units, quality behavior, confidence meaning, and
calibration must still be compatible. New evidence semantics can require a
reviewed contract or risk-policy revision, but should not require a core rewrite.
Keep the previous implementation/configuration available for rollback.

## Consequences, risks, and validation evidence required

The benefit is independent evolution and graceful degradation. The cost is
explicit contracts, provenance, and sufficiency policy. Principal risks are
false independence, incompatible score meanings, stale context, invalid
references, and confusing pipeline completion with assessment quality.

Before future implementation is accepted, demonstrate through targeted replay
and failure checks that:

- Disabling each optional capability still reaches a saved human-review result.
- Zero plugins and unusable camera evidence yield `UNKNOWN_DEGRADED`, not `NORMAL`.
- A timeout or invalid record affects only that capability and its declared dependents.
- Network loss preserves local processing and exposes missing/stale remote context.
- Conflicting evidence and shared provenance remain inspectable.
- Replacing an adapter preserves the core flow; incompatible semantics are rejected
  or explicitly versioned and reviewed.
- Replaying fixed evidence, state, and configuration reproduces risk decisions.
- No plugin or risk output bypasses the human-review/public-warning boundary.

These are future acceptance conditions, not tests performed or passed by this
documentation change. Revisit the design if measured resource contention requires
isolation, multiple adapters demonstrate a real framework need, or validated
requirements change the risk-policy boundary. Roll back an incompatible adapter
or configuration rather than silently reinterpreting historical evidence.

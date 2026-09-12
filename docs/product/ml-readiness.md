# ML Readiness And First Model Strategy

Status: direction agreed on 2026-09-11 for
[issue #108](https://github.com/lamadipen/OpenFloodAI/issues/108).
This is a planning decision. Training readiness has not been demonstrated and no
model architecture has been selected.

## Context And Decision Drivers

OpenFloodAI is camera-first. The core workflow is local video, machine evidence,
human labels, comparison, and review. First make that workflow reliable; later
use other information to double-check risk.

We need understandable evidence, honest unclear results, privacy, and affordable
local processing. A model score alone must not become a public warning.

## Options Considered

| Direction | Decision |
| --- | --- |
| Train a flood/no-flood classifier first | Do not start here: it hides important water changes and unclear views. |
| Make riverbank segmentation the main product | Use it as optional supporting evidence and a selection aid. |
| Review water conditions and change over time | Agreed main direction, building on the current labeling and validation workflow. |

## Agreed Decision

The main goal is to review normal water, rising water, high water, falling water,
and unclear views, as described in the [labeling guide](../research/labeling-guide.md).
These are product concepts, not new saved label values introduced by this plan.

Use a visible riverbank as the first reference. A person confirms a clear view
recorded during normal conditions. Pillars, rocks, or other stable markers can
provide extra evidence. The system may suggest a bank area, with user correction
and manual selection available. Lack of a usable bank must be explained; it must
not be treated as normal water or make bank annotation mandatory for all review.

The normal baseline stays anchored to the same physical bank. Future video
overlays can show the estimated current boundary, bank coverage, observation
times, and uncertainty. Drawing these overlays needs no segmentation library;
finding reliable boundaries is a separate analysis problem. See the
[overlay design](../architecture/windowed-video-evidence.md#proposed-video-overlays).

Always show machine observations separately from human comparison. Human labels
are optional for validation, but required for comparison and supervised training
targets. When missing, say “No human label for comparison.”

### Easy Example

A strip of bank is visible in the normal reference. Later, reliable analysis
estimates that water covers more of it. Keep the reference outline fixed and
highlight the newly covered area, with the compared times. This supports the
water-condition assessment. If glare hides the bank, report “Cannot judge.”
Neither bank coverage nor rising water alone establishes flood danger.

## What Exists And What Remains

| Area | Current foundation | Work still needed |
| --- | --- | --- |
| Local review | Sites, video intake, watched regions, time-window labels, run records, reports and review images | A reviewed dataset suitable for the chosen experiment |
| Machine evidence | Sampled frame comparisons and basic quality checks | Reliable water-specific observations and temporal direction |
| Normal reference | A first usable frame within a review window | A separately confirmed normal baseline with provenance and camera alignment |
| Visual support | Watched-area selection and saved review images | Assisted bank selection, boundary estimates and synchronised video overlays |
| ML | Validation workflow and research | Readiness evidence, controlled experiments and a versioned model package |

Current pixel-change scores can respond to light, shadows, or camera movement.
They do not reliably identify water or prove rising versus falling water. A low
change score can also occur when water is already high.

## Readiness Gate Before Training

Training stays blocked until the team records evidence for all of these:

1. **Define the prediction.** Start with visible change over a reviewed time
   window: rising, falling, no clear change, or unable to judge. Preserve camera
   problems. Resolve how normal/high water relates to trend: water can be high
   and rising at the same time. Agree any future label mapping separately;
   existing schemas stay unchanged here.
2. **Review the examples.** Follow the
   [data quality checklist](data-quality-checklist.md). Keep video/site/event IDs,
   time windows, source permission, label version, reviewer notes, and visibility
   conditions. Have another reviewer check a sample and resolve disagreements.
3. **Establish useful coverage.** A first collection target is 50–100 reviewed
   windows across multiple independent videos/events. This is a planning target,
   not permission to train or proof of enough data. Count independent events and
   conditions, not just frames; collect more whenever a target condition lacks
   usable training or evaluation examples.
4. **Prevent data leakage.** Keep related video/event windows together when
   splitting training, development, and locked test data. Do not randomly split
   adjacent frames. Reserve unseen sites where available; otherwise describe the
   result as limited to the tested sites. Check duplicates and near duplicates.
5. **Measure the baseline.** Replay the existing simple method on the same
   reviewed windows. Save failures and counts by condition before choosing a
   trainable alternative.
6. **Set acceptance targets first.** Record numerical limits for missed target
   changes, false detections, detection delay, unclear results and device cost.
   The targets and target hardware remain open decisions; do not choose them
   after seeing test results.
7. **Confirm reproducibility and permission.** Freeze dataset/split versions,
   preprocessing, labels, experiment configuration and code version. Review the
   exact model code, weights, dependencies and training-data permissions.

Closing prerequisite issues does not demonstrate that this gate has passed.
Missing gate evidence means continue data preparation or baseline work.

## First Possible Experiment And Finished Model

After the gate passes, compare the classical baseline with a small pretrained
image network plus a method that considers ordered frames. The first experiment
asks whether the candidate improves visible water-change review. It does not
predict public flood warnings. Input should be short ordered sequences from
reviewed windows, with watched regions and optional confirmed reference evidence.
An isolated image cannot establish rising or falling by itself.

Reuse an established neural network if it helps; we do not need to invent a new
architecture. Train or fine-tune its weights on our permitted, reviewed examples.
The exact network, sequence length, and use of reference features remain choices
to evaluate. Segmentation is not a prerequisite for the main experiment.

Evaluate full held-out windows/events, not only individual frames. Report rising
and falling confusion, missed changes, false detections per camera-day where
continuous footage exists, detection delay, unclear/unavailable time, and errors
by visibility condition. Report sample counts and uncertainty; do not use overall
accuracy as the only measure. For later normal/high outputs, evaluate those
separately. Measure latency and memory on the intended device.

Keep the locked test set out of tuning. Inspect failures and retain the simpler
method if the new model does not improve the agreed criteria. A finished model
package includes weights, output definitions, preprocessing and sampling rules,
versions, license notices, evaluation evidence, and runtime/export checks. Training
a weights file alone does not complete the system.

## Tools And Research Boundaries

These are planning roles, not approved installations or integrations.

| Option | Useful role | Decision or limitation |
| --- | --- | --- |
| Classical CV / OpenCV | Cheap reference-region and temporal baselines; drawing overlays | Use the existing foundation and evaluate water-specific methods. Pixel change alone is not water change. |
| SAM 2 / MobileSAM | Possible assisted region selection or segmentation experiments | Optional support; compare quality and device cost. Do not assume MobileSAM provides SAM 2 video tracking. |
| OpenRiverCam / pyorc | Strong upstream inspiration for calibrated camera measurements | No initial integration. A future adapter could accept independently produced measurements with units, time, quality and calibration provenance, after license and contract review. |
| Google Flood Forecasting / OpenHydroNet research | Future basin-level forecasting ideas | Outside the immediate camera MVP. |
| FloodNet / satellite datasets | Labeling and research ideas | Do not substitute aerial or satellite examples for fixed-camera evaluation. |
| Vertex AI / AutoML / Cloud Vision | Possible later training, management or cloud experiments | Not required for local operation; first decide permission, privacy, cost and suitability for temporal review. |
| Gauges, rainfall, earthquake or forecast information | Possible later cross-checks | Relevance must be established; an external signal alone does not prove local flood danger. |

The initial shortlist excludes pyorc/ffpiv, Ultralytics YOLO segmentation,
FastSAM and OpenPIV integrations under our current licensing preference. This is
a project scope decision, not a claim that all have identical license terms or
can never be used. Revisit explicitly before adoption. SAM 2, MobileSAM and
OpenCV remain candidates subject to exact version, weights and dependency review.

Study published algorithms where useful. Develop our application logic as needed;
there is no decision to build a complete velocity or water-level library. Physical
height, speed and discharge measurements require appropriate calibration and are
outside the first experiment.

See [model options](../research/ml-model-options.md) for more background. Primary
references include [SAM 2](https://github.com/facebookresearch/sam2),
[MobileSAM](https://github.com/ChaoningZhang/MobileSAM),
[pyOpenRiverCam](https://localdevices.github.io/pyorc/), and
[Google flood-forecasting (OpenHydroNet)](https://github.com/google-research/flood-forecasting).
Related background:
[Google streamflow forecasting research](https://github.com/google-research-datasets/global_streamflow_model_paper).

## Consequences, Privacy And Risks

Keep approved source footage and evidence local for the authorised review or
experiment period, following [privacy and retention](../privacy-retention.md).
Do not retain every video indefinitely. Preserve enough permitted sequence context,
labels and version information to reproduce an experiment; record when deletion
prevents replay. Local review permission is not automatically training or upload
permission. No cloud uploads or raw media commits are authorised by this plan.

Bank visibility depends on the site and season. Camera movement needs reliable
alignment or a stopped comparison. Darkness, glare and obstruction must produce
an explicit unclear result, rather than a stale overlay or a normal-water result.
Baseline selection and field measurements can themselves be wrong and need review.

## Validation Evidence And Future Production Gate

The next milestone is reliable local review supported by held-out event evidence,
condition-specific failure analysis and independent QA.

Future public-warning use needs a separate process: independent field evidence,
a shadow pilot with no public messages, operator review, reliability and failure
testing, monitoring and rollback, and an authorised warning procedure. Completing
model training is not production approval. No alerts, deployment or accuracy
claims are authorised here.

## Revisit Trigger And Next Work

Revisit the design if bank references do not help, simpler methods work better,
camera movement cannot be handled, or quality/device requirements cannot be met.
Keep existing local review available while new components are evaluated separately.

The normal-reference record and its confirm/draft/invalidate visual selection
workflow are now defined (issue #163) — see
[Confirmed Riverbank Reference](../architecture/data-contracts.md#confirmed-riverbank-reference-issue-163).
Next implementation planning should build on that record while dataset
preparation establishes the training gate. Choose one bounded follow-up task
at a time. Exact model architecture, numerical acceptance targets, baseline
frame selection and future label contracts remain open; the camera-first
product direction is settled.

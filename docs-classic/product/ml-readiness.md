# ML Readiness And First Model Strategy

Status: direction agreed on 2026-09-11 for
[issue #108](https://github.com/lamadipen/OpenFloodAI/issues/108); refreshed on
2026-10-08 for the system we have now (images as well as videos, gauge evidence,
curation and release tools). This is a planning decision. **It is not yet time to
train a model.** Training readiness has not been demonstrated and no model
architecture has been selected. This plan trains nothing, claims no accuracy, sends
no alerts and does not replace human review.

## Context And Decision Drivers

OpenFloodAI is camera-first. The core workflow is local video, machine evidence,
human labels, comparison, and review. First make that workflow reliable; later
use other information to double-check risk.

We need understandable evidence, honest unclear results, privacy, and affordable
local processing. A model score alone must not become a public warning.

### Nepal Bhote Koshi 2026 Lesson

The Government of Nepal's
[Rasuwa-Bhote Koshi Flood Event assessment report](https://hydrology.gov.np/cm/files/Assessment%20Report%20II_Bhotekoshi%20Flood_2026_1789276630363.pdf)
supports this camera-first direction. The report says the 26 August 2026 event
was not a normal rainfall flood. It was assessed as a rapid outburst linked to
an ice-rock avalanche or landslide-dam process, with very short warning time,
damaged monitoring stations, and a new CCTV monitoring installation at Timure
after the event.

Simple meaning: rainfall, gauges, seismic signals, satellite data, and field
reports are useful cross-checks, but they may not be enough by themselves for a
sudden Himalayan flood. Direct visual evidence from a camera can help confirm
what the river is actually doing, especially when a gauge fails or the event is
not caused by local rain.

For OpenFloodAI, this does not approve automatic public warnings. It does
confirm that our dataset and validation work should preserve visual evidence of
sudden water rise, debris, blockage, muddy surge, damaged or missing gauges, and
short-warning events. Those examples can later help evaluate whether camera
observations agree with human review and supporting external signals.

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
They describe the review product. The first ML pilot targets gauge height from a single
image instead; trend (rising and falling) is a separate, future experiment. See
[Choose One First Prediction Task](#choose-one-first-prediction-task).

Use a visible riverbank as the first reference. A person draws the **Normal
Waterline Guide** by hand: a polyline on the normal water edge with a water-side
point, confirmed by a reviewer ([issue #174](https://github.com/lamadipen/OpenFloodAI/issues/174);
see "Normal Waterline Guide" in the full documentation's data contracts).
The system does not suggest or auto-draw the baseline line, and a new drawing tool
is not a prerequisite. Pillars, rocks, or other stable markers can provide extra
evidence. Lack of a usable bank must be explained; it must not be treated as normal
water or make a guide mandatory for all review. Keep the human guide separate from
machine observations.

The normal baseline stays anchored to the same physical bank. The Review page
already overlays the watched area and the confirmed guides on the baseline and a
chosen image. Overlays that show a machine-estimated current boundary, bank
coverage and uncertainty are still future work. Drawing overlays needs no
segmentation library; finding reliable boundaries is a separate analysis problem. See the
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
| Local review | Sites, video and timestamped-image intake, watched areas, human labels with revisions, event reviews, run records, reports and review images in the Review Workspace | A reviewed dataset large and varied enough for the chosen experiment |
| Image supply | Water-level sampling picks low, middle and high water images from a linked gauge, and can append to a sequence ([guide](../learning/water-level-sampling.md)) | Coverage across independent cameras and conditions |
| Gauge evidence | Each image's own matched USGS reading, with units, time gap and quality, frozen with the run | Treating readings as instrument-derived supervision, never as observed truth |
| Machine evidence | Sampled frame comparison, a pixel-change adapter, and an optional riverbank-crossing adapter that is off by default and reports that camera alignment is unavailable | Reliable water-specific observations, camera alignment and temporal direction |
| Normal reference | A manually drawn Normal Waterline Guide with draft, confirmed and invalid states ([#174](https://github.com/lamadipen/OpenFloodAI/issues/174)) and per-sample quality checks | Confirmed guides on more sites, with provenance |
| Assisted labelling | Optional, off-by-default hosted SAM 3.1 outlines for water or riverbank; a person accepts, rejects or asks for correction (see the full documentation's hosted SAM guide) | Evidence that it saves review effort; it is never a label by itself |
| Dataset building | Curated, versioned local datasets from reviewed observations across runs, with site/camera-isolated splits, locked-validation protection, duplicate checks and frozen, checksummed versions ([guide](../learning/dataset-curation.md)) | Enough independent cameras and events to fill train, validation and test |
| Sharing | A verified, versioned release with a licensing and privacy gate, a dataset card and a private-first upload path ([guide](../learning/dataset-release.md)) | Recorded approvals; no release is published by default |
| ML | A validation scorecard, label comparison and a riverbank pilot evaluation | Readiness evidence, an agreed baseline run, acceptance targets, controlled experiments and a versioned model package |

Current pixel-change scores can respond to light, shadows, or camera movement.
They do not reliably identify water or prove rising versus falling water. A low
change score can also occur when water is already high.

## Readiness Gate Before Training

Training stays blocked until the team records evidence for all of these:

1. **Define the prediction.** Use the chosen task. The recommended first pilot is
   **gauge-height estimation from a single image at one site** (see
   [Choose One First Prediction Task](#choose-one-first-prediction-task)). Name the
   target, the intended site and the input available at deployment, and state whether
   the experiment is site-specific or meant to transfer to new cameras. Rising/falling
   change over a reviewed window is a separate, future change-detection experiment.
   Its labels (rising, falling, no clear change, unable to judge) and how normal or
   high water relates to trend (water can be high and rising at once) are agreed only
   if that task is chosen. Preserve camera problems. Existing schemas stay unchanged
   here.
2. **Review the examples.** Follow the
   [data quality checklist](data-quality-checklist.md). Keep video/site/event IDs,
   time windows, source permission, label version, reviewer notes, and visibility
   conditions. Have another reviewer check a sample and resolve disagreements.
3. **Establish useful coverage.** There is no automatic readiness threshold at
   50, 100 or 500 images. Audit a small representative pilot using the existing
   curation tools: count independent sites, events and conditions, not just
   images or frames; record reviewer disagreements and missing evidence; collect
   more whenever a target condition lacks usable training or evaluation examples.
4. **Prevent data leakage.** Keep related events, windows and near-duplicate images together when
   splitting training, development, and locked test data. Do not randomly split
   adjacent frames. For an unseen-site claim, hold out whole sites and their
   cameras. A one-site chronological pilot is allowed as a limited, site-specific
   experiment and proves nothing about other cameras. Check duplicates and near
   duplicates.
5. **Measure the baseline.** Measure a simple task-matched baseline on the same
   held-out examples before choosing a trainable alternative. For gauge-height
   estimation that means height error (mean absolute error) and bias in the gauge's
   stated unit, for example against predicting the training median. Save failures and
   counts by condition and by gauge range. Only a future change-detection experiment
   replays the existing simple method over reviewed windows.
6. **Set acceptance targets first.** Record numerical limits in the chosen task's own
   measures before the experiment runs. For gauge-height estimation these are height
   error and bias in stated units, the share of unclear or unavailable cases, and
   device cost. Missed changes, false detections and detection delay apply only to a
   future change-detection experiment. The targets and target hardware remain open
   decisions; do not choose them after seeing test results.
7. **Confirm reproducibility and permission.** Freeze dataset/split versions,
   preprocessing, labels, experiment configuration and code version. Review the
   exact model code, weights, dependencies and training-data permissions.

Closing prerequisite issues does not demonstrate that this gate has passed.
Missing gate evidence means continue data preparation or baseline work.

## Is It Time To Start ML? Status Against The Gate

**No.** The tools to build a trustworthy dataset now exist, but the evidence the gate
asks for has not been recorded. The next work is collecting and reviewing data, and
measuring the simple baseline, not training.

| Gate item | What exists now | What is still missing |
| --- | --- | --- |
| 1. Define the prediction | The recommended pilot is single-image gauge-height estimation at one site. Curated datasets support four tasks: segmentation, gauge height, low/middle/high categories (from approved site definitions) and rising/falling pairs | Naming the pilot site, and stating site-specific or transfer. Label mapping for trend is agreed only if a change task is chosen; any new label mapping stays a separate decision |
| 2. Review the examples | Human labels with revisions, quality answers, event reviews, accepted masks, the [data quality checklist](data-quality-checklist.md) | A second reviewer checking a sample and resolving disagreements. No tool for this exists yet |
| 3. Establish useful coverage | Curated datasets show how many examples, sites, cameras and categories they hold | A pilot audit counting independent sites, events and conditions, with reviewer disagreements and missing evidence, has not been recorded. [#158](https://github.com/lamadipen/OpenFloodAI/issues/158) owns the readiness report |
| 4. Prevent data leakage | Splits are by camera (and site) and never random, locked-validation data is test-only, pairs stay together, identical images cannot cross splits | A frozen split before tuning. A one-site chronological pilot is allowed with limited, site-specific claims; an unseen-site claim needs held-out sites and cameras. Three independent camera splits are a rule for a public release, not for every local pilot |
| 5. Measure the baseline | Validation scorecard, human-versus-machine comparison and a riverbank pilot evaluation. They were built for change review and do not measure height error | A recorded task-matched baseline on the same held-out examples. For gauge height: error and bias in stated units, with counts by condition and gauge range |
| 6. Set acceptance targets first | Nothing yet | Numerical limits on height error and bias in stated units, the share of unclear cases and device cost, plus the target hardware. Limits for missed changes, false detections and delay apply only to a future change-detection experiment. Set these before any result is seen |
| 7. Reproducibility and permission | Frozen, checksummed dataset versions, recorded source and license approvals, and a privacy review gate for sharing | Permission to train on each source, and a review of any model's code, weights, dependencies and licenses |

This table is a snapshot. Re-check it, and update it, whenever a gate item changes. Closing
an issue does not pass the gate.

## Choose One First Prediction Task

Dataset curation supports four tasks. We recommend one for a first pilot, not all four,
and no existing label schema changes. Training eligibility is task-specific and stricter
than merely being able to run validation.

| Task | Supervision | Effort to obtain it | What it does not prove | Task-specific metrics |
| --- | --- | --- | --- | --- |
| Water segmentation | A mask for the exact image that a person accepted, with the model and provenance kept | Highest: every mask needs review, and the hosted tool is a paid optional call | Flood danger or physical height | Overlap (IoU or Dice) and boundary error in pixels, by condition |
| Gauge-height estimation | An image and its own matched gauge value, units, station and quality | Low: water-level sampling already saves each image's matched evidence | Camera-local depth, or transfer to another site without evaluation | Mean absolute error and bias in the gauge's stated unit, by gauge range and condition |
| Low/middle/high classification | A reviewed image, matched gauge evidence and approved, versioned site bands | Medium: a person must approve the bands and review each image | Universal flood thresholds. Collection groups are not training labels | Per-class precision and recall, a confusion matrix, and errors between neighbouring classes |
| Rising/falling change | Ordered same-view image pairs or windows with matched evidence for both times | Medium to high: explicit pairs and time context | Direction from one isolated image | Rising/falling confusion, missed changes, false detections and detection delay |

### Recommended first pilot: gauge-height estimation at one site

Predict the gauge height from a single image of one stable camera view, and measure the
error in the gauge's own unit.

Why this one:

- Its supervision comes from tools that already exist. Water-level sampling picks images
  across the gauge range and freezes each image's own matched reading with units, station,
  time gap and quality.
- It needs the least extra human labelling, so a pilot can start from reviewed, diverse
  examples rather than waiting for masks, approved bands or explicit pairs.
- Its error is measured in stated units against a simple baseline, which is a clear
  success or failure test.
- It avoids thresholds nobody has approved (classification), paid and reviewed masks
  (segmentation) and ordered pairs (change). A mask may still help a reviewer, but it is
  not required for this task.

Limits of the recommendation: it depends on the pilot audit showing enough independent
events and a wide enough range of gauge values at the chosen site. If the audit finds the
range narrow, the matches sparse or the camera view unstable, revisit the choice. The
nearby gauge does not give the physical water level at the camera, so a good result means
"predicts what the gauge reports" and nothing more.

### Do not feed the answer to the model

When gauge height is the target, **the target gauge reading must never be a model input.**
That includes the reading matched to the image, readings of the same station at nearby
times, and anything derived from them: the low/middle/high sampling group, a category from
an approved band, or a feature built from any of these. Giving the model those and calling
the result image-based prediction is invalid. Timestamps and season can stand in for the
water level, so state them explicitly as inputs or hold them out.

### Pilot protocol (site-specific)

- Freeze a chronological split before any tuning: earlier period for training, a later
  period for development, the latest as a locked test. Leave a gap between periods and keep
  related events and near-duplicates together.
- Measure a simple task-matched baseline on the same held-out examples first, for example
  predicting the training median and a simple classical image-feature baseline.
- Report sample counts, unclear cases and errors by condition (glare, darkness, frozen
  water, moved camera) and by gauge range. Do not rely on one overall number.
- Keep unclear, frozen-water, glare, darkness and moved-camera examples identifiable. They
  must not silently become valid water-level examples.
- A one-site chronological pilot supports a limited, site-specific claim only. An
  unseen-site claim needs held-out sites and their cameras. Publishing a dataset is optional
  and is not a prerequisite for a local experiment.

The detailed specification (candidate model, protocol, numerical success criteria and
compute limits) belongs to [#160](https://github.com/lamadipen/OpenFloodAI/issues/160).
Numerical limits are agreed before the experiment runs and are never chosen after seeing
test results. Reuse an established pretrained network or library if one helps; we do not
need to invent an architecture. Segmentation is not a prerequisite for this pilot.

### The Finished Model Package

Keep the locked test set out of tuning. Inspect failures and retain the simpler method if
the new model does not improve the agreed criteria. A finished model package includes
weights, output definitions, preprocessing and sampling rules, versions, license notices,
evaluation evidence, and runtime/export checks. Training a weights file alone does not
complete the system. Accepting or correcting a mask does not retrain the hosted provider's
model.

## Tools And Research Boundaries

These are planning roles, not approved installations or integrations.

| Option | Useful role | Decision or limitation |
| --- | --- | --- |
| Classical CV / OpenCV | Cheap reference-region and temporal baselines; drawing overlays | Use the existing foundation and evaluate water-specific methods. Pixel change alone is not water change. |
| SAM 2 / MobileSAM / hosted SAM | Assisted region selection and segmentation experiments. An optional hosted SAM 3.1 service is already wired in, off by default, sending only the chosen crop after confirmation | Assisted labelling only. An accepted mask is a reviewed machine output, not a hand-drawn label and not a flood decision. Compare quality, cost and device suitability. Do not assume MobileSAM provides SAM 2 video tracking. |
| OpenRiverCam / pyorc | Strong upstream inspiration for calibrated camera measurements | No initial integration. A future adapter could accept independently produced measurements with units, time, quality and calibration provenance, after license and contract review. |
| Google Flood Forecasting / OpenHydroNet research | Future basin-level forecasting ideas | Outside the immediate camera MVP. |
| FloodNet / satellite datasets | Labeling and research ideas | Do not substitute aerial or satellite examples for fixed-camera evaluation. |
| Hugging Face / Kaggle | Sharing a reviewed dataset with other researchers, privately first | Only after the release gate (source and license approvals, privacy review) and a human decision to publish. Not a training platform here. |
| Vertex AI / AutoML / Cloud Vision | Possible later training, management or cloud experiments | Not required for local operation; first decide permission, privacy, cost and suitability for temporal review. |
| Gauges, rainfall, earthquake or forecast information | Gauge readings are already matched to images as supporting evidence. Rainfall, earthquake and forecast data are possible later cross-checks | Relevance must be established; an external signal alone does not prove local flood danger. |

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

## Training-Readiness Checklist

Record a clear **ready** or **not ready** decision with the remaining gaps. Passing this
list is the evidence for a separately approved experiment. It is not the experiment.

| Check | Evidence to record | Owner |
| --- | --- | --- |
| Target, sites and deployment input named; site-specific or unseen-site stated | One written statement for the chosen task | [#160](https://github.com/lamadipen/OpenFloodAI/issues/160) |
| Pilot audited | Counts of independent sites, events and conditions; reviewer disagreements; missing evidence | [#158](https://github.com/lamadipen/OpenFloodAI/issues/158) |
| Provenance preserved | Original image identity, review revisions, mask origin, label-definition version, gauge evidence, with machine suggestions, human decisions, collection groups, quality flags and instrument-derived targets kept separate | Existing curation ([guide](../learning/dataset-curation.md)) |
| Splits frozen before tuning | Chronological or site/camera split recorded; near-duplicates and related events kept together | [#157](https://github.com/lamadipen/OpenFloodAI/issues/157) |
| Task-matched baseline measured | Baseline results on the same held-out examples, using development data only for tuning | [#159](https://github.com/lamadipen/OpenFloodAI/issues/159) |
| Success and failure criteria agreed | Numerical limits and compute or cost limits, recorded before the run | [#160](https://github.com/lamadipen/OpenFloodAI/issues/160) |
| Dataset frozen and permissions recorded | Dataset version, code and configuration, source and license permissions, known limitations | Existing curation and [release](../learning/dataset-release.md) |
| Candidate code and weights checked | Exact licenses and dependencies reviewed before adoption | [#160](https://github.com/lamadipen/OpenFloodAI/issues/160) |

## Open Decisions

These need a named person to decide. They are not chosen here, and they must be settled
before results are seen:

- which site the first pilot uses, and whether it is site-specific or intended to transfer;
- numerical success and failure criteria and the target hardware;
- how a second reviewer samples and resolves disagreements;
- which network, input size and baseline to compare;
- any future label mapping between trend and normal or high water;
- permission to train on each source, and the license review of any model.

## Who Owns The Next Steps

| Step | Owner |
| --- | --- |
| Collect and review representative samples, and rehearse the workflow | [#152](https://github.com/lamadipen/OpenFloodAI/issues/152), [#153](https://github.com/lamadipen/OpenFloodAI/issues/153) |
| Failure tracking, reviewer evidence and progress visibility (check what current code already covers first) | [#154](https://github.com/lamadipen/OpenFloodAI/issues/154), [#155](https://github.com/lamadipen/OpenFloodAI/issues/155), [#156](https://github.com/lamadipen/OpenFloodAI/issues/156) |
| Locked evaluation rules, reconciled with current curation and release checks | [#157](https://github.com/lamadipen/OpenFloodAI/issues/157) |
| Evidence-backed model-readiness report | [#158](https://github.com/lamadipen/OpenFloodAI/issues/158) |
| Baseline evaluation and tuning, on development data only | [#159](https://github.com/lamadipen/OpenFloodAI/issues/159) |
| Detailed first-experiment specification: candidate model, protocol, success criteria (reconcile older example label names with current schemas) | [#160](https://github.com/lamadipen/OpenFloodAI/issues/160) |
| Optional CVAT-assisted annotation round trip, not mandatory when accepted masks suffice | [#216](https://github.com/lamadipen/OpenFloodAI/issues/216) |
| Dataset curation and release, already delivered. Reuse rather than rebuild | [#219](https://github.com/lamadipen/OpenFloodAI/pull/219), [#220](https://github.com/lamadipen/OpenFloodAI/pull/220) |

## Not Authorized Here

This plan does not authorize training or fine-tuning a model, publishing or uploading a
dataset, sending alerts, replacing human review, or any production-accuracy claim. A
real hosted upload has not been validated, and having the tools does not show that any
dataset is ready. Pretrained segmentation may keep helping reviewers now; it does not
wait for training readiness.

## Revisit Trigger And Next Work

Revisit the design if bank references do not help, simpler methods work better,
camera movement cannot be handled, or quality/device requirements cannot be met.
Keep existing local review available while new components are evaluated separately.

The manual Normal Waterline Guide and its confirm/draft/invalidate workflow are defined
(issue #174, which replaced the earlier baseline rectangle and suggestion contract) — see
"Normal Waterline Guide" in the full documentation's data contracts.
Per-sample riverbank/reference quality checks that separate baseline-ready
evidence from practice-only footage are defined too (issue #164) — see
"Riverbank/Reference Quality Checks" in the full documentation's data contracts.

Next steps are owned by the issues in the table above, one bounded task at a time.

Exact model architecture, numerical acceptance targets, baseline frame selection and
future label contracts remain open; the camera-first product direction is settled.

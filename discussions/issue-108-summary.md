# Issue #108 — ML readiness discussion memory

Last updated: 2026-09-10
Status: DISCUSSION ONLY — main goal reaffirmed; implementation/model choices open

Current agreed direction (supersedes the narrower proposals in rounds 2–10):
water-state review remains the main goal, following the existing labeling guide.
Segmentation and riverbank selection support visual baseline selection and stronger
evidence; they are not the main prediction goal or a mandatory training prerequisite.
No main model architecture has been selected.
Branch: `feature/OF_054_ML-readiness-discussion`
Starting commit: `79194df` on local `main` (remote freshness not checked)

## Purpose and working agreement

The user asked to explore issue #108 together, using their research notes as a
baseline. Keep this file as our running memory. Update or create formal project
documentation only after the discussion reaches an agreed conclusion.

The supplied document's recommendations and checklists are research input, not
authorization to implement, install dependencies, train, upload data, or publish.
No project behavior changes are part of this discussion. Tests and formatting
checks remain deferred until the user asks to commit. The existing `.gitignore`
edit is unrelated and must be preserved.

## Sources and current context

- [Issue #108: ML readiness and first model strategy](https://github.com/lamadipen/OpenFloodAI/issues/108)
- [MVP reference discussion](https://github.com/lamadipen/OpenFloodAI/issues/108#issuecomment-5572498383)
- User baseline: `openfloodai-research-notes.md`, supplied from Downloads. Reviewed
  all eight sections; retained as a separate original, not edited or copied wholesale.
- Existing project notes: `docs/research/ml-model-options.md`.
- Dependencies #104, #81, #106, and #111 are closed as checked on 2026-09-10.
  Closure is not evidence that the actual dataset meets ML readiness requirements.
- Local project metadata declares MIT in `pyproject.toml`; no license-named file
  was found within the first two directory levels. Confirm licensing before adoption.
- The baseline's September 6/7 project inventory is historical. Current main also
  includes desktop packaging; `platformdirs` is now a runtime dependency.

## What the research proposes

Keep camera evidence and human review central. Improve classical vision before
training a flood classifier. Study OpenRiverCam/pyorc/ffpiv for camera geometry,
water-level and velocity measurement. Consider a custom water-level scorer,
segmentation-assisted labeling, and later temporal and external cross-checks.
Avoid choosing dependencies without considering licenses and deployment costs.

Other candidates mentioned: OpenCV, scikit-image, ruptures, river, SAM2,
MobileSAM, YOLO-seg, FastSAM, torchvision, CVAT, Label Studio, FiftyOne, ONNX
Runtime, gauges/markers, optional sensors, and low-light/rain preprocessing.
These are candidates to evaluate, not an approved dependency list.

## Initial assistant assessment — proposals, not decisions

The strongest part is breaking the problem into measurable camera evidence instead
of treating a model's flood/no-flood answer as trustworthy. The main adjustment is
to choose the first measurement before choosing a library or building algorithms.

| Question | What would support an answer? | Initial priority proposal |
| --- | --- | --- |
| Did the image change? | Stable camera and usable image comparisons | Existing baseline to improve |
| Did the waterline move up or down? | A visible, stable reference and reviewed time windows | Candidate next target |
| How high is the water in metres? | Known geometry or a calibrated visible gauge, with a defined datum | Optional calibrated route |
| How fast is the surface moving? | Trackable texture, reliable timing, geometry for physical units | Separate later question |
| What is the discharge? | Velocity plus cross-section and additional assumptions/validation | Later hydrometric work |
| Is there danger downstream? | Local context and independent evidence/authority decisions | Outside this camera MVP |

Example: leaves can move quickly downstream while the waterline stays at the same
mark on a pillar. That is surface motion, not proof of rising water. If the water
covers progressively higher known marks, there is more direct evidence of a rise.
If the image becomes unreadable, preserve an unclear state rather than force a result.

Candidate next experiment to discuss: use approved fixed-camera clips with a visible
reference, ask people to mark rising/falling/stable/unclear windows, and compare a
simple reference-line method against the current baseline. Only after identifying
its failures decide whether segmentation or another model addresses them.

## Corrections and claims needing verification

1. **PIV effort:** a short correlation demo is not a validated hydrometric system.
   Do not accept the “few hundred lines” effort estimate for a reliable replacement.
   Camera geometry, quality rejection, uncertainty, difficult scenes, and field
   evaluation can dominate the work. This is an engineering assessment, not a benchmark.
2. **OpenCV before extra dependencies:** OpenCV already documents dense optical flow.
   Adding scikit-image needs a measured reason, not just its presence on a tool list.
   [OpenCV tracking API](https://docs.opencv.org/4.x/dc/d6b/group__video__track.html)
3. **OpenRiverCam:** its documentation supports reprojection, velocity estimation,
   and discharge over a provided cross-section. That makes it a useful reference;
   it does not establish suitability or production accuracy at our sites. Exact
   water-level APIs, survey needs, versions, and field performance still need a focused review.
   [pyorc documentation](https://localdevices.github.io/pyorc/)
4. **Licensing language is too absolute:** pyorc's AGPL text includes source-sharing
   conditions and Section 13 addresses modified versions used remotely. The baseline's
   statement that any import automatically puts the entire codebase under AGPL is
   not a legal conclusion established here. The actual combined work and deployment
   require assessment; process separation is not automatic clearance either.
   Do not label permissive tools “no risk” or original reimplementation “no license risk.”
   [pyorc license, including Section 13](https://github.com/localdevices/pyorc/blob/main/LICENSE)
   GNU's own page timed out; the license copy in the upstream repository was read instead.
5. **MobileSAM:** upstream describes a lighter SAM image encoder; do not assume
   SAM2-style temporal tracking or target-device performance from that alone.
   [MobileSAM upstream README](https://github.com/ChaoningZhang/MobileSAM)
6. **Markers and measurements:** a visible marker may help registration or scale
   under suitable geometry. Do not assume one marker establishes the river's changing
   surface plane, a height datum, or channel cross-section. Site requirements remain open.
7. **Dataset size:** the issue comment's 50–100 examples is a discussion starting
   point, not proof of readiness. Many neighboring frames from one event are not many
   independent examples. Diversity, label review, leakage-free splits, and failure
   coverage matter. Set a gate for a specific experiment, not a magic total.
8. **Human labels:** a rising/falling window label is not a water mask or measured
   level label. Additional annotations may be needed for the chosen experiment.
   Model-suggested labels need human checking to avoid evaluating a model against itself.
9. **Enhancement and sensors:** better-looking images do not automatically contain
   reliable new evidence. Cheap sensor component prices do not establish installed
   outdoor system cost. Neither claim has been validated for this project.

Other tool licenses, model weights, version-specific APIs, dataset terms, cost,
and the claimed absence of permissive water-level alternatives remain unverified
in this discussion. Do not carry the baseline's “confirmed” labels into a final plan
without checking the relevant artifacts.

## Open decisions, in discussion order

1. Reference choice answered: visible riverbank first; existing pillars or markers
   are optional supporting references. No installed marker is required for the first approach.
2. How should a person choose and confirm the normal-condition bank baseline, and
   when should it be replaced? Relative visual change is the first direction;
   physical height, speed, and volume are not initial requirements.
3. What fixed-camera videos, independent events, difficult conditions, and reviewed
   labels do we actually have permission to use?
4. What is the acceptable installation and maintenance effort at a site?
5. What observation error, false-change rate, unclear rate, and time-to-detect would
   count as useful improvement? For height estimates, define error against an
   independent reference. For segmentation, mask overlap alone is insufficient.
6. Which baseline failure would justify the smallest ML experiment? Could assisted
   labeling be useful before training anything? Avoid bundling training and label assistance.
7. Is preserving a permissive project license a firm requirement? Compare compliant
   reuse, independent upstream evidence, and original development before choosing.
8. What retention, privacy, and edge resource constraints apply? Keep forecasting,
   cloud platforms, and external signals optional future topics.

## Decisions made so far

The discussion workflow is agreed: branch created, this memory file started,
research treated as a baseline, and formal documentation deferred.

User direction recorded on 2026-09-10:

- Use a visible riverbank as the primary reference.
- Establish how that bank looks during normal conditions, then observe whether
  water covers previously visible bank areas.
- Use pillars or other visible markers as additional references when available.
- Follow an understandable visual-review approach: people can notice concerning
  changes without measuring water speed or volume. Those measurements are not
  prerequisites for the first approach.

This establishes a product direction, not a validated detection method. No library,
model, numerical threshold, automatic danger rule, or integration has been selected.

## Riverbank baseline — discussion round 2

Assistant interpretation and proposed workflow (not yet agreed in detail):

1. A person selects a clear view showing the bank under conditions they consider
   normal and confirms the bank area to watch.
2. Compare later views of that same bank against the saved baseline and recent
   frames. Describe which previously visible areas appear covered by water.
3. Require enough evidence to distinguish water coverage from mere disappearance.
   Fog, shadows, vegetation, obstruction, and camera movement must be considered;
   disappearance alone is not sufficient evidence of water coverage.
4. Show the observation and supporting images, for example: “Water appears to
   cover part of the bank that was visible in the baseline.” If the cause cannot
   be established, say “The bank is not clearly visible; cannot judge.”
5. Treat sustained expansion as a candidate for human review, not proof of a flood
   or an automatic public warning. Local danger thresholds still need a separate
   discussion and independent evidence.

Illustrative example, not a numerical rule: a bank has three recognizable rock
patches above water in the baseline. Later, the lowest patch appears submerged;
then the next patch does too. That supplies a sequence to review. If all patches
vanish into fog instead, report loss of visibility rather than a rising-water result.

Baseline questions still open:

- Should the first version use one human-confirmed baseline image, a short clip,
  or several examples of normal conditions?
- How will reviewers define “normal” for a site? It must not automatically mean safe.
- Which bank features stay visible and useful across lighting and seasonal changes?
- How should a moved camera or changed bank invalidate the old reference?
- Which persistence and coverage evidence would justify a review candidate?
- Could automatic baseline updates hide a slow rise? The proposed safeguard is to
  keep the normal reference fixed until a person approves a replacement and also
  retain recent comparison views. Exact replacement rules still need discussion.

## Riverbank baseline — discussion round 3

The user replied “Yes we can do that” to the proposed baseline approach.
Record agreement with using a human-confirmed normal riverbank baseline and later
comparison views. The reply did not select between a single reference frame and
multiple frames from a normal-condition video; that choice remains open.

Assistant proposal for the smallest initial workflow, not a finalized requirement:
let a person select one clear frame from a normal-condition video and mark the
bank area. Retain its source video/time and compare later images against it. Add
multiple baseline frames only if lighting or other observed failures justify them.

Next discussion: what should a person mark in that image? Prefer exploring a bank
area with recognizable features rather than assuming a percentage of covered pixels
can directly represent water height or flood danger. No UI or algorithm work is
being authorized by this discussion agreement.

## Handoff / next turn

Continue with how the normal riverbank reference should be selected and maintained.
Do not reopen the primary reference choice without a new reason: riverbank first,
optional markers second. Record user decisions separately from assistant proposals.
Keep uncertainty and rejected ideas visible with a short reason. Once the user is
satisfied, map the agreed conclusions to issue #108's required comparison table and
readiness plan, and choose existing docs to update instead of duplicating them.


## Riverbank baseline — discussion round 4

User proposal: let the system suggest possible riverbanks first, then let the user
correct them. This is a candidate workflow, not a selected model or implementation.
It revises the earlier assistant proposal that marking must begin manually.

Proposed interaction:

1. User supplies a suitable normal-condition frame or video (format still open).
2. System highlights candidate visible bank areas as suggestions, not confirmed banks.
3. User adjusts, removes, or adds areas and explicitly confirms the reference.
4. Save the confirmed bank regions with the baseline image and its source/time.
5. Compare later views against those confirmed regions; do not silently replace them
   with new machine suggestions.

The annotation target needs care: a visible bank region is land next to the water,
not just the water mask or the edge of the entire image. We still need to decide
whether to keep a bank-area polygon, a waterline, or both. No such schema change is
agreed yet.

Keep a manual marking path if no useful suggestion is available. Do not require
accepting a suggestion. A suggested bank also does not prove the image shows normal
or safe conditions; baseline suitability needs human confirmation.

This gives issue #108 a concrete candidate for first model-assisted functionality:
help choose reference regions during setup. It does not by itself justify training
or selecting a model, nor claim reliable bank detection. Compare candidate methods
later using human correction effort and missed/incorrect regions across difficult
scenes. Preserve the distinction between machine drafts and human-confirmed labels.

Next discussion: confirm this interaction, then decide what the user should correct
(bank area, waterline, or both) before evaluating tools or changing formal docs.

## Riverbank suggestions — discussion round 5: useful libraries

User asks whether the previously researched libraries can help. Answer: yes.
The earlier caution was about unverified riverbank accuracy, not a rejection of reuse.

| Candidate | Possible role in our proposed workflow | Important limit / next evidence |
| --- | --- | --- |
| SAM 2 | Candidate region masks, click/box-assisted corrections, and video mask propagation | A mask is not automatically identified as a riverbank. Need a method or human input to choose the correct regions; assess local compute cost. |
| MobileSAM | Lighter candidate for selecting/correcting masks on a baseline image | Do not assume SAM2-style video propagation or acceptable latency on our hardware. |
| OpenCV | Classical region proposals, boundary refinement, alignment, overlays, later image comparisons | Region boundaries are not semantic bank recognition; measure sensitivity to lighting and vegetation. |
| YOLO segmentation | Technical capability reference only; excluded from the current adoption shortlist under the user's licensing constraint | Reconsider only after an explicit licensing decision; do not assume generic weights know riverbanks. |
| pyorc / OpenRiverCam | Geometry, stabilization and later calibrated river measurement reference | Not the first candidate for automatic bank suggestion in an uncalibrated image. |
| CVAT / Label Studio | Possible offline annotation workflow if mask-label collection grows | They do not automatically solve bank detection; avoid replacing the Home UI without a clear need. |

Source checks for this round (2026-09-10):
- [SAM 2 upstream](https://github.com/facebookresearch/sam2): promptable image/video
  segmentation, pretrained checkpoints, automatic image mask generation, and
  PyTorch dependencies. Proposed bank use is our inference, not an upstream accuracy claim.
- [MobileSAM upstream](https://github.com/ChaoningZhang/MobileSAM): lighter SAM image
  encoder. Proposed baseline-image use needs an actual comparison.
- [Ultralytics segmentation docs](https://docs.ultralytics.com/tasks/segment/):
  pretrained segmentation and custom training; no riverbank performance established.
- [OpenCV watershed tutorial](https://docs.opencv.org/4.x/d3/db4/tutorial_py_watershed.html):
  marker-guided region segmentation, not automatic semantic recognition of riverbanks.

Assistant shortlist proposal: compare OpenCV-assisted marking, MobileSAM and SAM 2
on the same approved baseline images. Measure correction time, wrong/missed bank
areas, memory and latency. Start by evaluating pretrained inference, not training a
new model. This is a proposed future evaluation only; nothing has been installed,
run, or selected. The training gate remains separate from evaluating a pretrained
annotation helper, subject to local privacy and model/dependency review.

Preserve the user's desired system-first interaction: automatic candidate masks
would still need a way to rank/name likely banks. A user-click-first mask helper is
an alternative/fallback, not the same capability. Keep that distinction explicit
when choosing the smallest experiment. Setup assistance could run on the user's
computer; it need not imply running the same model continuously on an edge device.


## Licensing and custom algorithms — discussion round 6

User correction: the supplied research excluded certain libraries because of their
licenses and proposed original algorithm development. Keep that constraint visible
in every shortlist. The previous answer listed YOLO's capability without clearly
showing its excluded status; this was an omission, not an agreed change of direction.

Working adoption boundary from the research and user clarification:

- Keep pyorc, ffpiv, Ultralytics YOLO-seg, FastSAM, and OpenPIV outside the initial
  integration shortlist unless the user explicitly revisits licensing.
- Continue considering OpenCV, scikit-image, SAM 2, and MobileSAM as candidates,
  subject to the exact versions, dependencies, and weights being reviewed. A
  permissive license does not remove notice or other applicable obligations.
- Studying a project's capabilities does not mean importing or copying its code.
- This is a project selection constraint, not a claim that copyleft software is
  unlawful or that every integration automatically requires relicensing all code.

The original notes propose three distinct pieces:

1. Camera geometry: use OpenCV primitives directly rather than pyorc wrappers.
2. Velocity: potentially build a correlation/block-matching experiment using
   permissive primitives. This is optional later work for the riverbank-first goal,
   not a required initial subsystem or an accepted small-effort estimate.
3. Water-level scoring: design an original method to score candidate waterlines
   using known camera geometry and a surveyed cross-section instead of adopting
   pyorc's implementation. The claimed absence of permissive alternatives remains
   unverified. This method requires information our ordinary-bank approach may lack.

Assistant proposal for adapting the third piece to the current goal:
Build original application logic that compares a human-confirmed normal bank region
with later evidence of water coverage. Candidate steps are frame alignment, image
quality checks, current water-region evidence, overlap with the saved bank region,
and persistence across time. Output relative coverage change or cannot-judge;
do not convert coverage directly into metres, flow, or flood danger.

This is a proposed bank-coverage method, not a clean-room reproduction of pyorc's
cross-section method and not a selected algorithm yet. Segmentation assistance
helps draw the reference; the comparison logic is a separate component. Use
independent specifications and appropriately licensed components, rather than
translating upstream source and calling it original. Original work is not blanket
legal clearance; detailed licensing choices remain to be reviewed.

Sources rechecked on 2026-09-10:
- [Ultralytics license](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)
- [ffpiv license](https://github.com/localdevices/ffpiv/blob/main/LICENSE)
- [pyorc license](https://github.com/localdevices/pyorc/blob/main/LICENSE)
- User baseline, Section 5: hybrid implementation proposal.

No integration, new algorithm implementation, training, or formal documentation
change authorized or performed in this round.

## Reuse versus original logic — discussion round 7

User understanding: SAM 2, MobileSAM, and OpenCV have suitable licenses, while
surface velocity and water-level estimation would need our own library.

Clarification: keep these tools as licensing-suitable candidates, subject to their
actual distribution terms. OpenFloodAI declares MIT; the candidate licenses are
not necessarily identical to MIT. SAM 2's main code/checkpoints and MobileSAM's
repository use Apache-2.0; OpenCV 4.5+ uses Apache-2.0. Preserve required notices
and review bundled dependencies and artifacts. This is not a dependency adoption.
Sources: [SAM 2](https://github.com/facebookresearch/sam2#license),
[MobileSAM license](https://github.com/ChaoningZhang/MobileSAM/blob/master/LICENSE),
[OpenCV license](https://opencv.org/license/).

We do not yet know that a separate original library is necessary for either
physical measurement. The current proposal is smaller: original bank-coverage
comparison logic inside OpenFloodAI, reusing suitable image-processing components.
Surface velocity is optional later work. Absolute water height needs calibration
and reference information; custom software alone does not supply these inputs.
Do not turn avoiding certain dependencies into a decision to rebuild their entire
capability. Search and evaluate appropriate alternatives if those needs arise.

Working allocation: segmentation assistance from SAM 2 or MobileSAM (selection
pending), image processing from OpenCV, and original application logic for changes
in the confirmed bank reference. This is an architectural proposal, not final
implementation authorization or a finding that all alternatives have been exhausted.

## Minimum necessary capability — discussion round 8

User asks whether we may avoid building those measurement algorithms or adding
other libraries altogether. Clarification: yes, velocity and calibrated height may
be unnecessary for the initial bank-coverage goal. Avoiding those measurements does
not mean bank-coverage detection is already solved or needs no original logic.

OpenCV is already available. Whether it is sufficient for useful automatic bank
suggestions and later coverage assessment is unproven. SAM 2/MobileSAM remain
optional candidates if they reduce user correction effort or address observed
failures. Do not promise either that new dependencies are required or that OpenCV
alone will work. Keep the user's system-suggests/human-corrects workflow as the
intended interaction, with manual marking as a fallback.

No final tool choice or implementation decision was made in this round.

## Current-code alignment — discussion round 9

User asks whether the implementation already aligns with the riverbank-first plan
and which parts remain. Read-only code review on 2026-09-10, starting from local
main commit `79194df`; no tests, validation runs, or product edits performed.

Conclusion: the collection/review/history foundation aligns and can be reused.
The proposed bank-specific observation method is not implemented. Do not describe
pixel difference, a generic watched rectangle, or report baseline images as an
already implemented normal-bank reference system.

| Capability | Current coverage | Evidence / remaining gap |
| --- | --- | --- |
| Site setup, local videos, manifest, watched-area editing | Implemented | Home UI and server support the workflow, including separate watched-area editing. |
| Human time-window labels and machine comparison | Implemented | `review/label_comparison.py`; current agreement concerns visual change, not reliable rising/falling direction. |
| Frame sampling across reviewed windows | Implemented | `pipeline/local_poc.py` and `ingestion/evidence_sampling.py`; successive samples and first-sample-to-later pairs. |
| Reports, image review, explanation/status tags, run feedback | Implemented | `tools/openfloodai-home-ui.html`, review images and result explanation modules. |
| Run input snapshots/history | Implemented for existing inputs | `validation/input_snapshot.py`; future baseline image/region artifacts must also be captured when introduced. |
| Portable run export | Present on current main | `validation/run_export.py`; this supersedes the earlier discussion's assumption that export was only future work. New baseline assets would need inclusion. |
| Human-confirmed normal-condition bank baseline | Missing | Config only accepts a rectangular `reference_region`; no selected normal reference image, source/time, approval or baseline identity. |
| System bank suggestions with user correction | Missing | No SAM 2/MobileSAM integration or semantic bank proposal method found in active src/tools. Current selector draws a rectangle. |
| Bank shapes / masks | Missing | `config/site_config.py` defines x/y/width/height only; no bank polygon/mask representation. |
| Bank covered by water versus merely changed pixels | Missing | `vision/simple_signals.py` computes mean absolute pixel differences and upper/middle/lower band scores; no water/bank classification. |
| Relative increasing/decreasing bank coverage | Missing | `_system_result` in label comparison reduces evidence to change/no-clear-change/cannot-judge. A maximum change score has no direction. |
| Visibility and camera movement handling | Partial | Dark/unknown-time and insufficient coverage checks exist; whole-region-change heuristic requests review. No explicit image registration or demonstrated water-vs-fog/shadow/occlusion discrimination. |
| Sustained coverage trend and baseline replacement policy | Missing | Multiple frames are sampled, but no bank-coverage time series or human-approved normal-reference lifecycle. |
| Physical velocity, calibrated height, volume | Not implemented; not a first-goal requirement | Do not treat these as blockers for relative bank coverage. |

Specific interpretation cautions:

- `water_level_evidence_state = useful_water_level_evidence` is a heuristic name,
  not proof that a waterline was detected. Its implementation uses band differences.
- `baseline_frame_index` and `baseline_image_path` identify an earlier comparison
  frame from a reviewed window. They are not approved normal-condition evidence
  persisted for comparison across future videos.
- Current `agree` may pair a rising OR falling human label with `water_change_seen`.
  The report explicitly says the simple signal does not know direction. This is not
  yet a direction-sensitive evaluation metric.
- The risk engine is explicitly a threshold skeleton for test signals. Existing
  `NORMAL`, `WATCH`, or `WARNING_CANDIDATE` names do not validate flood danger.
- Existing quality checks, tests, and issue closure do not establish performance on
  a representative real bank dataset. Dataset readiness was not audited this turn.

Candidate work order for discussion, not implementation authorization:

1. Define the confirmed normal reference and bank annotation format, including
   source/time, approval, identity/version, and invalidation after camera/site changes.
2. Extend the existing setup flow with candidate bank suggestions and human correction;
   retain manual marking. Evaluate helper choices on approved images rather than
   assume a segmentation library solves semantic bank recognition.
3. Add alignment/visibility checks and evidence of water overlap with the fixed bank
   reference, then aggregate coverage over time. Preserve cannot-judge states.
4. Extend saved evidence and comparison rules to explain more/less/no-clear-change
   in bank coverage without claiming physical height or flood danger.
5. Extend snapshots/exports and validation examples for the new baseline artifacts.
   Judge methods by coverage errors, false changes, unclear cases, correction effort,
   and performance across conditions; define targets before training.

Useful existing code references (relative to this memory file):
- [Home UI](../tools/openfloodai-home-ui.html)
- [Config representation](../src/openfloodai/config/site_config.py)
- [Visual measurements](../src/openfloodai/vision/simple_signals.py)
- [Sample comparisons](../src/openfloodai/pipeline/local_poc.py)
- [Human comparison rules](../src/openfloodai/review/label_comparison.py)
- [Input receipts](../src/openfloodai/validation/input_snapshot.py)
- [Run exports](../src/openfloodai/validation/run_export.py)

No percentage-complete estimate is justified. Reuse the working review infrastructure;
the central bank-coverage capability still requires design and measured evaluation.

## Training path and algorithm candidates — discussion round 10

The user supports the proposed development direction and asks how it leads to ML
training and which algorithm to use. This is planning, not authorization to train
or finalize formal project documentation.

Assistant proposal: make the first trained model identify image regions, rather
than predict flood/no-flood. A compact semantic segmentation model could predict
visible water, exposed bank, and other visible areas, subject to a precise labeling
guide. Uncertain pixels should be explicitly ignored in training/evaluation, not
silently assigned to a known class. Image visibility/quality and model uncertainty
must still govern whether the system can judge a frame.

Data flow for a later experiment:

1. Save approved source videos and source/time metadata, site/camera/event grouping,
   baseline version, permissions, conditions, and human review provenance.
2. Use a selected pretrained SAM helper for draft outlines if useful; humans correct
   and confirm them. Include later water-covered views and hard cases, not only
   normal baseline images. An initial setup-region selection alone is insufficient
   pixel-level training data for changing water coverage.
3. Store frame masks separately from existing rising/falling/no-clear-change time
   labels. Masks teach image regions; time labels evaluate the combined observation
   pipeline. Neither machine agreement nor model drafts become truth automatically.
4. Freeze train/development/test membership by event/video, and where practical site.
   Adjacent frames from one event must not cross splits. Human-review the held-out
   annotations; never tune the model or thresholds against the locked test set.
5. Establish an OpenCV/classical baseline. Train a compact model only if the dataset
   gate is met and a defined failure warrants it. Keep inference/model assistance
   separate from custom training.
6. Apply current water masks to the aligned, human-confirmed baseline bank region.
   Measure image-space overlap and temporal change with ordinary application logic.
   This is not physical bank area, height in metres, or a flood probability.
7. Save model, preprocessing, threshold and dataset versions alongside run inputs.

Provisional model comparison, not a selected dependency:

- Start candidate: Torchvision LR-ASPP with MobileNetV3-Large, a compact semantic
  segmentation architecture. Adapt its output classes and fine-tune using reviewed
  masks if permitted pretrained weights are used. Generic pretrained output labels
  are not already our water/bank classes.
- Comparison candidate: DeepLabV3 with MobileNetV3-Large. Compare bank/water boundary
  errors and runtime against LR-ASPP and the classical baseline; no assumed winner.
- SAM 2 / MobileSAM retain the proposed annotation-helper role. Training them is
  not required for the proposed first compact-model experiment.
- Initial loss proposal: pixel cross-entropy with ignored uncertain pixels; consider
  class weighting or Dice loss only if error analysis justifies it. No final recipe
  or hyperparameters agreed.

Candidate acceptance evidence: water/bank overlap and boundary error, missed water
coverage and false coverage under shadows/glare, correct direction of coverage
change, false-change events, time-to-detect, cannot-judge rate, and latency/memory
on the intended device. Report results by visibility, weather, camera and event;
image segmentation scores alone cannot establish operational usefulness. No numeric
pass threshold or minimum dataset count has been agreed. 50–100 examples can help
explore the problem but do not establish training readiness or generalization.

Licensing remains a constraint: Torchvision's code uses BSD-3-Clause, but selected
weights, upstream dependencies, and data need their own review. Do not equate the
code license with blanket clearance of all training assets.

Primary sources checked on 2026-09-10:
- [LR-ASPP MobileNetV3](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.segmentation.lraspp_mobilenet_v3_large.html)
- [DeepLabV3 MobileNetV3](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.segmentation.deeplabv3_mobilenet_v3_large.html)
- [Torchvision license](https://github.com/pytorch/vision/blob/main/LICENSE)
- [SAM 2 upstream](https://github.com/facebookresearch/sam2)

All algorithm choices above are assistant recommendations for discussion, not
measured results or user-approved implementation decisions. Next: agree the first
training target and annotation requirements, then define the readiness gate.


## Goal correction — latest user agreement

The user explicitly confirms that OpenFloodAI stays with its main goal.
Segmentation and riverbank selection should strengthen the evidence and help the
user and machine visually select a riverbank baseline.

Use the existing labeling guide as the product reference: normal, rising, high,
going down, and unclear/degraded observations. Distinguish high water from rising
water. Reference evidence can include banks, pillars, markers and other useful
features; it does not replace the water-state determination or human review.

This corrects the assistant's overly narrow proposal to make bank segmentation the
central first model task. LR-ASPP and DeepLabV3 remain possible supporting
segmentation candidates only, not recommendations for the main model. Mask labels
are optional additional data if that supporting method proves useful. Existing
reviewed time-window labels remain central to evaluating the intended task.

The intended interaction remains system suggestions, human correction and
confirmation, with a manual fallback. The exact reference format, model, data gate,
comparison method and evaluation targets remain open.

Next discussion should start from the water-state task and ask which evidence and
temporal method support it. Do not resume from the superseded assumption that a
bank-coverage model is the product goal. Only this working memory is updated;
formal documentation and product code remain unchanged. The earlier illustrative
training-code exchange is not being added to this file.

## Proposed path to a finished model

User asks how the finished model will be made. This is an end-to-end planning
proposal, not a selected architecture, a readiness claim, or permission to train.

1. Agree the prediction contract against the labeling guide. Represent visible
   water condition and change over time, with a clear inability-to-judge path.
   Resolve the guide's NORMAL/HIGH/direction/visibility concepts against current
   machine-readable label values before training. High and rising can coexist;
   decide whether the output needs separate level/trend/quality fields rather
   than assuming these are mutually exclusive classes.
2. Build a reviewed dataset of short fixed-camera sequences, watched-region and
   optional confirmed baseline/reference information. Include normal, rising,
   high, falling and difficult views. Track permission, site/event, timestamps,
   label provenance and version. Region/mask annotations remain optional support.
3. Define grouped training/development/locked-test splits and readiness criteria.
   Measure the existing classical baseline before adding a trainable component.
4. Reuse an established network architecture if justified. A candidate design is
   a pretrained image feature extractor plus a temporal component that considers
   ordered frames. Exact architecture and input duration remain to be compared;
   single-image classification cannot by itself establish temporal direction.
5. Train/fine-tune using our reviewed data and development set. The resulting
   learned weights are our task-specific model, although the architecture is reused.
   Keep the locked test set out of tuning. Confirm licenses of code, weights and data.
6. Connect supporting evidence and quality checks. Bank/reference observations may
   be model inputs or separate supporting outputs; choose this through evaluation.
   Evidence shown in the UI must be traceable and must not be presented as the
   model's explanation unless the system actually used or independently verified it.
7. Evaluate the combined system on held-out full events, difficult conditions and
   unseen sites where possible. Check missed changes, false changes, high/normal
   confusion, unclear states, detection delay and device cost. Define acceptance
   targets before selecting the winning method. No production flood-accuracy claim.
8. Package weights together with class/output definitions, preprocessing, temporal
   sampling, thresholds, versions, license notices and evaluation evidence. Verify
   runtime/export equivalence on the intended device. Add a replaceable inference
   adapter to the existing run/report/history workflow and retain human review.

The deliverable is not just a weights file: it is a versioned inference package
plus a reproducible evaluation record. A successful bounded experiment is an MVP
model candidate; production/public-warning readiness remains a separate gate.
The whole plan can still conclude that a simpler non-neural method is preferable
if the evaluated neural candidates do not improve the defined task.
'''
p.write_text(s)
PY
## Future production and public-warning path

User asks how the model could ultimately support public flood warnings and production.
This establishes a future ambition, not authorization to deploy, send warnings, or
skip the current camera-first ML readiness scope. No guarantee of production
suitability is implied by completing a model-training experiment.

Assistant proposal: use evidence gates rather than a promised accuracy number or
date. Treat the model as one component in a complete warning system.

1. Agree a specific pilot site/community, relevant impacts, useful warning lead time,
   and responsible warning authority. Determine how observed camera conditions relate
   to actual impacts; rising/high water alone does not establish downstream danger.
2. Establish independent ground truth and predefined acceptance targets. Evaluate
   held-out complete events and hard conditions; measure missed hazardous events,
   false candidates per camera-day, detection delay, unclear/unavailable time and
   uncertainty. Record sample counts and limits, not just overall accuracy.
3. Run a live shadow pilot with no public messages. Compare observations with
   independent gauges, trained local observers or other appropriate evidence and
   existing official information. Multiple outputs from one camera/model are not
   independent corroboration. Field testing must cover representative conditions;
   a quiet period without hazardous events is insufficient evidence of recall.
4. Introduce operator-only candidates under an agreed review/escalation procedure.
   Define who reviews, acknowledges and acts, including when a reviewer is absent
   or evidence disagrees. Never turn loss of visibility/communications into NORMAL.
5. Prove operational reliability: power/network loss, stale frames, moved/blocked
   camera, secure configuration and updates, backup communication where needed,
   logs, monitoring, maintenance ownership, rollback, retention and local privacy.
6. Co-design any public-warning procedure with the responsible authority/community:
   authorized sender, recipients, language, action, accessibility, update/expiry and
   cancellation, delivery acknowledgement and drills. Keep ML output separate from
   the official warning decision; begin with human authorization.
7. Independent technical and operational review plus documented release acceptance
   precede limited production rollout. Expand site-by-site, monitor failures and
   suspend/revert when quality or reliability falls below agreed criteria.

Production operator decision support is an earlier milestone than authorized public
warning operation. A single trained model or high validation accuracy does not make
an end-to-end warning service ready. Our proposed additional signals support future
verification; they do not replace the camera-first MVP with forecasting.

Primary references checked 2026-09-10:
- [WMO Early Warnings for All](https://wmo.int/all-activities/build-resilience/early-warnings-all)
- [UNDRR early warning system definition](https://www.undrr.org/terminology/early-warning-system)
These describe risk knowledge, monitoring, warning communication, and preparedness
as connected elements. The staged rollout above is an OpenFloodAI planning proposal,
not a certification, official approval, or a complete jurisdiction-specific standard.

Open decisions: pilot location, operational partner, independent evidence, acceptable
errors and lead time, budget/ownership, and authority process. No final thresholds,
public-warning algorithm or production deployment selected.

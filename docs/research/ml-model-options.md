# ML Model, Dataset, And Cloud Options

This note compares possible machine learning paths for OpenFloodAI and records
the ADR for issue #108's ML readiness direction.

The [agreed ML readiness plan](../product/ml-readiness.md) records the living,
authoritative direction and takes precedence over earlier suggestions below.
This page provides research background and decision history, not an approved
dependency list.

Simple meaning: before choosing a model, we should understand what already exists, what can help now, and what is risky.

This is research only. It does not add model code, download data, connect to cloud services, or claim flood detection accuracy.

## Decision Record — 0001 ML Readiness Direction (Issue #108)

Status: Agreed 2026-09-11.

### Context

Issue #108 asked how OpenFloodAI should approach ML readiness and first-model
strategy: whether to train a flood/no-flood classifier, make riverbank
segmentation the main product, or center the product on reviewing water
conditions and change over time. The question also covered candidate tool
roles (SAM 2, MobileSAM, OpenRiverCam/pyorc, YOLO segmentation, and others),
licensing scope, and what a first temporal experiment would need.

The full research and discussion that led to this decision — including
candidate-tool evaluation, licensing corrections (e.g. pyorc's AGPL terms),
and ten rounds of proposal/correction — is preserved in this repository's
history on issue #108 and is not repeated here; this record exists to state
the agreed direction and its consequences, not to re-host that discussion.

### Decision

Camera-first water-condition review is the main goal, following the existing
[labeling guide](labeling-guide.md). A visible riverbank is the first
reference, with optional markers and assisted selection. Visual overlays are
supporting evidence. Machine observations stay clearly separate from human
comparison. Model evaluation is baseline-first, after the readiness gate
defined in [ML Readiness And First Model Strategy](../product/ml-readiness.md).

Segmentation and riverbank selection support visual baseline selection and
stronger evidence; they are not the main prediction goal or a mandatory
training prerequisite. No main model architecture has been selected. No
readiness pass, implementation, training, or public-warning approval is
implied by this decision.

`docs/product/ml-readiness.md` is the authoritative, living plan (data
quality, grouped splits, privacy, evaluation, candidate tool roles, licensing
scope, and the first possible temporal experiment). This page is the broader
research background. Both take precedence over any earlier proposal from the
original discussion.

### Consequences

- Training stays blocked until the readiness gate in `product/ml-readiness.md`
  is satisfied. Closing prerequisite issues does not by itself satisfy it.
- No dependency, model, or license choice is approved by this record. SAM 2,
  MobileSAM, and OpenCV remain candidates subject to version/weights/license
  review; pyorc/ffpiv, YOLO segmentation, and FastSAM are excluded from the
  initial integration shortlist under the current licensing preference (a
  scope decision, not a claim that all have identical license terms).
- Revisit this direction if bank references do not help, simpler methods work
  better, camera movement cannot be handled, or quality/device requirements
  cannot be met.

## Short Answer

There is no single public model that OpenFloodAI should trust to directly detect floods from every river camera.

Some existing tools can help with smaller jobs:

- find water-like areas in an image
- track a selected river area across video frames
- help humans label data faster
- train a future model after OpenFloodAI has safe labeled examples

Simple example: a model may help mark the water area in one camera view, but a person still needs to check whether that means real danger.

## Product Inspiration

One useful product reference is [Noema Flood Detection](https://noema.tech/flood/). Their page describes a smart-camera flood detection application that monitors water levels and flood-prone areas with computer vision. It mentions ideas such as water coverage, virtual rulers, edge processing, metadata output, and operator alarms.

OpenFloodAI can learn from this concept, but should keep its own open-source and safety-first path.

Ideas worth exploring:

- reference regions or virtual rulers in the camera image
- water coverage change over time
- metadata that other tools can read
- edge-first processing so the system can still work with weak internet
- operator review before alerts become public warnings

Simple example: instead of asking the model "is there a flood?", we can ask a smaller question first: "is water covering more of the marked river area than before?"

Important boundary: OpenFloodAI should not copy private product details, claim the same capability, or send automatic public warnings without field validation.

## Nepal Bhote Koshi 2026 Case Study

The Government of Nepal's
[Rasuwa-Bhote Koshi Flood Event assessment report](https://hydrology.gov.np/cm/files/Assessment%20Report%20II_Bhotekoshi%20Flood_2026_1789276630363.pdf)
is a useful real-world example for OpenFloodAI.

Key lessons for this project:

- The event was assessed as a sudden outburst linked to an ice-rock avalanche or
  landslide-dam process, not a normal rainfall flood.
- Warning time was very short near the source, so slow manual-only review is not
  enough for future operational systems.
- Several hydrological stations stopped transmitting or were damaged, so camera
  evidence can be valuable when gauges fail.
- Nepal initiated CCTV-based real-time river monitoring at Timure after the
  event, connected to 24-hour flood forecasting and warning services.
- The report describes CCTV as a complement to gauges, rainfall, telemetry,
  satellite/radar information, and field reports, not as a replacement for them.
- Recorded CCTV footage can support flood travel-time analysis, debris movement
  review, channel-change review, forecast verification, and future model
  evaluation.

Simple meaning: this supports OpenFloodAI's camera-first direction. Weather and
forecast data remain useful cross-checks, but the core product should still
focus on what the camera saw, what the machine detected, and what the human
reviewer confirmed.

Useful future label or metadata ideas from this report:

- event type: rainfall flood, GLOF, landslide-dam outburst, debris flow, unknown
  sudden flood
- visual evidence: debris, logs, boulders, muddy surge, blockage, obstruction,
  sudden water rise, camera view lost
- supporting evidence: rainfall amount, nearby gauge reading, seismic signal,
  official warning time, field report source
- system state: gauge available, gauge failed, camera online, camera offline,
  video usable, video unclear

Important boundary: this case study supports research and validation planning.
It does not prove OpenFloodAI can detect this class of event yet, and it does
not authorize automatic public warnings.

## Open-Source Model Options

### General Segmentation Models

Segmentation means drawing around parts of an image.

The agreed candidate roles, licensing exclusions, and limitations for SAM 2,
MobileSAM, and Ultralytics YOLO segmentation are recorded in the
[Tools And Research Boundaries table](../product/ml-readiness.md#tools-and-research-boundaries) —
this page does not restate that decision.

How segmentation may help in general:

- mark the river or water-like area
- help create labels for training data
- compare how the water area changes over time

Main limitation:

- these models are general vision tools, not verified flood-warning systems
- they may confuse shadows, roads, sky reflection, mud, rain, or glare with water
- large models may be too heavy for low-cost edge devices

Simple example: a segmentation model can help a reviewer select the river area
in a video. That selected area can become training or testing data later. It
should not automatically tell people there is a flood.

### Object Detection Models

Object detection means finding named things such as people, vehicles, bridges, or debris.

Useful options:

- lightweight detectors, subject to code and weights license review
- future custom detectors trained on OpenFloodAI labels

How they may help:

- detect floating debris if enough local examples exist
- detect bridge/road reference objects if they are visible
- support safety review if a scene has people or vehicles

Main limitation:

- flood risk is not one simple object
- many river cameras need water level and change over time, not only object boxes

Simple example: detecting a bridge rail is not the same as detecting flood risk. The useful signal may be whether water moves closer to that rail over time.

### Classical Computer Vision Baselines

Classical computer vision means simple image math before deep learning.

Useful options:

- fixed reference region
- brightness and blur checks
- frame difference over time
- edge/line changes near a known riverbank
- optical flow for movement

How it may help:

- cheap to run on edge devices
- easy to explain
- useful as a first baseline

Main limitation:

- can break when the camera moves
- can break in darkness, heavy rain, fog, glare, or dirty lenses
- cannot understand local flood danger by itself

Simple example: if a fixed camera usually sees a rock and later the rock disappears under water, a simple rule may notice the change. A reviewer still needs to decide what that means.

### Visual Markers And Optional Segmentation

Our main goal remains reviewing water conditions and changes over time. Bank
selection and segmentation are supporting tools, not a replacement for that goal.

Drawing a confirmed bank outline, baseline marker, or status on a video does not
require a segmentation library. Browser canvas or OpenCV can draw the overlays.
Automatically finding a water boundary or a bank area now covered by water is a
separate analysis task. Segmentation may help, but a changed pixel alone is not
proof of water.

Evaluate a simple OpenCV approach first. See the segmentation candidates and
licensing scope above; no dependency or model choice is approved here.

See [proposed video overlays](../architecture/windowed-video-evidence.md#proposed-video-overlays)
for the normal baseline, changing observations, unclear-view handling, and an
easy example. These overlays are proposed functionality, not current capability.

## Public Dataset Options

Public datasets can teach useful ideas, but many are not direct matches for fixed river cameras.

### FloodNet

[FloodNet](https://github.com/BinaLab/FloodNet-Supervised_v1.0) is an aerial drone image dataset from Hurricane Harvey. It includes segmentation labels such as flooded buildings, flooded roads, water, trees, vehicles, and grass.

How it may help:

- learn about flood-scene segmentation
- test basic segmentation training code later
- study how flood labels are organized

Main limitation:

- it is aerial drone imagery, not fixed river-camera imagery
- it focuses on post-flood scene understanding, not early river-level warning support

### Sen1Floods11

[Sen1Floods11](https://github.com/cloudtostreet/Sen1Floods11) is a satellite flood dataset for surface-water mapping. The dataset uses Sentinel-1 and Sentinel-2 imagery and flood labels.

How it may help:

- learn flood-water mapping methods
- compare labels and evaluation practices
- inspire broader flood context research

Main limitation:

- it is satellite imagery, not ground camera video
- it has different resolution, viewpoint, and timing from OpenFloodAI river cameras

### Cloud To Street / Microsoft Flood And Clouds Dataset

The [Cloud to Street - Microsoft Flood and Clouds Dataset](https://registry.opendata.aws/c2smsfloods/) contains Sentinel-1 and Sentinel-2 flood/cloud data on AWS Open Data.

How it may help:

- learn from public flood and cloud labels
- study satellite flood mapping workflows

Main limitation:

- it is also satellite data, not edge camera video
- cloud storage access and dataset size need planning

## What Training Data OpenFloodAI Eventually Needs

OpenFloodAI will need its own fixed-camera dataset.

Good training examples should include:

- normal river level
- rising water
- high water
- water going down
- day and night
- rain, fog, glare, and muddy water
- camera shake or camera moved
- dirty lens or blocked view
- missing frames or low frame rate
- examples from different rivers and seasons

Each example should keep useful metadata:

- site ID
- camera ID
- broad public location
- time range
- weather or visibility if known
- label version
- reviewer notes
- privacy and permission status

Simple example: one useful label could be "water covers the lower half of the reference region from minute 12 to minute 18." That is more useful than only labeling one frame as "flood."

## Google ML, Vertex AI, And Cloud Vision Options

Google tools may help later, but they should not be required for edge operation.

### Vertex AI

[Vertex AI](https://cloud.google.com/ai-platform/docs) can train and manage ML models. It supports AutoML and custom training. Google also documents [managed datasets](https://docs.cloud.google.com/vertex-ai/docs/training/using-managed-datasets), which can help organize labels and train/test splits.

Where it may fit:

- future cloud training
- experiment tracking
- model registry
- comparing model versions
- batch evaluation on labeled data

Where it should not fit yet:

- V1 edge runtime dependency
- automatic public warning decisions
- storing private camera data without a clear permission plan

### Cloud Vision API

[Cloud Vision API](https://docs.cloud.google.com/vision/docs) can label images and detect general objects/text. It is a managed API, not a flood-specific river-camera model.

Where it may help:

- quick experiments on sample images
- detecting obvious general labels
- checking whether cloud labels are useful enough to study further

Main limitation:

- it needs cloud access and credentials
- it is not trained for local river flood warning support
- sending real camera frames to a cloud API can create privacy and cost concerns

Simple example: Cloud Vision may label an image as "water" or "river." That does not prove the river is flooding.

## USGS And Public Water-Data Inspiration

[USGS Water Data APIs](https://api.waterdata.usgs.gov/) provide machine-readable water data such as streamflow, gage height, daily values, monitoring locations, flood-impact locations, and public imagery resources.

How this may help OpenFloodAI:

- inspire useful metadata fields
- compare camera signals against stream gage measurements where available
- learn from public water monitoring patterns
- build future evaluation datasets with public reference data

Main limitation:

- USGS data is strongest for places with USGS monitoring coverage
- OpenFloodAI may need to support places that do not have nearby public gages
- public water data is supporting evidence, not a replacement for local validation

Simple example: if a public gage says water height rose quickly, that can help evaluate whether a camera-based signal also changed at the same time.

## What Can Be Reused Now

Good near-term reuse:

- public dataset documentation and label ideas
- segmentation research and candidate evaluation planning; installation or use
  requires a separately scoped experiment
- simple image metrics for baselines
- USGS-style time-series and site metadata ideas
- Vertex AI concepts for future experiment tracking

Simple example: we can reuse the idea of a label guide before training anything. That costs little and prevents confusing labels later.

## What Should Wait Until Later

Wait on:

- training a custom flood model
- downloading large datasets into the repo
- cloud training jobs
- cloud credentials
- live camera ingestion
- automatic retraining
- public warning automation

Reason: OpenFloodAI first needs clear local records, privacy rules, sample review workflows, and a labeled dataset plan.

## What Should Run Locally At The Edge

These should stay edge-first:

- camera/feed health checks
- frame quality checks
- basic visual signal extraction
- lightweight inference when a model exists
- risk-state evaluation
- local record buffering
- degraded/unknown state handling

Simple meaning: if the network is down, the edge device should still know whether the camera is usable and should still save local evidence.

## What Should Not Be Automated Without Human Review

Do not automate these without field evidence and review:

- public evacuation messages
- sirens
- emergency SMS
- final flood declarations
- automatic model updates from new field data

Simple example: a model can create a `WARNING_CANDIDATE` record. A responsible human or approved local process should review before any public warning action.

## Risks And Limitations

Main risks:

- a general model may fail on local river conditions
- flood examples are rare compared with normal river footage
- random frame splits can make tests look better than reality
- night, fog, rain, glare, mud, and camera movement can break image logic
- satellite and drone datasets may not transfer well to fixed cameras
- cloud tools can add cost, privacy, and connectivity dependencies
- a single camera or single model should not be the only safety signal

Important boundary: no model should be trusted for public warnings without field validation, independent QA evidence, and a human-in-the-loop escalation plan.

## Recommended Next Practical POC Step

The next practical POC step should be:

1. Choose a small set of safe local or synthetic videos.
2. Define a simple labeling guide for reference regions and visible water changes.
3. Create a baseline that measures water-like coverage or reference-region change over time.
4. Save outputs as structured records.
5. Replay the records and compare them with human notes.

Simple example: start with one bridge camera view. Mark the river area, run the same video through the POC pipeline, save the scores, and ask whether the saved records match what a human sees.

Do this before training a custom ML model.

## Sources

- [Government of Nepal Assessment Report II: Rasuwa-Bhote Koshi Flood Event, 2026](https://hydrology.gov.np/cm/files/Assessment%20Report%20II_Bhotekoshi%20Flood_2026_1789276630363.pdf)
- [Meta Segment Anything Model 2](https://github.com/facebookresearch/sam2)
- [Ultralytics YOLO segmentation documentation](https://docs.ultralytics.com/tasks/segment/)
- [FloodNet supervised dataset](https://github.com/BinaLab/FloodNet-Supervised_v1.0)
- [Sen1Floods11 dataset](https://github.com/cloudtostreet/Sen1Floods11)
- [Cloud to Street - Microsoft Flood and Clouds Dataset](https://registry.opendata.aws/c2smsfloods/)
- [Vertex AI documentation](https://cloud.google.com/ai-platform/docs)
- [Vertex AI managed datasets documentation](https://docs.cloud.google.com/vertex-ai/docs/training/using-managed-datasets)
- [Cloud Vision API documentation](https://docs.cloud.google.com/vision/docs)
- [USGS Water Data APIs](https://api.waterdata.usgs.gov/)
- [Noema Flood Detection](https://noema.tech/flood/)

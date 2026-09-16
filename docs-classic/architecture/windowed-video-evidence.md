# Decision: Sample Video Evidence Across Each Review Period

Status: implemented for local POC review, pending field validation.

Related discussion: [issue #104](https://github.com/lamadipen/OpenFloodAI/issues/104).

## Problem

The old pipelines compared only the first two frames. Those frames can be almost
identical, or both black during a fade-in. They cannot explain a 30-second label.

## Decision Drivers

We need evidence from the correct period, clear records of unusable footage,
repeatable settings, and limited image memory. Missing evidence must not become
a successful comparison.

## Options Considered

- Use a fixed number of frames for every video. This is simple, but a short clip
  and a long clip would have very different spacing.
- Use a time interval with a sample limit. This gives useful spacing on short
  clips and still covers the end of long clips. We chose this option.

## Decision

Both local pipelines read every decodable frame and retain its metadata.
A frame with mean channel brightness below 5 on the 0–255 scale is marked
DEGRADED, with reason IMAGE_TOO_DARK. Unknown frame timing is also excluded.
This is a basic dark-image check, not a complete image-quality detector.

Site validation passes each video's label periods to the pipeline. Only the
period boundaries are used; the human's label value does not control sampling.
Without periods, the pipeline samples the full decoded clip.

The default interval is five seconds, with at most 120 samples per period.
The first and last usable frames are included. Longer periods use wider spacing
when necessary to meet the limit. The report records the actual sample times and
largest spacing.

Compare each sample with the previous sample, and with the first usable sample.
Do not duplicate the first pair. This provides both short and overall change
measurements. Both frame times must be inside the label period: start included,
end excluded.

The initial coverage rules require:

- At least two usable frames.
- At least 80% of the requested period covered by usable frames, estimated using
  the video's frame rate.
- No usable-frame gap larger than twice the requested interval plus one frame
  period. Missing opening and ending footage also count as gaps.

These are conservative prototype quality rules, not validated flood thresholds.
A period that fails is cannot_compare, with counts and a reason. Measurements
from a poorly covered period are marked as such and excluded from label scoring.
Their derived risk records use unknown input quality, not normal input quality.

Review images use the exact saved pair with the highest region change in each
period. Each image has a separate video-time caption. The report links the pair
to its signal record and shows missing coverage. A period without a usable pair
has no comparison images.

A rerun replaces its derived records and refreshes its generated review images,
so old measurements are not mixed with the new run.

## Easy Example

A person labels seconds 0–30 as water_level_rising.

- Seconds 0–4 are black: keep metadata and mark them too dark.
- Use clear frames around 5, 10, 15, 20, 25, and the last frame before 30 seconds.
- Compare 5→10, 10→15, and later consecutive pairs.
- Also compare 5→15, 5→20, and later samples to capture a slow overall change.
- Show the actual frame times in the report.

The report can say that usable footage shows visual change. It cannot judge the
dark opening or prove the direction of water movement.

## Consequences And Limits

The detection thresholds remain unchanged; that work belongs to #109.
A stronger score can mean scene or lighting change, not necessarily water change.
A stable high-water scene can still have a low change score.

Mean brightness may reject usable night footage or accept an incomplete fade.
The check does not yet detect blur, glare, camera shake, or every obstruction.
Video times use frame index divided by reported frame rate; variable-frame-rate
footage should be converted to constant frame rate before time-based validation.

Metadata grows with frame count. Images are loaded in bounded batches per period.
The decoder is read again for selected frames and images, so long videos and many
label periods cost extra processing time. The sample cap may miss brief events.
This local implementation is not an edge performance claim.

## Validation Evidence Required

Regression tests cover both pipelines, the issue's synthetic rising/falling
waterline, slow change, stable footage, dark openings, all-dark and single-usable-frame
clips, missing footage, long gaps, separate periods, exclusive end times, capped
sampling, exact review-image pixels, and reruns.

Real footage with reviewed regions is still required before making any claim
about detection accuracy or choosing field settings.

## Revisit Trigger

Revisit the settings if night footage is wrongly rejected, short events are
missed, variable frame timing is needed, or memory/decoding cost is too high.
Preserve unknown results when evidence is insufficient. Do not restore first-two-frame
comparisons as a fallback.

## Proposed Video Overlays

Status: supporting direction agreed in the [ML readiness plan](../product/ml-readiness.md)
for issue #108; detailed implementation remains proposed. The sampling and review
images described above already exist; the moving video overlays described here
are future work.

The main goal remains reviewing water conditions and changes over time, following
the [labeling guide](../research/labeling-guide.md). Riverbank selection and
segmentation would help people and the machine see supporting evidence.

### What The User Would See

A person selects a clear view recorded during normal conditions and confirms the
visible riverbank. The system could suggest a bank outline for the person to
correct, with manual selection available. A pillar or another stable marker can
provide an extra reference when available.

The video player could then show:

| Overlay | Meaning | Does it change? |
| --- | --- | --- |
| Blue bank outline | The riverbank confirmed in the normal reference view | Stays fixed to the same bank |
| Dashed baseline line | The water boundary in the normal reference, if visible | Stays fixed |
| Yellow estimated boundary | Where the machine estimates the water boundary at the displayed observation time | Updates when usable evidence is available |
| Shaded bank area | Part of the baseline bank estimated to be covered by water now | Updates with the observation |
| Text and time | The machine observation, its time window, and any visibility problem | Updates with the result |

Colours are illustrative; text and line styles should also explain each overlay.
The selected bank outline is a reference, not proof that the machine found water.
The first usable frame in a current validation window is also not automatically
a confirmed normal-condition baseline.

### Drawing And Detecting Are Separate Jobs

Drawing lines, markers, shading, and text does **not** require a segmentation
library. Browser canvas or OpenCV drawing tools can display saved coordinates.

Finding a trustworthy water boundary or covered bank area requires image analysis.
Segmentation, which separates an image into areas, is one possible approach. It
could help suggest a riverbank for a person to correct or estimate water coverage
on later frames. It is optional, and its suggestions still need evaluation.

Start by evaluating a simple OpenCV approach on approved examples. Consider SAM 2
or MobileSAM if they improve the specific selection or boundary task enough to
justify their cost. No new library or model has been selected. See
[ML model options](../research/ml-model-options.md#visual-markers-and-optional-segmentation).

### Keep The Display Honest

- Save each observation with its video timestamp, reference, and estimated shape
  so the player can show the matching evidence. Sampled observations do not prove
  what happened in every frame between samples; show the actual observation time.
- Keep the normal baseline anchored to the same physical bank. If the camera
  moves, align the views reliably or stop the comparison and request review.
- When the view is unclear, show “Cannot judge — water boundary unclear.” Hide
  unavailable estimates instead of showing an old boundary as a current result.
- Do not create a moving waterline from the current pixel-change score alone.
  Lighting, shadows, or camera movement can also change pixels.
- Show relative visual change. Do not report centimetres of water-level change
  without suitable calibration.
- Keep machine evidence separate from human comparison. A missing human label
  means “No human label for comparison,” not that machine evidence is unavailable.

### Easy Example

In the normal reference, a strip of riverbank is visible. The user confirms its
blue outline. Later, reliable analysis estimates that water covers part of that
strip. The blue outline stays in place, while the yellow boundary and shaded
area show the new observation. Text could say “More of the reference bank appears
covered by water” and show the compared times.

If glare hides the boundary in the next observation, show “Cannot judge” rather
than continuing to move the line. Bank coverage strengthens the evidence; it
does not by itself establish flood danger or authorise a public warning.

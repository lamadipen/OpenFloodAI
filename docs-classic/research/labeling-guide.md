# Human Labeling Guide For Water-Change Review

This guide explains how people should describe visible water changes in OpenFloodAI review images or video clips.

Simple meaning: before training ML, reviewers need to use the same words for the same things.

This guide does not prove flood danger. It does not create alerts or public warnings.

For the machine-checkable label file format, see [Human Label Format](human-label-format.md).

## Why Labels Matter

Good labels help the project learn from human review.

Messy labels create messy models later.

Simple example: if one person writes "high river" and another person writes "danger," the computer may not know those mean a similar thing. A shared label like `HIGH_WATER` is clearer.

## What Reviewers Should Look At

Start with the configured reference region.

The reference region is the watched part of the image, like a virtual ruler.

Look for:

- whether the river or water area is visible
- whether water covers more of the watched area than earlier
- whether water is close to a bridge support, bank, marker, road, or other reference point
- whether the view is too unclear to judge
- whether the camera moved or changed view
- whether the input is missing or unreadable

Simple example: if the camera watches a bridge pillar, focus on the marked part of that pillar. Do not label based only on sky, trees, traffic, or shadows outside the watched area.

## Main Labels

Use one main label for each reviewed image, clip, or time window.

| Label | Simple Meaning | Use When |
| --- | --- | --- |
| `NORMAL_WATER` | Water looks close to the usual visible level. | The watched region looks normal compared with the baseline or earlier frames. |
| `RISING_WATER` | Water appears to be increasing. | Water covers more of the watched region than earlier in the video. |
| `HIGH_WATER` | Water appears high in the watched area. | Water is near or above a known marker, bank, bridge support, or reference line. |
| `WATER_GOING_DOWN` | Water appears to be decreasing. | Water covers less of the watched region than earlier. |
| `UNCLEAR_VIEW` | The reviewer cannot judge water state safely. | The view is too dark, blurry, blocked, rainy, foggy, glared, or confusing. |
| `CAMERA_MOVED` | The camera view changed from the expected scene. | The watched area no longer matches the original view. |
| `POOR_VISIBILITY` | The scene is visible but hard to trust. | Rain, fog, low light, glare, dirty lens, or compression makes review weak. |
| `MISSING_OR_UNREADABLE_INPUT` | The input cannot be reviewed. | The file, frame, or stream is missing, broken, or unreadable. |

## Simple Label Examples

### `NORMAL_WATER`

Use this when the river is visible and looks close to the usual level.

Simple example: the same rocks, riverbank, or lower bridge area are visible as before.

### `RISING_WATER`

Use this when water covers more of the watched region than earlier in the same clip or compared with a trusted baseline.

Simple example: the lower half of a bridge pillar was dry at the start, but later more of it is covered by water.

### `HIGH_WATER`

Use this when water appears high near a known reference point.

Simple example: water reaches a painted marker, bridge support, road edge, or riverbank area that is normally dry.

Do not use this label to create a public warning. It only means the reviewed image shows high water evidence.

### `WATER_GOING_DOWN`

Use this when water covers less of the watched region than earlier.

Simple example: more of the bridge pillar or riverbank becomes visible again.

### `UNCLEAR_VIEW`

Use this when the reviewer cannot judge safely.

Simple example: the scene is too dark, the lens is blocked, or heavy rain makes the river hard to see.

Do not force unclear cases into `NORMAL_WATER` or `HIGH_WATER`.

### `CAMERA_MOVED`

Use this when the camera no longer points at the expected scene.

Simple example: the reference region was supposed to show a riverbank, but now it shows sky or a road.

### `POOR_VISIBILITY`

Use this when the image can still be seen, but confidence is low.

Simple example: the river is partly visible, but glare or fog makes the water boundary hard to trust.

### `MISSING_OR_UNREADABLE_INPUT`

Use this when there is no useful image to label.

Simple example: the video file cannot open, the frame is blank, or the stream is missing.

## How To Use The Reference Region

The reference region should guide the label.

Good reviewer question:

```text
What changed inside the watched box?
```

Avoid this question:

```text
Did anything change anywhere in the whole image?
```

Simple example: a car moving on a bridge outside the watched box should not become `RISING_WATER`.

If the watched box is wrong, add a reviewer note. Do not pretend the label is strong.

## How To Mark Uncertainty

Use uncertainty when the evidence is not clear.

Good uncertainty notes:

- `uncertain: true`
- `uncertainty_reason: too dark to judge`
- `uncertainty_reason: heavy rain on lens`
- `uncertainty_reason: camera view changed`
- `uncertainty_reason: water boundary not visible`

Simple example: if you think water may be rising but the image is foggy, label the main state as `UNCLEAR_VIEW` or `POOR_VISIBILITY` and explain why.

Do not force every frame into flood or no-flood.

## Suggested Reviewer Notes

Future reviewed examples should include notes like:

- what changed
- where it changed
- how confident the reviewer is
- whether the reference region looked correct
- whether privacy permission exists
- whether the clip can be used for training later

Simple example:

```yaml
label: RISING_WATER
uncertain: false
watched_region: lower bridge pillar
note: Water covers more of the lower pillar than at the start of the clip.
privacy_permission: approved_for_local_review
training_use: not_decided
```

## Privacy And Permission

Do not label or share real camera footage unless the project has permission to use it.

Do not commit reviewed images, private videos, exact private GPS coordinates, camera URLs, passwords, phone numbers, or emails.

Simple example: labels from synthetic images can go in GitHub. Labels tied to a real private camera should stay local unless permission says otherwise.

## Human Review Is Not A Public Warning

Labels are evidence for review and future testing.

They are not emergency instructions.

OpenFloodAI should keep these things separate:

```text
human label -> training/testing evidence -> future model evaluation
```

and:

```text
official public warning -> approved local authority or trusted emergency process
```

Simple example: a reviewer may label a clip as `HIGH_WATER`. That does not mean OpenFloodAI should send an evacuation message.

## Good First Labeling Set

Start small.

A useful first local review set could include:

- 2 `NORMAL_WATER` clips
- 2 `RISING_WATER` clips, if approved examples are available
- 1 `HIGH_WATER` clip, if approved examples are available
- 2 `POOR_VISIBILITY` or `UNCLEAR_VIEW` clips
- 1 `CAMERA_MOVED` or bad-reference-region example
- 1 `MISSING_OR_UNREADABLE_INPUT` case

Simple meaning: a small clear set is better than a large messy set.

## Current Boundary

This guide does not add ML training code, automatic retraining, uploads, alerts, dashboards, public warnings, or claims of flood detection accuracy.

It only gives reviewers a shared language for describing visible water changes.

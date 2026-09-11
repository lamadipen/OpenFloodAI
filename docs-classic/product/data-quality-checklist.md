# Labelled Data Quality Checklist

This checklist helps contributors prepare useful and safe validation examples.
It is for local validation and human review. It does not prove flood detection
accuracy and it does not create public warnings.

## Before You Start

- Use a local or synthetic video that you are allowed to review.
- Keep the video ID short and safe, such as `river-demo-001`.
- Use a broad location name, such as `Demo River near Example Town`.
- Do not add private videos, exact private coordinates, camera URLs, passwords,
  faces, license plates, phone numbers, or email addresses to Git.
- Set `approved_for_repo` to `false` unless the video is clearly approved.

## What Makes A Useful Video

A useful video should:

- show the watched river area clearly enough to review;
- keep the camera view mostly fixed;
- contain enough time before and after the change;
- have readable frames at the labelled time;
- use a configured reference region, such as a bridge pillar or bank marker;
- have a known frame rate or usable video timing when possible.

A video does not need to show a flood. Normal, unclear, dark, shaky, and blocked
videos are useful too when they are labelled honestly.

## Labelled Time Window

Use the smallest window that contains the change and enough context to judge it.
For a short local example, a window such as `[0, 30]` seconds is reasonable. For
a longer video, use the actual start and end seconds around the visible change.

Good window:

```text
Video: river-demo-001
Window: [30, 60]
Reason: water is visible before and after it changes.
```

Bad window:

```text
Window: [0, 1]
Reason: the change happens around 45 seconds, outside the label window.
```

Do not use overlapping windows unless there is a clear reason. A label at exactly
the start belongs to that window. Keep the same time units and use increasing
start and end values.

## Label Meanings

Use one of the machine-readable labels below for each reviewed window.

| Label | Use it when |
| --- | --- |
| `water_rising` | Water covers more of the watched area than earlier in the same window. |
| `water_falling` | Water covers less of the watched area than earlier in the same window. |
| `no_clear_change` | The watched area is usable, but there is no clear water change. |
| `cannot_judge` | The reviewer cannot safely decide because the evidence is unclear. |
| `camera_video_problem` | The video or camera view has a direct problem, such as missing, unreadable, or moved input. |

The current machine signal can detect visual change, but it does not reliably
know whether water is rising or falling. Keep the human label direction when a
person can see it, and remember that the machine result is only review evidence.

## When To Use Unclear Labels

Use `cannot_judge` when the view is too dark, blurry, blocked, glared, rainy,
shaky, or confusing to decide safely.

Use `camera_video_problem` when the input itself is missing, unreadable, frozen,
or the camera moved away from the expected scene.

Use `no_clear_change` only when the scene is usable and the reviewer looked at
the whole labelled window but saw no clear water change. Do not use it as a
shortcut for a dark or broken video.

Example:

```text
Good: cannot_judge because heavy glare hides the water boundary.
Bad: no_clear_change because the video could not be opened.
```

Unclear labels are valuable data. Do not force them into `water_rising` or
`water_falling` just to avoid an incomplete result.

## Good And Bad Examples

### Good Example

```json
{"video_id":"river-demo-001","time_window_seconds":[30,60],"human_label":"water_rising","confidence":"medium","note":"Water covers more of the lower bridge pillar by the end of the window."}
```

Why it is good:

- the window is long enough to compare;
- the watched area is named;
- the label describes visible evidence;
- confidence and notes explain the decision.

### Bad Example

```json
{"video_id":"river-demo-001","time_window_seconds":[0,1],"human_label":"water_rising","note":"Looks bad."}
```

Why it is bad:

- the window may not contain the change;
- the note does not say what changed or where;
- it may force a guess without usable evidence.

### Good Unclear Example

```json
{"video_id":"river-demo-002","time_window_seconds":[0,30],"human_label":"cannot_judge","confidence":"low","note":"The first half is dark and glare hides the water boundary."}
```

## Useful Location Details

Use broad, non-sensitive details that help a reviewer understand the scene:

- a public site name or safe site ID;
- a broad location, such as `Demo River near Example Town`;
- the camera ID, such as `camera-demo-01`;
- the watched object, such as `lower bridge pillar` or `riverbank marker`;
- the reference-region description.

Do not include exact private GPS coordinates, private stream URLs, credentials, or
personal contact details. If exact location data is needed for a future field
pilot, keep it private and obtain permission first.

## Privacy Rules

- Review private footage only with permission.
- Keep real videos and real review images local by default.
- Do not upload or publish footage through the validation tools.
- Do not commit raw media, private notes, faces, plates, exact sensitive locations,
  URLs, passwords, or tokens.
- Delete local raw video and generated evidence when the review is finished.
- Use synthetic videos or clearly approved public examples for repository tests.

## Final Check

Before adding a labelled example, ask:

- Can another reviewer find the change inside this time window?
- Is the watched/reference region correct?
- Does the label describe what is visible, not what we hope is true?
- Should this be `cannot_judge` or `camera_video_problem` instead?
- Is the video safe to keep locally or commit?
- Does the example avoid claiming flood accuracy?

This checklist supports future validation and ML planning. It does not start ML
training and does not turn human labels into production truth.

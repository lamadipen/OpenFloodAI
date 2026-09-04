# Real Hard-Case Sample Workflow

This page explains how to document confusing real-world samples safely.

Simple meaning: when a real video has glare, darkness, camera shake, or a blocked view, we can record what happened without committing private footage.

## Why This Exists

Hard cases are useful because they show where OpenFloodAI may be confused.

Simple example: if the camera shakes, many pixels change. That does not mean the river changed. The system should keep that case visible as `DEGRADED`, `UNKNOWN`, or `cannot_compare`.

This workflow is for review and validation only. It does not prove flood accuracy, train a model, send alerts, upload files, or publish warnings.

## Where Metadata Lives

Keep hard-case sample metadata inside the matching site folder:

```text
data/sites/<site-name>/expected-behavior/real-hard-case-samples.jsonl
```

Simple example:

```text
data/sites/example-site/expected-behavior/real-hard-case-samples.jsonl
```

The actual video may stay local in:

```text
data/sites/<site-name>/inputs/videos/
```

If the video is private or unclear for sharing, do not commit it. Keep only safe metadata.

## Metadata Fields

Each row should include:

- `case_id`: a short ID for this hard case
- `case_type`: the type of confusing case
- `video_id`: the matching video ID from the site manifest
- `approved_for_repo`: `true` only when the file is clearly safe to commit
- `human_review_needed`: usually `true` for real hard cases
- `expected_result`: usually `cannot_compare`, `UNKNOWN`, or `DEGRADED`
- `plain_reason`: simple reason a reviewer can understand
- `reviewer_notes`: short notes from the person reviewing the sample

## Safe Example

```json
{"case_id":"camera-shake-real-001","case_type":"camera_shake","video_id":"camera-shake-001","approved_for_repo":false,"human_review_needed":true,"expected_result":"cannot_compare","plain_reason":"The whole image moves, so pixel change may not mean water changed.","reviewer_notes":"Safe example metadata only. No real video is committed."}
```

Simple meaning: this tells us the case is useful, but the video should stay local.

## Hard-Case Types

Use one of these values when possible:

- `heavy_glare`
- `rain_or_noisy_image`
- `night_or_dark_frame`
- `camera_shake`
- `blocked_view`
- `compression_or_noise_artifacts`
- `missing_video`
- `unreadable_video`
- `camera_offline`

If a new type is needed, document it before using it widely.

## Approval Rules

Set `approved_for_repo` to `false` by default.

Only use `true` when all of these are clear:

- the video or image is allowed to be public
- the source and license are understood
- it does not reveal private people, homes, vehicles, or sensitive locations
- it does not include camera URLs, passwords, tokens, or exact private GPS details
- a maintainer agrees it is safe for the repository

Simple example: a short synthetic glare video can be approved for the repo. A real private camera clip should stay local.

## When Footage Cannot Be Committed

You can still document the sample.

Keep:

- the `case_id`
- the `video_id`
- the hard-case type
- broad notes, such as "sun glare hides the water area"
- whether a human reviewed it
- the expected safe result

Do not keep:

- private camera URLs
- exact private GPS coordinates
- screenshots that show people, homes, vehicles, or sensitive places
- personal contact details
- private field notes that identify people or restricted locations

## Review Steps

1. Put the real video in the local site folder if you are allowed to use it.
2. Add or update the site `manifest.jsonl`.
3. Add a hard-case row in `expected-behavior/real-hard-case-samples.jsonl`.
4. Add human labels when a person has reviewed the time window.
5. Run the local validation workflow.
6. Keep unclear cases visible as `DEGRADED`, `UNKNOWN`, or `cannot_compare`.

Simple example: if glare hides the river, the result should not be counted as a success. It should say the view is unclear and needs review.

## Current Boundary

This workflow does not add real footage, upload files, train ML models, send alerts, publish warnings, or claim real flood detection accuracy.

It only explains how contributors can document confusing real samples safely.

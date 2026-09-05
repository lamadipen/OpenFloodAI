# Validation Results And Known Limits

This page tracks what OpenFloodAI has tested so far, what the result looked like, and what we still do not know.

Simple meaning: this is the project truth page for validation. It should help a new reader understand how far the proof of concept has gone.

OpenFloodAI is still a proof of concept. These results are not public flood warnings, do not prove real flood detection accuracy, and do not replace local emergency judgment.

## What We Tested

So far, validation is local and small.

| Area | What Was Tested | Simple Result |
| --- | --- | --- |
| Video health | Missing, empty, and readable local videos | The code can say when a video is missing or unreadable. |
| Frame metadata | Local videos and generated test videos | The code can save frame IDs, timestamps, size, FPS, and frame hashes. |
| Visual signals | Full-frame and reference-region image changes | The code can create simple brightness, change, and watched-region band scores. |
| Region POC pipeline | A configured watched area inside a video | The code can save records for the selected area. |
| Review images | Biggest local visual changes | The code can save images so a person can review what changed. |
| Human labels | Small example label files | The code can read labels like `water_rising`, `no_clear_change`, and `cannot_judge`. |
| Label comparison | System output compared with human labels | The report can compare matching time windows and show `agree`, `disagree`, and `cannot_compare`. |
| Threshold tuning | A few prototype visual-change thresholds | The report can show how different threshold numbers change the comparison result. |
| Validation tracking | A plain-language known-limits page | The docs can now show what is tested, what is weak, and what should come next. |
| Multi-video site validation | A folder of local videos for one site | The runner can create one combined summary table for several videos and multiple label windows. |
| Hard-case expected behavior | Missing, unreadable, dark, glare, noisy, shaky, and blocked-view cases | The docs say these should stay `UNKNOWN`, `DEGRADED`, or `cannot_compare` instead of success. |

Simple example: a developer can run one local video, save POC records, add a human label, and compare whether the system output pointed in the same broad direction.

Current local validation can also run a whole site folder, create one combined report, and keep missing or unclear cases visible.

The current MVP also includes generated synthetic known-answer checks for rising,
falling, no-change, and unreadable videos. These checks run without stored media,
internet access, or private footage. They are regression checks, not real-world
validation evidence.

The test suite includes small deterministic synthetic videos for rising water,
falling water, no clear change, and unreadable input. These videos are generated
during tests and are not stored as media files in the repository. They provide
known-answer checks for the local pipeline without internet access or private
footage. Passing a synthetic test does not prove real-world flood accuracy.

Each site validation report now includes a short **Validation Scorecard** with the
number of videos reviewed, label windows, `agree`, `disagree`, and `cannot_compare`
counts, plus the most common notes for cases that need review. The scorecard is a
quick progress view for local testing. It is not an accuracy score and does not
prove flood detection.

## What Worked

- Local video files can be checked before processing.
- Local records can be saved as JSON Lines files.
- The project can keep records grouped by site and video.
- A user can mark a reference region, like the lower part of a bridge pillar.
- The system can create simple scores for full frames and selected regions.
- Region comparison now shows whether the upper, middle, or lower part of the watched area changed most.
- Review images can help a person inspect the biggest changes.
- Human labels can be compared with system output in a simple report.
- Human label windows can be compared with machine records from the same time range.
- `cannot_compare` stays separate and is not counted as success.
- The validation scorecard keeps `cannot_compare` visible and lists common review reasons.
- Hard-case expectations are documented for confusing inputs like glare, darkness, camera shake, and blocked views.

Simple example: if a person says a clip shows `water_rising`, and the system shows stronger change in the lower part of a watched bridge pillar while the upper part stays steady, the comparison may say `agree`.

## What Did Not Work Yet

OpenFloodAI has not yet proven that it can detect real floods.

Current gaps:

- The sample validation set is too small.
- The system does not yet know what water is with high confidence.
- A visual change may come from rain, glare, shadows, people, debris, camera movement, or compression.
- If the whole watched region changes, the signal stays cautious because it may not be water-level movement.
- The risk engine is still simple and test-oriented.
- Threshold tuning is one `video_id` at a time, not a full dataset study.
- Multi-video validation is local only and still depends on small, reviewed examples.
- Time-window comparison depends on machine records having usable timing or source-frame links.
- There is no locked test set yet.
- There is no field pilot evidence yet.
- Synthetic fixtures are not a substitute for real rivers, cameras, weather, or field evidence.

Simple example: if sunlight changes on the river surface, the system may see a visual change. That does not always mean water is rising.

## Known Limits

These limits should stay visible until better evidence exists.

- This is a proof of concept, not a finished warning system.
- Current outputs are for human review and development only.
- Current reports do not prove accuracy.
- Current reports do not prove safety.
- OpenFloodAI must not send public warnings by itself.
- Local emergency teams and community judgment remain responsible for real decisions.
- Private or sensitive videos should not be committed to git.
- More testing is needed across different rivers, cameras, weather, seasons, and lighting.

Simple example: a `WATCH` or changed score in a local run means "please review this evidence." It does not mean "tell people to evacuate."

## Current Validation Record

The current validation record is early and should be updated as more reviewed examples are added.

| Evidence | Current Status |
| --- | --- |
| Unit and contract tests | Available for current POC helpers. |
| Synthetic smoke test | Available for a safe end-to-end local check. |
| Local real-video workflow | Available for local-only review. Real videos should stay out of git unless license and size rules are handled. |
| Human label examples | Available as small example JSON Lines files. |
| Comparison report | Available for one video at a time. |
| Threshold tuning report | Available for one video at a time. |
| Multi-video validation report | Available for one local site folder. |
| Validation scorecard | Available in the multi-video report with counts, review reasons, and safety wording. |
| Time-window comparison | Available when machine records have matching timing evidence. |
| Reference-region band signal | Available as prototype evidence for human review. |
| Hard-case expected behavior | Documented with a safe example fixture. |
| Field validation | Not started. |
| Production readiness | Not started. |

## Next Validation Goals

Near-term validation should stay small and reviewable.

What is now in place:

1. Multi-video local validation for one site folder.
2. Combined validation summary reports.
3. Human label comparison.
4. Prototype threshold tuning.
5. Human label windows matched to machine records from the same time range.
6. Improved reference-region signal with upper, middle, and lower change scores.
7. Hard-case expected behavior for confusing inputs.
8. A plain-language validation scorecard for each site report.
9. A local Home UI report-history view.
10. A labelled data quality checklist.

Simple meaning: OpenFloodAI can now run local validation practice and explain what happened, but it still has not proven real flood detection.

General validation goals:

- Add a few approved validation clips for different conditions.
- Label each clip with simple human labels.
- Compare system output with human labels.
- Add more machine outputs inside each reviewed time window.
- Track where the system agrees, disagrees, or cannot compare.
- Keep unclear cases visible instead of hiding them.
- Add a locked validation split before any ML training.
- Test difficult cases like glare, rain, darkness, camera shake, and blocked views.
- Document every result in simple language.

Simple example: start with two normal clips, two possible rising-water clips, two bad-visibility clips, and one missing-video test. Then write down what happened for each one.

See [Hard-Case Validation Examples](hard-case-validation.md) for the current expected behavior list.

## How To Update This Page

When a new validation run is reviewed, add:

- the site or public label used for the video
- whether the clip was synthetic, public, or local-only
- the human label
- the system output
- whether the result was `agree`, `disagree`, or `cannot_compare`
- any weak spot noticed by the reviewer

Do not add private camera details, exact sensitive locations, faces, license plates, or large raw videos to the repository.

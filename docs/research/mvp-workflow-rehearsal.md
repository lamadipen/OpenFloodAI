# MVP Workflow Rehearsal

Prefer a visual walkthrough? Open [Your First End-to-End Review](../learning/end-to-end-workflow.html).

Use this page without the chat history. The goal is to check whether a new
contributor can add 5–10 labelled videos, run validation, and explain the results.
This is a workflow check, not a flood detection accuracy test.

## What you need

- A local checkout and Python 3.12 or newer.
- Five short synthetic or public, approved test videos from the same fixed view.
  You can repeat with ten videos after completing five.
- About 30–60 minutes and a place to record confusing steps.
- No private videos, camera credentials, uploads, public warnings, or ML training.

From the repository folder, set up and start the application:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 scripts/run_openfloodai_home_ui.py
~~~

Open http://127.0.0.1:8765/openfloodai-home-ui.html in a browser.
Keep the server terminal open. Stop it with Ctrl+C when finished.

Need safe practice files? Run the automated rehearsal below with -s. It prints
a temporary folder containing five generated AVI files. Use those source files
in the manual checklist with a new site. They are simple changing grey images,
not real river footage. These images may be marked unclear; that is expected.
Some browsers may not preview AVI files. Record that as a failed preview step,
or use a locally generated browser-compatible MP4; do not hide the problem.

## Checklist

For each step, record Pass, Fail, or Not tried. Do not mark a step passed simply
because the server returned success.

| Step | What to do | What to check |
| --- | --- | --- |
| 1. Start | Open the Home UI address above. | The page shows both review routes and the guided workflow. |
| 2. Create site | Choose Create Site. Use Site Name “MVP Rehearsal”, folder “mvp-rehearsal”, Site ID “site-mvp-rehearsal”, Camera ID “camera-mvp-rehearsal”. | The new site is selected. Config is found. Missing video or watched-area items remain visible. |
| 3. Add video | Choose Add Video To Site, select the site and a local file. Give it a unique Video ID. Choose Video purpose, Dataset group “practice”, and write a short note. | Leave Safe to share unchecked. The original file stays in place. |
| 4. Choose watched area | Preview a clear frame and drag a rectangle over a fixed riverbank or bridge area. Save the video. | The watched-area step becomes complete. If the video cannot preview, record the failure. |
| 5. Repeat | Add the remaining files, for a total of five. | All five IDs appear. Use clips from the same camera/view: the saved area belongs to the site and a later selection can replace it. |
| 6. Check manifest | Open the Manifest step. If missing/incomplete, use its create/repair action. | Five videos are tracked. Existing notes remain. Sharing is not enabled automatically. No manual JSON editing should be needed. |
| 7. Try machine-only | Before adding labels, read readiness and run validation. | It explains machine-only review. A report and evidence are created. Missing labels produce cannot_compare, not agreement. |
| 8. Add labels | For each of five videos, open Add Human Label, choose its ID, and enter start/end seconds inside the actual clip. Choose what you see. | Use “I cannot judge from this video” for unclear footage. For a ten-second generated file use 0 to 10 seconds. Labels are saved separately from intake metadata. |
| 9. Confirm readiness | Return to Run Validation and read every check. | Correct site, video count, watched area, labels, manifest, and local output are shown. Missing items are not hidden. |
| 10. Run with labels | Run Validation and wait for completion. | A new run folder is created. The earlier run remains unchanged. |
| 11. Review results | Read the Home UI counts, then the report, scorecard, comparison notes, and image paths. Open local paths in your editor/file manager if the UI does not open them. | Counts match. Images show actual compared times. An all-dark clip has an explanation instead of misleading comparison images. |
| 12. Explain | Ask the contributor to explain one result and one unclear case without help. | Record their explanation and any question they could not answer. Repeat with ten files if practical. |

The saved files for each run are under:

~~~text
data/sites/mvp-rehearsal/outputs/runs/<run-id>/
  validation-report.md
  scorecard.json
  run-metadata.json
  records/<video-id>.jsonl
  review-images/<video-id>/
  videos/<video-id>/summary.md
  videos/<video-id>/label-comparison.md
~~~

Do not commit this output folder or source media.

## Simple meaning of results

- Agree: the human label and machine evidence match under the current rules.
  It does not prove the system knows whether water rose or fell.
- Disagree: they do not match. Review the label period, watched area, and images.
- Cannot compare: evidence or a label is missing or unclear. This is not success.
- Machine-only: measurements can run, but there is no human label to compare.

Example: a person labels 0–10 seconds “Water is rising”. If the video is too dark,
cannot_compare is the honest result. Do not change the label just to increase
the Agree count.

## Failure checks

Use the rehearsal site only.

- Try running with no video or watched area. Record whether the UI explains the blocker.
- Include an all-dark video and an “I cannot judge” label. Confirm unclear states stay visible.
- Leave one video unlabelled, run again, and confirm its missing label is visible.
- For manifest repair, use a separate practice site with a local video but no manifest.
  Confirm repair creates tracking without enabling sharing.
- Inspect browser network requests if possible: application requests should stay on
  localhost. No media should be sent to an external service. Static page resources,
  if any, are not proof of a media upload; record destination and request type.
- If a step fails, save the error text and local evidence path. Do not attach private media.

## Automated rehearsal

~~~bash
python3 -m pytest tests/ui/test_home_server.py::test_mvp_rehearsal_setup_to_five_video_result_review -q -s
~~~

This uses a temporary localhost server and generated videos. It calls the real
site-setup, intake, manifest-repair, label, validation, and status endpoints.
It checks config persistence, source-file preservation, five manifest rows with
sharing off, records, images, scorecards, run history, and visible unclear states.
It blocks Python socket connections to destinations other than localhost.

This uses JSON intake rather than the browser's file picker/multipart request.
It does not prove browser preview, rectangle dragging, accessibility, or human
understanding. Other Home UI tests cover workflow visibility and missing states.

## Rehearsal result and follow-up

Automated evidence recorded on 2026-09-06: all 320 Python tests and three
JavaScript UI tests passed. Formatting, lint, type checks, and the strict
documentation build passed. The new rehearsal creates five local synthetic
videos, runs once without labels and once with five labels, and verifies both
saved runs and the status API. Both runs have zero agreements and five
cannot_compare cases; the second run uses five actual label windows.

Current assessment: **the core API path is rehearsed; contributor usability is
not yet confirmed.** A person still needs to complete the manual checklist.

The synthetic scenes can produce five cannot_compare results even after all five
labels are added. They lack reliable water-level evidence. Do not weaken the
pipeline or count successful requests as correct detection.

Known friction to track:

| Finding | Follow-up |
| --- | --- |
| Local paths may require an editor/file manager to open. | Confirm a new contributor can find the evidence; improve navigation if they cannot. |
| AVI preview support differs between browsers. | Test the supported browser and document a working local video format. |
| One watched area is shared by the site. | Keep clips from one view; review warnings when adding a different view. |
| An empty usable range may appear as “Nones to Nones” in detailed notes. | Replace this with “No usable frames” in a separate wording fix. |
| Cannot_compare can remain after labels are added. | Explain the evidence reason, not just whether label files exist. |
| New-contributor manual trial has not been done. | Complete the form below before calling the workflow independently usable. |

Copy and fill this record:

~~~text
Date and commit:
Contributor (optional name):
OS / browser:
Number of videos (5–10):
Synthetic or approved source:
Step results (1–12):
Machine-only run path:
Human-comparison run path:
Agree / Disagree / Cannot compare:
Unclear case explanation:
Any external media request observed:
Confusing steps and exact errors:
Needed help from another person or chat? Yes / No
Can a normal contributor complete this workflow without help? Yes / No / Not tested
Next fixes, owner, and issue links:
~~~

A passing manual rehearsal requires all steps to work or clearly explain missing
inputs, evidence paths to be findable, unclear results to be understood, and no
outside help needed. If not, record “No” and the next fixes. Keep issue #130 open
until this evidence is recorded; automated tests alone cannot answer that question.

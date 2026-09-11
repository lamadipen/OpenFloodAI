# Your First End-to-End Review

*Local MVP · Practical guide*

Create a site, add videos, run validation, and understand the result — without the chat history.

**Plan:** 30–60 minutes · 5 short practice videos

## Before You Start

This page is a guide. Follow step 1 to get OpenFloodAI running, then use the Home UI for the rest. Reading this page does not start validation.

<div class="grid cards" markdown>

-   **Machine-only review**

    ---

    Needs a site config, a video, and a watched area. Produces machine evidence. Without a human label, there is no human comparison.

-   **Human comparison review**

    ---

    Add human labels and confirm the manifest. The report compares what the machine measured with what a person saw.

</div>

!!! note
    Human labels are optional for running validation, but required for comparing the machine result with human review.

Use synthetic or approved practice videos. Keep sharing unchecked. This workflow does not send public warnings or train a model. A successful run does not prove flood detection accuracy.

Check the boxes as you go. They are a temporary aid, not a saved test record. Save your notes separately before closing this page.

## 1. Make Sure OpenFloodAI Is Running

If OpenFloodAI is already open in your browser, check the box below and skip to step 2.

- **Developers**: follow the [Developer Quickstart](../dev-quickstart.md) to set up and run the app from source.
- **Hydrologists & disaster-management users**: follow the [Quickstart](../end-user-quickstart.md) to download, install, and run the packaged app.

Keep it running in the background — the rest of this guide needs it.

<label><input type="checkbox"> I have OpenFloodAI open in my browser and can see its guided workflow.</label>

## 2. Create A Practice Site

Choose **Create Site**. Use these example values:

- Site Name: **MVP Rehearsal**
- Folder Name: **mvp-rehearsal** — filled automatically
- Site ID: **site-mvp-rehearsal**
- Camera ID: **camera-mvp-rehearsal**
- Privacy Notes: **Practice videos only.**

Choose **Create Folder Structure**. If that folder already exists, choose another name. Select your new site in the workflow.

<label><input type="checkbox"> The site appears and its config is found.</label>

## 3. Choose A Video And Enter Its Details

Choose **Add Video** to open **Add Video To Site**. Select your practice site and a short local video.

- Video ID: use a unique name such as **practice-01**.
- Video purpose: choose why this video is useful.
- Dataset group: choose **practice**.
- Difficult case type: leave **No difficult case** unless it applies.
- Video notes: write one sentence, such as "Clear view of the bridge; water looks steady."

!!! warning
    Keep **Safe to share in repository** unchecked. This form copies the file locally and updates its manifest details. Human labels are added separately.

Do not save yet if the watched area is still missing. Complete step 4 in the same form.

<details markdown="1">
<summary>I need safe synthetic practice files</summary>

With the environment activated, run:

```bash
python3 -m pytest tests/ui/test_home_server.py::test_mvp_rehearsal_setup_to_five_video_result_review -q -s
```

The test prints **Synthetic rehearsal files:** followed by a temporary folder. It contains five source AVI files. Select those files for a new manual practice site. They are simple grey scenes, not flood footage. Use "I cannot judge from this video" if you cannot identify water behavior.

Some browsers cannot preview AVI. Record that issue or use an approved browser-compatible local MP4. Do not skip watched-area selection and call the rehearsal complete.
</details>

<label><input type="checkbox"> I selected the right video and entered its details.</label>

## 4. Choose The Watched Area And Save

Use the video controls to choose a clear frame. Drag a rectangle around a fixed riverbank, bridge pillar, or other useful reference area. Avoid a black opening frame.

Choose **Copy Video And Update Manifest**. Confirm the watched-area step is complete.

!!! note
    The watched area is saved in the site's config. Use clips from the same camera view. Choosing an area for a later video can replace the site's saved area.

Repeat steps 3–4 until the site contains five videos. Give each a different Video ID. You can repeat with ten videos later.

<label><input type="checkbox"> Five videos are listed and the watched area is saved.</label>

## 5. Confirm The Manifest

The **manifest.jsonl** file is the list of video details. You should not need to edit it by hand.

Open the **Manifest** workflow step. Check that all five videos are tracked. If it says missing or incomplete, use its create/repair action and read the result message.

Existing notes should remain, and sharing should stay off. If repair reports a conflict, record it instead of ignoring it.

<label><input type="checkbox"> The manifest tracks all five videos.</label>

## 6. Try A Machine-Only Run

Before adding labels, read the **Run validation** readiness summary. Confirm the site, videos, watched area, and local output destination.

Run validation. With no labels, the report should clearly say human comparison is unavailable. **Cannot compare** is expected; it does not mean the software failed to run.

<label><input type="checkbox"> A machine-only run exists and missing labels are explained.</label>

## 7. Add A Human Label For Each Video

Choose **Add Label**. Select the site and an existing Video ID. Enter a start and end time in seconds, within the video's actual duration.

!!! note "Example"
    You review seconds 0–10. If the water looks steady, choose **No clear water change**. If you cannot see clearly, choose **I cannot judge from this video**.

Choose what you actually see, add useful reviewer notes, and save the label. Repeat for all five videos. A period ending at 10 seconds uses frames before 10 seconds; the end time is excluded.

A human label is a comparison reference. It does not train the machine or force agreement.

<label><input type="checkbox"> Each of my five videos has a human-reviewed time period.</label>

## 8. Run With Human Labels

Read the readiness summary again. Check config, video count, watched area, human labels, manifest, and output location. Resolve blockers or record them.

Choose **Run Validation** and wait. This creates a new folder under **outputs/runs/**. The earlier run should remain unchanged.

<label><input type="checkbox"> The new run finished and the earlier run is still available.</label>

## 9. Review The Result, Not Just The Completion Message

- **Agree:** the human label and current machine evidence match. This is not proof of flood accuracy or water direction.
- **Disagree:** they do not match. Review the label period, watched area, and images.
- **Cannot compare:** evidence or a label is missing or unclear. Do not count it as success.

Check the Home UI counts and open the report, scorecard, comparison notes, and images. If the UI shows a path without an open action, open that path in your editor or file manager.

```text
data/sites/mvp-rehearsal/outputs/runs/<run-id>/
  validation-report.md
  scorecard.json
  run-metadata.json
  records/<video-id>.jsonl
  review-images/<video-id>/
  videos/<video-id>/summary.md
  videos/<video-id>/label-comparison.md
```

Check the image time captions against the label period. A dark clip may have no comparison images; its report should explain why. Even with labels, the generated grey clips may all remain cannot_compare.

<label><input type="checkbox"> I can explain one result and one unclear case using the saved evidence.</label>

## 10. Record What Worked And What Was Confusing

Do not change labels just to increase the Agree count. Record failures and questions so the next contributor has a better workflow.

**Your rehearsal notes** — copy these into a local text file before closing:

<textarea style="width:100%;min-height:150px;padding:14px;font-family:inherit;border:1px solid #7d94a3;border-radius:8px" spellcheck="true">Date and commit:
OS / browser:
Number of videos:
Machine-only run path:
Human-comparison run path:
Agree / Disagree / Cannot compare:
Confusing steps or exact errors:
Could I finish without help? Yes / No
What needs fixing next:
</textarea>

No information in this box is sent anywhere. This guide has no network scripts or save service. Use your browser's Print command if you want a paper checklist.

If you started OpenFloodAI from a terminal, stop the server with **Ctrl+C**. If you're using the packaged app, use its tray/menu-bar **Quit** option. Leave practice media and output files out of commits.

<label><input type="checkbox"> I saved my notes and recorded any unfinished steps honestly.</label>

## If Something Goes Wrong

- **Page will not open:** check that the server is still running and use the address from step 1.
- **Video will not preview:** try an approved browser-compatible file and record the original format/browser.
- **Run is blocked:** read the missing items in readiness, especially the watched area.
- **Labels exist but comparison is unclear:** check exact Video ID, time period, frame quality, and detailed notes.
- **"Nones to Nones" in a report:** this is a known wording problem for an empty usable range. It means there were no usable frame times.

The workflow is not independently verified until a contributor completes these steps without help. The automated rehearsal alone does not prove that.

---

*OpenFloodAI · Local review evidence · No official public warnings*

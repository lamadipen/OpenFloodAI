# Review Workspace

The Review Workspace lets you run machine analysis first and add human labels
after looking at the saved evidence. Human labels are optional for analysis.
They are needed to compare a person's observation with the machine result.

Start the local Home UI:

```bash
python3 scripts/run_openfloodai_home_ui.py
```

Open the address printed by the server and select **Review Workspace** in the
Home navigation. The new page is at `/review-workspace.html`. Restart an older
Home UI server after updating the code so it can serve the new routes.

## 1. Set up a site

Select a site in the sidebar, or choose **Create site**. This opens the existing
Home site form inside a modal, including the first video and watched-area
selector. After saving, the workspace selects the new site. Use **Add media** to
add more videos or an image sequence. Media intake opens the existing Home form
in a modal. Save before closing it; closing refreshes the workspace.

Use the setup links to define the watched area and riverbank guides with the
existing editors in a modal. Choose a normal-condition reference where possible.
Save the setup, then close the editor.

## 2. Run analysis

Select **Open analysis form** to choose the analysis inputs in a modal.

For videos, the workspace analyses samples across the video without restricting
sampling to existing human-label windows. This does not mean every frame is
analysed. For image sequences, select a baseline image before running analysis.

Each analysis creates a new saved run. The earlier runs remain available.
Labels do not change the machine's visual measurements.

## 3. Review and label

Select a saved run. Click a timeline point or a row in the review queue to see
its evidence and the machine's explanation. The score describes visual change;
it is not water height or a flood warning.

- Videos show the start and end of a sampled comparison, using playback seconds.
  You can adjust the human-label start and end seconds.
- Images show the saved baseline beside the selected image, using capture time.
  The label is attached to that image pair and run.
- Watched-area and riverbank overlays come from the selected run's setup
  snapshot. They do not use later edits to the site's setup.

Select **Add human label** or **Edit human label** to open the label modal with
the selected evidence beside it. Choose what you see, add notes or quality
details, and select **Save label & next**. The existing label vocabulary is
retained. Review normal conditions and
poor-quality samples as well as large changes. Use **All** to see the full queue.

When the selected image has available `riverbank_crossing_v1` evidence, the
same form shows two additional questions: whether visual change crossed the
normal guide and whether the highlighted overlay matches what the reviewer
sees. Optional chips capture muddy water, glare, shadows, vegetation, snow, or
low light. The existing camera-stability answer is reused instead of asking
about camera movement again. The server links the review to the exact saved evidence record;
the reviewer does not enter an evidence ID.

Without a label, the page says **No human label for comparison**. Missing or
unclear evidence can also prevent comparison. An image comparison checks change
versus no change; agreement does not prove rising/falling direction or safety.

Video time is not matched to gage readings, including for time-lapse videos.
For images, each saved image is matched to its own USGS reading when the run is
made, and that match is saved with the run. The page shows the image time, the
reading time, the exact gap between them, the parameter and unit, and the USGS
quality status (provisional readings are marked as such). It never uses a
reading more than 15 minutes from an image; those images show **No matching
gauge reading**. Gauge readings are supplemental context, not an input to the
machine score.

A run made before gauge evidence was saved shows that it was **not captured**.
It is never rebuilt from gauge data downloaded later, so a finished run keeps
showing what it showed when it was made.

### Compare with another image

Beside the comparison view switch, **Compare with another image…** lets you pick any other saved
image of the same camera and see the two earlier-then-later in the same views, with a mask-based
water coverage change when both have accepted masks. It is optional and changes nothing unless you
press Save this comparison. See [Measure Water Change From Masks](water-change-measurement.md).

## 4. Assign a dataset group

Select **Edit dataset group** to open the dataset form in a modal.

Assign the whole video or image-sequence date range together. Avoid splitting
nearby frames from the same footage between practice and locked validation.

Videos use the existing `practice` and `locked_validation` manifest values.
Images use the existing date-range group assignments. Conflicting image date
ranges are refused rather than silently replaced. Tags do not start training
or grant permission to share media.

## Where reviews are saved

Video labels use the existing site label files under `labels/`. The workspace
also records which saved sample was reviewed. Image labels use that review log
with an explicit baseline and image identity, rather than video timestamps:

```text
outputs/runs/<run-id>/human-review/observations.jsonl
outputs/image-sequence-runs/<run-id>/human-review/observations.jsonl
```

The workspace recalculates displayed comparisons from saved machine evidence
and current reviews. It does not rewrite the original run report or scorecard.
Image review logs are workspace records; they are not automatically converted
into training data or consumed by the existing video-label tools.

Riverbank pilot answers are saved in this same observation log. They do not
change the machine result or enable the adapter in the risk engine.

Original media must still match the run's saved file hashes to be displayed or
reviewed. If a file was removed or replaced, restore the original file or run
analysis again. This workflow stays local and does not publish media or issue
public warnings.

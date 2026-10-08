# Curate Training Datasets

Reviewed images are valuable. **Dataset curation** lets a reviewer pick observations from
different saved runs and sequences into one local, versioned dataset for a specific
task, without copying JPEGs into folders by hand and without losing the evidence behind
each example.

This is curation only. It does not train a model, classify flooding, send an alert, or
publish anything. A later export story reads the frozen versions made here (see
[the handoff contract](#the-handoff-contract)).

## The workflow

1. Open a saved run and select an image. Inspect the image, its matched gauge reading,
   the machine mask if there is one, any human review, and the watched area and bank
   guides the run used.
2. In **Add to dataset**, choose a dataset, or create one on the **Datasets** page, and
   choose **Add this image**. The server checks that the image has the evidence the
   dataset's task needs. If something is missing, it is not added and every reason is
   shown.
3. Keep choosing images from other runs. Selecting the same source image again is safe:
   it resolves to the same observation and nothing is counted twice.
4. On the **Datasets** page see what you have: every example and its status, label
   counts, missing evidence, possible duplicates, and the split of examples into train,
   validation and test.
5. **Freeze** a version when the dataset is ready. A frozen version never changes.
   Editing the draft afterwards and freezing again makes the next version.

Existing runs work as they are. You do not need to download anything again.

## What each task needs

| Task | Required example | Needs a low image? |
| --- | --- | --- |
| Water segmentation | The image and a water mask for those exact image bytes that a person **accepted** | No |
| Low / middle / high classification | The image, a human review, the image's own matched gauge reading, and an approved, versioned category definition for the site | No (the whole dataset needs a suitable spread of categories) |
| Gauge-height estimation | The image and its own matched gauge reading with unit, station, time and quality | No |
| Rising / falling | An earlier and a later image **you choose**, from the same camera view, each with a gauge reading | Needs time context; the earlier image can already be high |

**Example.** A high-water image can be added to a gauge-height dataset on its own. To
teach a rise, add an earlier observation as a pair. The earlier one may itself already
be high. Pairs are never made automatically from unrelated runs or cameras: use **Use
as earlier** on one image, then **Add pair with this as later** on another.

If a mask was marked **needs correction**, it is not added. A corrected mask must come
from an established workflow; there is no mask editor here, and the page does not
pretend otherwise.

## Labels are kept apart

Each example keeps these in separate fields: the **collection group** (why the image was
sampled), the **numeric gauge reading**, the **human label**, **image quality**, and the
**review status**.

- A sampling batch's low, middle or high group depends on the date range someone
  requested. It is never turned into a training label.
- A gauge reading is instrument-derived supervision, not manually observed truth. A
  nearby station does not prove the same water elevation at the camera.
- Machine suggestions, human-accepted annotations and rejected records stay
  distinguishable. An accepted machine mask is recorded as `machine_mask_human_accepted`.
- An image a reviewer marked as one where the water level cannot be judged (or a camera
  problem) is not an approved visual-height example, even if its gauge reading is high.
  It may support quality evaluation.

## Category definitions for low, middle and high

Low, middle and high exist only where a person records, for one site:

- the gauge station, the measured quantity and the unit;
- numeric bands that meet at shared boundaries, and which side of each boundary belongs
  to which band;
- a source or rationale, an author and an approver.

There are no universal flood thresholds. A definition is never edited: a change is a new
version. A dataset names the version it uses, and examples categorized under an older
version are marked as out of date until you add them again. The numeric gauge reading is
always kept next to the category.

## Duplicates, conflicts and revisions

- The same source image reached from several runs is one observation.
- If the same observation gets a **different** annotation (a different mask, a changed
  review, a new definition version), you must choose **Replace** or **Keep existing**.
  Nothing is overwritten silently.
- Identical image content under different observations is flagged. It must not sit in
  two splits, and identical content with conflicting annotations blocks a freeze.
- Removing an example takes it out of the draft only. The image, the run and frozen
  versions are not touched.

## Train, validation and test

Neighbouring frames are never split at random.

- **By camera (default).** Every camera belongs to exactly one split. If you do not have
  enough independent cameras for validation and test, the dataset says so as a readiness
  gap. It does not invent a split.
- **By time blocks within one site.** For a local pilot. Blocks keep time together, and
  the version is marked as site-specific evaluation only. It says nothing about unseen
  cameras and does not meet the publication rule.
- Data from a locked validation range can only be in the test split and is never used for
  tuning. A camera with locked data cannot send its other data to training.
- A pair never straddles a split. Identical image content never appears in two splits.

## What a frozen version holds

```text
datasets/<dataset-id>/versions/v0001/
  images/            original image bytes, named by checksum
  masks/             accepted masks, when the task uses them
  samples.jsonl      one row per example, with its annotation and frozen evidence
  label-definitions.json
  splits.json
  manifest.json
  checksums.sha256
```

Each sample keeps the observation identity and original image checksum, the source URL,
system and capture time, the site and camera, the sequence and run, the baseline image
(its bytes are kept too when the file still matches what the run recorded; otherwise only its
checksum), the gauge reading with station, units, time gap and quality, the watched area and bank
guides the run used, the human review and its revision, and any machine output marked as
machine output. A version is written to a temporary folder, checksummed, then renamed into
place. **Verify** on the Datasets page recomputes every checksum.

Adding to a dataset never edits a run, a gauge match, a site configuration or a human
review. Choosing saved masks does not call a paid provider again.

## The handoff contract

`manifest.json` names `openfloodai.training_dataset`, version `1`. The later export and
publishing story (#207) can read `samples.jsonl`, `splits.json` and `checksums.sha256`
without this feature doing any upload. The splits already follow the site/camera
isolation that story requires, and a version says whether it meets that rule
(`meets_207_publication_rule`).

## What this does not do

It does not train or retrain a model, choose a network, change validation decisions,
upload to Hugging Face or Kaggle, add a mask editor, or ask for a manual review of every
image. OpenFloodAI is still not a flood-warning system.

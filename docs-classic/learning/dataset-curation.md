# Curate Training Datasets

Pick reviewed images from different saved runs into one local, versioned dataset for a
specific task, keeping the evidence behind every example. This is curation only: it does
not train a model, classify flooding, send an alert, or publish anything.

The full, current guide is `docs/learning/dataset-curation.md`. This page keeps the same
workflow and rules for the classic documentation.

## Use it

1. Open a saved run and select an image.
2. In **Add to dataset**, choose a dataset (or create one on the **Datasets** page) and
   choose **Add this image**. The server checks the evidence the task needs and explains
   anything missing instead of adding it.
3. Keep choosing images from other runs. The same source image is always one observation.
4. On the **Datasets** page review the examples, label counts, missing evidence,
   duplicates and the train, validation and test split.
5. **Freeze** a version. It never changes; editing and freezing again makes the next one.

## What each task needs

| Task | Required example |
| --- | --- |
| Water segmentation | The image and a water mask for those exact bytes that a person accepted |
| Low / middle / high classification | The image, a human review, its own matched gauge reading and an approved, versioned category definition for the site |
| Gauge-height estimation | The image and its own matched gauge reading with unit, station, time and quality |
| Rising / falling | An earlier and a later image you choose, from the same camera view, each with a gauge reading |

A single image never needs a low partner. For a rise, pair a high image with an earlier
one that may already be high. Pairs are never made automatically.

## Rules to remember

- Collection group, gauge value, human label, image quality and review status are separate
  fields. A sampling group is never a training label.
- Low, middle and high exist only from approved, versioned site definitions with a unit,
  boundary rule and source. There are no universal flood thresholds.
- An image marked as one where the water level cannot be judged is not an approved
  visual-height example.
- A different annotation for an observation already in the dataset needs an explicit
  **Replace** or **Keep existing**.
- Neighbouring frames are never split at random. Each camera is in one split, locked
  validation data is only in test, and a pair never crosses a split. Too few cameras is
  reported as a gap.
- Removing an example only takes it out of the draft.
- A frozen version keeps the original images, masks, evidence, labels, split and checksums,
  and is the local handoff for the later export story. Nothing is uploaded.

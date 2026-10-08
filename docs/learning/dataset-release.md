# Export A Dataset Release

A **release** is a clean, versioned export of one frozen training dataset (see
[Curate Training Datasets](dataset-curation.md)). It is built for other researchers: it
holds approved images and the metadata needed to reproduce each example, and it leaves out
everything internal. Building a release never uploads anything.

```text
Curate and freeze a dataset  ->  record approvals  ->  build  ->  verify
  ->  (optional) upload to a PRIVATE Hugging Face repository  ->  checklist  ->  you publish
```

OpenFloodAI is not a flood-warning system. A release is research data. It claims no model
accuracy.

## Use it from the Datasets page

Open a dataset that has a frozen version. Under **Release for sharing** you can do every step
below without the command line:

1. **Approvals** shows which sources and sites in the frozen version are still missing an
   approval, and has a form for each. The privacy form makes you tick faces, license plates
   and private property.
2. **Build a release** is disabled, with the reasons, until the approvals are in place. It
   shows the result: how many examples were released and how many were left out.
3. Each release has **Verify**, a **Checklist** you tick as you complete it, **Upload
   privately** and **Kaggle metadata**.
4. **Upload privately** sends a verified release to a **private** Hugging Face repository only.
   It needs the `HF_TOKEN` environment variable set where you started the app (the page says
   whether it is found and never asks for it or shows it), the optional Hugging Face library,
   and a confirmation that makes you type the repository name again.

Making a repository public is not in the app. Do that on Hugging Face yourself, after the
checklist.

The command line does the same things and is described below.

## Before you build: record the approvals

The release refuses anything a person has not approved. It never guesses or fills these in.

1. **Source reuse.** For each image source system (for example `usgs_nims`), record the
   license and the credit text. USGS material must be credited to the U.S. Geological
   Survey. Images from a source with no recorded approval are excluded.
2. **Annotation license.** Record the license of OpenFloodAI's own annotations.
3. **Each site.** Record how its location may be shown (generalized to a few decimals by
   default, hidden, or exact with a named approver) and that a privacy review covered
   **faces, license plates and private property**.

```bash
python3 scripts/export_dataset_release.py approve-source --source-system usgs_nims \
  --license-name "U.S. Government work" \
  --credit "Images courtesy of the U.S. Geological Survey (USGS)." \
  --reuse-note "Public USGS camera imagery." --approved-by "Your Name"

python3 scripts/export_dataset_release.py approve-annotation-license \
  --spdx-id CC-BY-4.0 --holder "OpenFloodAI contributors" --approved-by "Your Name"

python3 scripts/export_dataset_release.py approve-site --site-id <site_id> \
  --reviewed-by "Your Name" --faces-reviewed --license-plates-reviewed --private-property-reviewed
```

Approvals are saved in `data/release-policy.json` with who approved them and when. That file
is local and git-ignored, like the rest of `data/`.

## Build

```bash
python3 scripts/export_dataset_release.py build --dataset-id <id> --dataset-version 1 \
  --release-version v0.1 --notes "Small reviewed sample." --output-dir exports
```

This writes `exports/openfloodai-dataset-v0.1/`:

```text
README.md                dataset card: sources, schema, intended use, limits, bias, safety
LICENSE-DATA.md          the dual notice for source imagery and annotations
CHANGELOG.md             release notes; a new version adds to it
metadata.jsonl           one row per example (metadata.parquet too with --parquet)
sites.json               site and camera, generalized location, credit
images/<site>/<camera>/  original image bytes (and baseline images)
masks/                   accepted masks, for segmentation datasets
splits/                  train.jsonl, validation.jsonl, test.jsonl
label-definitions.json   the approved category bands, for classification datasets
REJECTIONS.md            every excluded observation and why
RELEASE-CHECKLIST.md     what to confirm before anything becomes public
checksums.sha256, release-manifest.json
```

It reads only the frozen dataset version, never a working site folder.

### What is kept out

- Local paths, secrets, private notes, reviewer ids and internal run or folder names.
- Anything from a source or site without a recorded approval, with the reason in
  `REJECTIONS.md`.
- Exact GPS unless a named person approved it.

### Labels stay separate

Human labels, review status and quality answers are separate columns from gauge readings and
from `machine_*` fields. Machine output is never ground truth. Samples a reviewer marked as
unjudgeable or a camera problem stay in the data under those labels as explicit quality
classes. The sampling group is kept as `collection_group` and is not a label.

### Splits never leak

Every released example is in exactly one split, and a camera is in exactly one split. The
build fails if a camera would appear in two. Identical image content is released once and the
repeat is reported. Datasets split by time blocks cannot be released, because that split is
site-specific evaluation only.

### Versions

- **v0.x** are private drafts. They may have gaps (for example no validation camera yet); the
  gaps are listed in the manifest and the card.
- **v1.0 and later** need released cameras in train, validation and test.
- A release is never replaced. A correction or removal is a new version with notes.

The same frozen inputs rebuild the identical release (same content digest).

## Verify

```bash
python3 scripts/export_dataset_release.py verify exports/openfloodai-dataset-v0.1
```

Checks every checksum, the required files, the metadata fields, that each example is in exactly
one split and no camera is in two, the dataset card sections, and scans every text file for
local paths and secret-like strings. `--require-checklist` also needs every box in
`RELEASE-CHECKLIST.md` ticked. The checklist is the one file left out of the checksums, because
ticking a box edits it; everything else is frozen.

## Optional: private Hugging Face upload

Install the optional extras first: `pip install "openfloodai[export]"`. Then, with a token in
the `HF_TOKEN` environment variable:

```bash
python3 scripts/export_dataset_release.py upload-hf exports/openfloodai-dataset-v0.1 \
  --repo-id your-name/openfloodai-v0-1 --yes
```

It uploads only a release that passes verification, only to a **private** repository, and
refuses a repository that is already public or already holds a release. The token is read
from the environment and never written down. Making the repository public is a separate
step you take yourself after completing `RELEASE-CHECKLIST.md`: confirm the dataset viewer
loads, spot-check images against the privacy review, check credits and splits, and record who
approved publishing.

`metadata.parquet` is optional (`build --parquet`, needs `pyarrow`). JSONL is always written.

## Optional: Kaggle mirror

```bash
python3 scripts/export_dataset_release.py kaggle-metadata exports/openfloodai-dataset-v0.1 \
  --owner your-kaggle-name --out dataset-metadata.json
```

This only writes the metadata file. Upload the identical release files with it using
Kaggle's own tools. There is no Kaggle upload code here.

## What this does not do

It does not publish anything automatically, train or select a model, change validation
decisions, use machine predictions as labels, or publish working site files.

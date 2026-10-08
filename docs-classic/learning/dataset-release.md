# Export A Dataset Release

A release is a clean, versioned export of one frozen training dataset, built for other
researchers. Building it never uploads anything. The full, current guide is
`docs/learning/dataset-release.md`; this page keeps the same workflow and rules for the
classic documentation.

## From the Datasets page

Open a dataset with a frozen version and use **Release for sharing**: record approvals (the
privacy form needs faces, license plates and private property ticked), build, verify, tick the
checklist, and optionally upload privately. The build button stays disabled, with reasons, until
the approvals are in place. Upload goes to a private Hugging Face repository only, needs
`HF_TOKEN` in the environment (the page never asks for or shows it), and needs the repository
name typed again. Making a repository public is not in the app.

## Steps

1. Curate and freeze a dataset (see Curate Training Datasets).
2. Record the human approvals the release depends on, with your name: the reuse permission
   and credit for each image source, the license for OpenFloodAI's annotations, and for each
   site its location rule and a privacy review covering faces, license plates and private
   property. Nothing is guessed. Images from an unapproved source or site are excluded.
3. Build with `scripts/export_dataset_release.py build`. It reads only the frozen version and
   writes a folder with a dataset card, license notice, changelog, metadata, images, splits,
   a rejection report, a checklist, checksums and a manifest.
4. Verify with `scripts/export_dataset_release.py verify`.
5. Optionally upload to a private Hugging Face repository (`upload-hf --yes`, with the token
   in `HF_TOKEN`) and complete `RELEASE-CHECKLIST.md` before making anything public.

## Rules to remember

- Local paths, secrets, private notes and internal ids are never included. Locations are
  generalized unless an exact location was approved.
- Labels, gauge readings, quality answers and machine output are separate columns. Machine
  output is never ground truth.
- Every example is in exactly one split, and a camera is in exactly one split. The build
  fails if a camera would be in two. Time-block datasets cannot be released.
- v0.x are private drafts and may list gaps. v1.0 and later need cameras in train, validation
  and test.
- A release is never replaced. A correction is a new version with release notes.
- The same frozen inputs rebuild the identical release.
- Upload is opt-in, private only, and refused for a repository that is public or already holds
  a release. Kaggle gets a metadata file only.

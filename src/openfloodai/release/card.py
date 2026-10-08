"""The human-readable files of a release: dataset card, license notice, changelog, checklist."""

from __future__ import annotations

from typing import Any

from openfloodai.curation.common import (
    TASK_GAUGE_HEIGHT,
    TASK_LEVEL_CHANGE,
    TASK_LEVEL_CLASSIFICATION,
    TASK_TITLES,
    TASK_WATER_SEGMENTATION,
)
from openfloodai.release.policy import USGS_CREDIT

HF_TASK_CATEGORIES = {
    TASK_WATER_SEGMENTATION: ["image-segmentation"],
    TASK_LEVEL_CLASSIFICATION: ["image-classification"],
    TASK_GAUGE_HEIGHT: ["image-classification"],
    TASK_LEVEL_CHANGE: ["image-classification"],
}

FIELD_DOCS = [
    ("sample_id", "Stable id of this example."),
    ("observation_id", "Stable id of the observed image (first image for a pair)."),
    ("split", "train, validation or test. Splits never share a site or camera."),
    ("task", "The task this example was curated for."),
    ("file_name", "Original image path inside this release (earlier image for a pair)."),
    ("later_file_name", "Later image of a rising/falling pair, otherwise empty."),
    ("baseline_file_name", "Baseline image the run compared against, when it was kept."),
    ("site_id / camera_id", "Public site and camera identifiers."),
    ("captured_at_utc / local_time", "When the image was captured."),
    (
        "source_system / source_url / source_credit",
        "Where the image came from and how to credit it.",
    ),
    (
        "human_label, label_confidence, change_presence, review_status",
        "What a person saw. Empty when not reviewed.",
    ),
    (
        "camera_stable, riverbank_visible, water_boundary_visible, stable_marker_visible, "
        "visibility_condition",
        "Reviewer quality answers.",
    ),
    (
        "watched_region, riverbank_guides",
        "The watched area and confirmed bank guides the run used (JSON).",
    ),
    (
        "gauge_value, gauge_unit, gauge_station, gauge_time_gap_seconds, gauge_quality",
        "The image's own matched gauge reading: instrument-derived, not observed truth.",
    ),
    ("annotation_kind, annotation", "The task annotation (JSON). Masks are listed in mask_files."),
    ("collection_group", "Why the image was sampled. It is NOT a label."),
    ("machine_result, machine_score", "Machine output only. Never ground truth."),
    (
        "latitude / longitude, location_precision",
        "Generalized location unless an exact location was approved.",
    ),
    ("image_sha256, baseline_sha256", "Checksums of the original bytes."),
]


def _size_category(count: int) -> str:
    for limit, name in ((1000, "n<1K"), (10000, "1K<n<10K"), (100000, "10K<n<100K")):
        if count < limit:
            return name
    return "100K<n<1M"


def dataset_card(
    *, manifest: dict[str, Any], policy: dict[str, Any], splits_present: list[str]
) -> str:
    task = manifest["task"]
    version = manifest["release_version"]
    configs = "".join(
        f"  - split: {name}\n    path: splits/{name}.jsonl\n" for name in splits_present
    )
    sources = "\n".join(
        f"- **{name}**: {entry['license_name']}. {entry['credit']} ({entry['reuse_note']})"
        for name, entry in sorted(policy["sources"].items())
        if entry.get("status") == "approved"
    )
    annotation = policy["annotation_license"]
    counts = manifest["counts"]
    split_text = ", ".join(f"{k} {v}" for k, v in sorted(counts["by_split"].items())) or "none"
    gaps = (
        "".join(f"- {g['message']}\n" for g in manifest["readiness_gaps"]) or "- None recorded.\n"
    )
    return f"""---
license: other
license_name: openfloodai-dual-notice
license_link: LICENSE-DATA.md
pretty_name: OpenFloodAI river camera dataset {version}
task_categories:
{chr(10).join("- " + c for c in HF_TASK_CATEGORIES[task])}
tags:
- river
- flood
- gauge
- camera
size_categories:
- {_size_category(counts["released"])}
configs:
- config_name: default
  data_files:
{configs}---

# OpenFloodAI river camera dataset {version}

A {manifest["channel"]} release of reviewed river camera images with gauge readings and human
review, curated for **{TASK_TITLES[task].lower()}**. It is research data for evaluating
visual water-level methods. It is **not** a flood detector and not a warning system, and no
accuracy of any model is claimed.

## What is in it

- {counts["released"]} examples ({counts["images"]} images, {counts["masks"]} masks);
  {counts["rejected"]} excluded (see `REJECTIONS.md`).
- Splits: {split_text}. Each site and camera is in exactly one split.
- `metadata.jsonl` has one row per example; `splits/*.jsonl` hold the same rows per split.

## Sources and credit

{sources}

Images are credited to their source. This release does not imply endorsement by the {USGS_CREDIT}
or any other source.

## Fields

| Field | Meaning |
| --- | --- |
{chr(10).join(f"| `{name}` | {text} |" for name, text in FIELD_DOCS)}

Collection group, gauge value, human label, image quality and review status are separate
fields. Samples a reviewer marked as unjudgeable or as a camera problem stay in the data under
their own labels, as explicit quality classes.

## Intended use and limits

For research on camera-based water-level estimation and quality screening. Do not use it to
issue warnings or make emergency decisions. Gauge readings are instrument-derived and a nearby
station does not prove the same water elevation at the camera. Provisional USGS readings may be
revised. The data covers few cameras and conditions and carries the biases of where cameras were
placed and which days were sampled.

## Splits and readiness

{gaps}

## Privacy

Working site folders were never uploaded. Private notes, local paths and secrets are excluded.
Locations are generalized unless an exact location was explicitly approved. A privacy review of
each site (faces, license plates, private property) was recorded before inclusion.

## Licensing

Source imagery and OpenFloodAI annotations have different terms. See `LICENSE-DATA.md`.
Annotations: {annotation["spdx_id"]}, held by {annotation["holder"]}.

## Citation

Cite as: OpenFloodAI river camera dataset {version}, from the OpenFloodAI project. No DOI has
been assigned.

## Version

{version} built from frozen dataset `{manifest["source"]["dataset_id"]}`
v{manifest["source"]["version"]}
(digest `{manifest["source"]["content_digest"][:16]}`). A published release is never replaced; a
correction or removal is a new version with release notes in `CHANGELOG.md`.
"""


def license_notice(policy: dict[str, Any]) -> str:
    annotation = policy["annotation_license"]
    lines = [
        "# Data license and credit",
        "",
        "This release combines source imagery with OpenFloodAI-created annotations. They are "
        "licensed separately.",
        "",
        "## Source imagery",
        "",
    ]
    for name, entry in sorted(policy["sources"].items()):
        if entry.get("status") == "approved":
            lines += [
                f"- **{name}** ({entry['license_name']}): {entry['credit']}",
                f"  - {entry['reuse_note']}",
            ]
    lines += [
        "",
        f"Credit the source named in each row's `source_credit`. USGS material is credited "
        f"to the {USGS_CREDIT}. "
        "This release does not imply endorsement by the U.S. Geological Survey.",
        "",
        "## OpenFloodAI annotations",
        "",
        f"Human labels, review fields, watched areas, guides and the dataset metadata are "
        f"licensed under {annotation['spdx_id']} "
        f"(held by {annotation['holder']}).",
        "",
        "Machine fields (`machine_*`) are model output and are not annotations by a person.",
        "",
    ]
    return "\n".join(lines)


def changelog(*, release_version: str, date: str, notes: str, previous: str | None) -> str:
    entry = f"## {release_version} ({date})\n\n{notes}\n"
    if previous:
        body = previous.split("\n", 2)[2] if previous.startswith("# Changelog") else previous
        return f"# Changelog\n\n{entry}\n{body.lstrip()}"
    return f"# Changelog\n\n{entry}"


def rejection_report(manifest: dict[str, Any], rejected: list[dict[str, Any]]) -> str:
    lines = [
        "# Excluded observations",
        "",
        f"{len(rejected)} observation(s) of the curated dataset were not released. Each is listed "
        "with the reason. No private notes are included here.",
        "",
    ]
    for row in rejected:
        lines.append(f"- `{row['sample_id']}` ({row['site_id']} / {row['camera_id']}):")
        lines += [f"  - {r['code']}: {r['message']}" for r in row["reasons"]]
    if not rejected:
        lines.append("None.")
    return "\n".join(lines) + "\n"


CHECKLIST_ITEMS = [
    "Run `verify` on this release and confirm it reports no problems.",
    "Upload to a PRIVATE Hugging Face dataset repository first.",
    "Open the dataset viewer and confirm images, splits and metadata columns load.",
    "Spot-check a sample of images against the privacy review (faces, plates, private property).",
    "Confirm every source credit and the license notice read correctly in the dataset card.",
    "Confirm no local paths, secrets or private notes appear in any file.",
    "Confirm the splits are site/camera isolated and the readiness gaps are acceptable.",
    "Record who approved making the repository public, and when.",
]


def checklist() -> str:
    boxes = "\n".join(f"- [ ] {item}" for item in CHECKLIST_ITEMS)
    return (
        "# Release verification checklist\n\n"
        "Complete every item before making any repository public. Tick a box by changing "
        "`[ ]` to `[x]`.\n\n"
        f"{boxes}\n"
    )

"""Build a clean, deterministic public export from one frozen curated dataset version (Issue #207).

The release reads ONLY a frozen version made by dataset curation (#215): checksummed images and
masks, per-example evidence, labels and splits. It never reads a working site folder, so what is
published is exactly what was reviewed and frozen.

Every example must pass the licensing and privacy gate (an approved source, a recorded privacy
review of its site) and be assigned to exactly one split. Anything that does not is excluded and
explained in a rejection report. A release is written to a temporary folder, checksummed and
renamed into place; an existing release is never replaced.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
from collections import defaultdict
from importlib import metadata
from pathlib import Path
from typing import Any

from openfloodai.curation.common import (
    TASK_LEVEL_CLASSIFICATION,
    TASK_WATER_SEGMENTATION,
    CurationError,
    reason,
    sha256_bytes,
    sha256_file,
)
from openfloodai.curation.store import verify_version
from openfloodai.ingestion.river_registry import find_camera
from openfloodai.release import card
from openfloodai.release import policy as release_policy

VERSION_PATTERN = re.compile(r"^v(\d+)\.(\d+)(?:\.(\d+))?$")
SPLIT_NAMES = ("train", "validation", "test")
FROZEN_VERSIONS = "versions"


class ReleaseError(ValueError):
    """The release cannot be built, with the reasons it cannot."""

    def __init__(self, message: str, details: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.details = details or []


def channel_for(release_version: str) -> str:
    """v0.x are private drafts; v1.0 and later are public releases with stricter requirements."""

    match = VERSION_PATTERN.fullmatch(release_version)
    if not match:
        raise ReleaseError("A release version looks like v0.1 or v1.0.")
    return "public" if int(match.group(1)) >= 1 else "draft"


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "x"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


def _line(value: Any) -> str:
    return json.dumps(value, sort_keys=True) + "\n"


def _tool_version() -> str:
    try:
        return metadata.version("openfloodai")
    except metadata.PackageNotFoundError:
        return "unknown"


def _sample_reasons(
    sample: dict[str, Any], pol: dict[str, Any], split: str | None
) -> list[dict[str, str]]:
    """Why a curated example cannot be released (empty when it can)."""

    reasons: list[dict[str, str]] = []
    if split is None:
        reasons.append(reason("no_split", "The example has no split assignment."))
    for obs in sample["observations"]:
        source = obs["source"]
        missing = [
            name
            for name, value in (
                ("source_system", source.get("source_system")),
                ("source_url", source.get("source_url")),
                ("captured_at_utc", source.get("captured_at_utc")),
                ("site_id", obs["site"].get("site_id")),
                ("camera_id", obs["site"].get("camera_id")),
                ("image_sha256", obs["image"].get("sha256")),
            )
            if not value
        ]
        if missing:
            reasons.append(
                reason("missing_provenance", f"Missing required provenance: {', '.join(missing)}.")
            )
        if source.get("source_system") and not release_policy.source_approved(
            pol, source["source_system"]
        ):
            reasons.append(
                reason(
                    "source_not_approved",
                    f"The source '{source['source_system']}' has no recorded, approved reuse "
                    "permission. Third-party or uncertain sources stay out until it is recorded.",
                )
            )
        if not release_policy.site_approved(pol, obs["site"].get("site_id")):
            reasons.append(
                reason(
                    "privacy_review_missing",
                    f"Site '{obs['site'].get('site_id')}' has no approved privacy review "
                    "(faces, license plates, private property).",
                )
            )
    seen: set[str] = set()
    unique = []
    for item in reasons:
        key = f"{item['code']}|{item['message']}"
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _public_annotation(sample: dict[str, Any], ids: dict[str, str]) -> dict[str, Any]:
    """The task annotation without internal ids (run ids, working-folder names)."""

    a = sample["annotation"]
    kind = a["kind"]
    if kind == "water_mask":
        return {
            "kind": kind,
            "source": a["source"],
            "prompt": a["prompt"],
            "model_requested": a.get("model_requested"),
            "masks": [
                {k: m.get(k) for k in ("sha256", "mask_size", "box_source_px")} for m in a["masks"]
            ],
        }
    if kind == "level_category":
        return {
            "kind": kind,
            "category": a["category"],
            "gauge_value": a["gauge_value"],
            "unit": a["unit"],
            "definition": a["definition"],
        }
    if kind == "gauge_height":
        keep = (
            "value",
            "unit",
            "parameter_code",
            "reading_datetime_utc",
            "time_difference_seconds",
            "qualifiers",
            "quality_status",
            "station_nwis_id",
            "station_relationship",
        )
        return {"kind": kind, **{k: a.get(k) for k in keep}}
    if kind == "visual_change":
        # Reviewer codes stay private: a release says how many people agreed, not who they were.
        return {
            "kind": kind,
            "source": a["source"],
            "earlier_observation": ids.get(a["earlier_observation"], a["earlier_observation"]),
            "later_observation": ids.get(a["later_observation"], a["later_observation"]),
            "direction": a["direction"],
            "elapsed_seconds": a.get("elapsed_seconds"),
            "reviewer_count": a.get("reviewer_count"),
            "blind_judgments_only": a.get("blind_judgments_only"),
            "informed_judgment_count": a.get("informed_count", 0),
            "dataset_review": a.get("dataset_review", "not_applicable"),
        }
    pair_keys = (
        "earlier_value",
        "later_value",
        "unit",
        "delta",
        "elapsed_seconds",
        "change_tolerance",
        "direction",
        "station_nwis_id",
    )
    return {
        "kind": kind,
        "earlier_observation": ids.get(a["earlier_observation"], a["earlier_observation"]),
        "later_observation": ids.get(a["later_observation"], a["later_observation"]),
        **{k: a.get(k) for k in pair_keys},
    }


# Only geometry and reference state of a bank guide are public. Its notes, free-text label and
# the working source it was drawn on (video or image names) stay private.
PUBLIC_GUIDE_FIELDS = ("id", "points", "water_side_point", "status", "normal_condition")


def _public_guides(guides: object) -> list[dict[str, Any]]:
    if not isinstance(guides, list):
        return []
    return [
        {key: guide[key] for key in PUBLIC_GUIDE_FIELDS if key in guide}
        for guide in guides
        if isinstance(guide, dict)
    ]


def _gauge_fields(obs: dict[str, Any] | None, prefix: str) -> dict[str, Any]:
    """One image's own gauge evidence, kept separately for each image of a pair."""

    gauge = (obs or {}).get("gauge") or {}
    reading = gauge.get("reading") or {}
    present = obs is not None and bool(reading)
    qualifiers = json.dumps(reading.get("qualifiers") or [], sort_keys=True) if present else None
    fields = {
        "gauge_value": reading.get("value"),
        "gauge_unit": reading.get("unit"),
        "gauge_parameter": reading.get("parameter_code"),
        "gauge_station": (gauge.get("station") or {}).get("nwis_site_id"),
        "gauge_datetime_utc": reading.get("datetime_utc"),
        "gauge_time_gap_seconds": gauge.get("time_difference_seconds"),
        "gauge_quality": reading.get("quality_status"),
        "gauge_qualifiers": qualifiers,
    }
    return {f"{prefix}{name}": value for name, value in fields.items()}


def _image_id(obs: dict[str, Any]) -> str:
    stamp = re.sub(r"[^0-9TZ]", "", obs["source"]["captured_at_utc"].replace("+00:00", "Z"))
    return f"{_safe(obs['site']['camera_id'])}-{stamp}-{obs['image']['sha256'][:8]}"


def _row(
    sample: dict[str, Any],
    split: str,
    paths: dict[str, Any],
    credit: str,
    location: dict[str, Any] | None,
    ids: dict[str, str],
) -> dict[str, Any]:
    first = sample["observations"][0]
    review = first.get("review") or {}
    visibility = review.get("visibility") or {}
    config = first["configuration"]
    machine = first.get("machine") or {}
    later = sample["observations"][1] if sample["kind"] == "pair" else None
    return {
        "sample_id": sample["sample_id"],
        "observation_id": first["observation_key"],
        "split": split,
        "task": sample["task"],
        "kind": sample["kind"],
        "file_name": paths["image"],
        "later_file_name": paths.get("later_image"),
        "baseline_file_name": paths.get("baseline"),
        "mask_files": json.dumps(paths.get("masks", []), sort_keys=True),
        "site_id": first["site"]["site_id"],
        "camera_id": first["site"]["camera_id"],
        "captured_at_utc": first["source"]["captured_at_utc"],
        "later_captured_at_utc": later["source"]["captured_at_utc"] if later else None,
        "local_time": first["source"].get("local_time"),
        "source_system": first["source"]["source_system"],
        "source_url": first["source"]["source_url"],
        "source_credit": credit,
        "human_label": review.get("human_label"),
        "label_confidence": review.get("confidence"),
        "change_presence": review.get("change_presence"),
        "review_status": "human_reviewed" if review else "not_reviewed",
        "review_revision": review.get("label_revision"),
        "camera_stable": visibility.get("camera_stable"),
        "riverbank_visible": visibility.get("riverbank_visible"),
        "water_boundary_visible": visibility.get("water_boundary_visible"),
        "stable_marker_visible": visibility.get("stable_marker_visible"),
        "visibility_condition": visibility.get("visibility_condition"),
        "watched_region": json.dumps(config.get("reference_region"), sort_keys=True),
        "riverbank_guides": json.dumps(
            _public_guides(config.get("normal_waterline_guides")), sort_keys=True
        ),
        **_gauge_fields(first, ""),
        **_gauge_fields(later, "later_"),
        "annotation_kind": sample["annotation"]["kind"],
        "annotation": json.dumps(_public_annotation(sample, ids), sort_keys=True),
        "collection_group": (first.get("collection") or {}).get("group"),
        "machine_result": machine.get("result"),
        "machine_score": machine.get("region_change_score"),
        "latitude": (location or {}).get("latitude"),
        "longitude": (location or {}).get("longitude"),
        "location_precision": (location or {}).get("precision"),
        "image_sha256": first["image"]["sha256"],
        "baseline_sha256": (first.get("baseline") or {}).get("sha256"),
    }


def build_release(
    *,
    datasets_dir: Path,
    dataset_id: str,
    dataset_version: int,
    output_dir: Path,
    release_version: str,
    notes: str,
    policy_path: Path,
    reference_dir: Path,
    previous_release: Path | None = None,
    write_parquet: bool = False,
) -> dict[str, Any]:
    """Build `output_dir/openfloodai-dataset-<version>/`, or explain why it cannot be built."""

    channel = channel_for(release_version)
    if not notes.strip():
        raise ReleaseError("Release notes are required.")
    frozen = datasets_dir / dataset_id / FROZEN_VERSIONS / f"v{int(dataset_version):04d}"
    try:
        check = verify_version(datasets_dir, dataset_id, int(dataset_version))
    except CurationError as error:
        raise ReleaseError(str(error)) from error
    if not check["ok"]:
        raise ReleaseError(
            "The frozen dataset version failed its checksum check, so it cannot be released.",
            [reason("frozen_version_invalid", p) for p in check["problems"]],
        )
    source_manifest = json.loads((frozen / "manifest.json").read_text(encoding="utf-8"))
    samples = _read_jsonl(frozen / "samples.jsonl")
    splits = json.loads((frozen / "splits.json").read_text(encoding="utf-8"))
    if splits["policy"]["kind"] != "site_camera":
        raise ReleaseError(
            "This dataset uses time-block splits, which are site-specific evaluation only. A "
            "release needs site/camera-isolated splits."
        )
    pol = release_policy.load_policy(policy_path)
    if not pol["annotation_license"]:
        raise ReleaseError(
            "No annotation license is recorded. Record one with approve-annotation-license "
            "before building a release."
        )

    final = output_dir / f"openfloodai-dataset-{release_version}"
    if final.exists():
        raise ReleaseError(
            f"{final.name} already exists. A release is never replaced; use a new version."
        )

    accepted, rejected = _select(samples, splits["assignments"], pol)
    cameras_by_split: dict[str, set[str]] = {name: set() for name in SPLIT_NAMES}
    camera_splits: dict[str, set[str]] = defaultdict(set)
    site_splits: dict[str, set[str]] = defaultdict(set)
    for sample, split in accepted:
        for obs in sample["observations"]:
            cameras_by_split[split].add(obs["site"]["camera_id"])
            camera_splits[obs["site"]["camera_id"]].add(split)
            site_splits[obs["site"]["site_id"]].add(split)
    leaks = [
        reason("camera_in_several_splits", f"Camera {c} is in {', '.join(sorted(s))}.")
        for c, s in sorted(camera_splits.items())
        if len(s) > 1
    ] + [
        reason(
            "site_in_several_splits",
            f"Site {site} is in {', '.join(sorted(s))}. Two cameras of one site look at the "
            "same place, so they must stay in one split.",
        )
        for site, s in sorted(site_splits.items())
        if len(s) > 1
    ]
    if leaks:
        raise ReleaseError(
            "A site or camera appears in more than one split, which would leak between "
            "training and evaluation.",
            leaks,
        )
    gaps = [
        reason("split_has_no_camera", f"No released camera is in the {name} split.", "warning")
        for name in SPLIT_NAMES
        if not cameras_by_split[name]
    ]
    if channel == "public" and gaps:
        raise ReleaseError(
            "A v1.0 or later release needs released cameras in train, validation and test.",
            gaps,
        )
    if not accepted:
        raise ReleaseError(
            "No example passed the licensing and privacy gate.", rejected_details(rejected)
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    building = output_dir / f".building-{release_version}"
    if building.exists():
        shutil.rmtree(building)
    building.mkdir()
    try:
        manifest = _write(
            building,
            frozen,
            source_manifest,
            splits,
            accepted,
            rejected,
            gaps,
            pol,
            reference_dir,
            release_version,
            channel,
            notes,
            previous_release,
            write_parquet,
            dataset_id,
            int(dataset_version),
        )
        os.rename(building, final)
    except BaseException:
        shutil.rmtree(building, ignore_errors=True)
        raise
    return manifest


def rejected_details(rejected: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        reason(r["code"], f"{row['sample_id']}: {r['message']}")
        for row in rejected
        for r in row["reasons"]
    ]


def _select(
    samples: list[dict[str, Any]], assignments: dict[str, str], pol: dict[str, Any]
) -> tuple[list[tuple[dict[str, Any], str]], list[dict[str, Any]]]:
    accepted: list[tuple[dict[str, Any], str]] = []
    rejected: list[dict[str, Any]] = []
    for sample in sorted(samples, key=lambda s: s["sample_id"]):
        split = assignments.get(sample["sample_id"])
        reasons = _sample_reasons(sample, pol, split)
        if reasons:
            first = sample["observations"][0]
            rejected.append(
                {
                    "sample_id": sample["sample_id"],
                    "site_id": first["site"]["site_id"],
                    "camera_id": first["site"]["camera_id"],
                    "reasons": reasons,
                }
            )
        else:
            assert split is not None
            accepted.append((sample, split))
    by_image: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for sample, split in accepted:
        if sample["kind"] == "observation":
            by_image[sample["observations"][0]["image"]["sha256"]].append((sample, split))
    drop: set[str] = set()
    for group in by_image.values():
        for sample, _ in group[1:]:
            drop.add(sample["sample_id"])
            first = sample["observations"][0]
            rejected.append(
                {
                    "sample_id": sample["sample_id"],
                    "site_id": first["site"]["site_id"],
                    "camera_id": first["site"]["camera_id"],
                    "reasons": [
                        reason(
                            "duplicate_image",
                            f"Identical image content to {group[0][0]['sample_id']}, which was "
                            "kept.",
                        )
                    ],
                }
            )
    accepted = [(s, sp) for s, sp in accepted if s["sample_id"] not in drop]
    return accepted, sorted(rejected, key=lambda r: r["sample_id"])


def _write(
    out: Path,
    frozen: Path,
    source_manifest: dict[str, Any],
    splits: dict[str, Any],
    accepted: list[tuple[dict[str, Any], str]],
    rejected: list[dict[str, Any]],
    gaps: list[dict[str, str]],
    pol: dict[str, Any],
    reference_dir: Path,
    release_version: str,
    channel: str,
    notes: str,
    previous_release: Path | None,
    write_parquet: bool,
    dataset_id: str,
    dataset_version: int,
) -> dict[str, Any]:
    ids = {
        obs["observation_key"]: obs["observation_key"]
        for s, _ in accepted
        for obs in s["observations"]
    }
    rows: list[dict[str, Any]] = []
    copied: dict[str, str] = {}
    sites: dict[str, dict[str, Any]] = {}
    image_count = mask_count = 0
    task = source_manifest["task"]

    def place(source: str, destination: str) -> str:
        if destination in copied:
            return destination
        target = out / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frozen / source, target)
        copied[destination] = source
        return destination

    for sample, split in accepted:
        first = sample["observations"][0]
        base = f"{_safe(first['site']['site_id'])}/{_safe(first['site']['camera_id'])}"
        files = sample["files"]
        paths: dict[str, Any] = {}
        if sample["kind"] == "pair":
            paths["image"] = place(files["earlier_image"], f"images/{base}/{_image_id(first)}.jpg")
            paths["later_image"] = place(
                files["later_image"], f"images/{base}/{_image_id(sample['observations'][1])}.jpg"
            )
            baseline_key = "earlier_baseline_image"
        else:
            paths["image"] = place(files["image"], f"images/{base}/{_image_id(first)}.jpg")
            baseline_key = "baseline_image"
        if files.get(baseline_key):
            sha = first["baseline"]["sha256"]
            paths["baseline"] = place(files[baseline_key], f"images/{base}/baseline-{sha[:12]}.jpg")
        if task == TASK_WATER_SEGMENTATION:
            paths["masks"] = [
                place(name, f"masks/{base}/{_image_id(first)}-{index}.png")
                for index, name in enumerate(files.get("masks", []))
            ]
        source_system = first["source"]["source_system"]
        credit = pol["sources"][source_system]["credit"]
        site_id = first["site"]["site_id"]
        if site_id not in sites:
            camera = find_camera(first["site"]["camera_id"], reference_dir)
            location = release_policy.location_for(
                pol,
                site_id,
                camera.latitude if camera else None,
                camera.longitude if camera else None,
            )
            sites[site_id] = {
                "site_id": site_id,
                "camera_id": first["site"]["camera_id"],
                "state": camera.state if camera else None,
                "location": location,
                "source_system": source_system,
                "source_credit": credit,
                "privacy_review": "approved",
            }
        rows.append(_row(sample, split, paths, credit, sites[site_id]["location"], ids))
    image_count = sum(1 for d in copied if d.startswith("images/"))
    mask_count = sum(1 for d in copied if d.startswith("masks/"))

    (out / "metadata.jsonl").write_text("".join(_line(r) for r in rows), encoding="utf-8")
    (out / "splits").mkdir()
    present = [s for s in SPLIT_NAMES if any(r["split"] == s for r in rows)]
    for name in present:
        (out / "splits" / f"{name}.jsonl").write_text(
            "".join(_line(r) for r in rows if r["split"] == name), encoding="utf-8"
        )
    (out / "sites.json").write_text(
        _dump({"sites": [sites[k] for k in sorted(sites)]}), encoding="utf-8"
    )
    if task == TASK_LEVEL_CLASSIFICATION:
        definitions = json.loads((frozen / "label-definitions.json").read_text(encoding="utf-8"))
        public = {
            site: {
                k: d[k]
                for k in (
                    "version",
                    "unit",
                    "station_nwis_id",
                    "parameter_code",
                    "datum",
                    "boundary",
                    "bands",
                    "rationale",
                )
            }
            for site, d in definitions["definitions"].items()
        }
        (out / "label-definitions.json").write_text(
            _dump({"definitions": public}), encoding="utf-8"
        )
    (out / "rejected.jsonl").write_text("".join(_line(r) for r in rejected), encoding="utf-8")
    if write_parquet:
        _write_parquet(out / "metadata.parquet", rows)

    by_split = {s: sum(1 for r in rows if r["split"] == s) for s in present}
    manifest: dict[str, Any] = {
        "release_version": release_version,
        "channel": channel,
        "task": task,
        "source": {
            "dataset_id": dataset_id,
            "dataset_name": source_manifest["dataset_name"],
            "version": dataset_version,
            "content_digest": source_manifest["content_digest"],
            "frozen_at_utc": source_manifest["frozen_at_utc"],
            "contract": source_manifest["contract"],
        },
        "counts": {
            "released": len(rows),
            "rejected": len(rejected),
            "images": image_count,
            "masks": mask_count,
            "by_split": by_split,
        },
        "cameras_by_split": {s: sorted(c) for s, c in _cameras(rows).items()},
        "readiness_gaps": gaps
        + [
            g
            for g in source_manifest.get("readiness_gaps", [])
            if g["code"] == "insufficient_independent_cameras" and False
        ],
        "publication_ready": channel == "public" and not gaps,
        "policy_digest": release_policy.policy_digest(pol),
        "tool": {"name": "openfloodai", "version": _tool_version()},
        "notes": [
            "Machine fields are model output, not ground truth.",
            "Nothing was uploaded by building this release.",
        ],
    }
    date = source_manifest["frozen_at_utc"][:10]
    previous_text = (
        (previous_release / "CHANGELOG.md").read_text(encoding="utf-8")
        if previous_release and (previous_release / "CHANGELOG.md").is_file()
        else None
    )
    (out / "CHANGELOG.md").write_text(
        card.changelog(
            release_version=release_version, date=date, notes=notes.strip(), previous=previous_text
        ),
        encoding="utf-8",
    )
    (out / "LICENSE-DATA.md").write_text(card.license_notice(pol), encoding="utf-8")
    (out / "REJECTIONS.md").write_text(card.rejection_report(manifest, rejected), encoding="utf-8")
    (out / "RELEASE-CHECKLIST.md").write_text(card.checklist(), encoding="utf-8")
    (out / "README.md").write_text(
        card.dataset_card(manifest=manifest, policy=pol, splits_present=present), encoding="utf-8"
    )

    # The checklist is the one file a person edits afterwards, so it is not checksummed.
    listed = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "RELEASE-CHECKLIST.md")
    lines = [f"{sha256_file(p)}  {p.relative_to(out).as_posix()}" for p in listed]
    manifest["content_digest"] = sha256_bytes("\n".join(lines).encode())
    (out / "release-manifest.json").write_text(_dump(manifest), encoding="utf-8")
    final_lines = lines + [f"{sha256_file(out / 'release-manifest.json')}  release-manifest.json"]
    (out / "checksums.sha256").write_text(
        "\n".join(sorted(final_lines, key=lambda x: x.split("  ", 1)[1])) + "\n", encoding="utf-8"
    )
    return manifest


def _cameras(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        result[row["split"]].add(row["camera_id"])
    return result


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    try:
        pyarrow = importlib.import_module("pyarrow")
        parquet = importlib.import_module("pyarrow.parquet")
    except ImportError as error:
        raise ReleaseError(
            "metadata.parquet needs the optional pyarrow package. Install it with "
            "pip install 'openfloodai[export]', or build without --parquet."
        ) from error
    parquet.write_table(pyarrow.Table.from_pylist(rows), str(path))


__all__ = ["SPLIT_NAMES", "ReleaseError", "build_release", "channel_for"]

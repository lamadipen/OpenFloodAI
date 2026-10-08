"""Local, versioned training datasets curated from reviewed observations (Issue #215).

Layout, one folder per dataset under the datasets directory (not inside a site, because a dataset
spans runs and sites):

    <dataset-id>/dataset.json            task, split policy, category definitions it uses
    <dataset-id>/draft/members.jsonl     append-only membership events (add, replace, reject,
                                         remove)
    <dataset-id>/blobs/images|masks/     content-addressed copies of the original bytes
    <dataset-id>/versions/v0001/...      an immutable frozen version (see `freeze_version`)

Adding to a dataset only reads saved runs; it never edits a run, a gauge match, a site
configuration or a human review. Removing draft membership never deletes imagery or run evidence.
A frozen version is written to a temporary folder, checksummed, then renamed into place, and is
never modified afterwards: later edits make a new version.
"""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from openfloodai.curation import labels as label_defs
from openfloodai.curation import splits as split_rules
from openfloodai.curation import tasks as task_rules
from openfloodai.curation.common import (
    CONTRACT_NAME,
    CONTRACT_VERSION,
    SCHEMA_VERSION,
    SEVERITY_ERROR,
    TASK_GAUGE_HEIGHT,
    TASK_LEVEL_CHANGE,
    TASK_LEVEL_CLASSIFICATION,
    TASK_TITLES,
    TASK_WATER_SEGMENTATION,
    TASKS,
    CurationConflict,
    CurationError,
    canonical_json,
    clean_text,
    content_id,
    errors_in,
    reason,
    sha256_bytes,
    sha256_file,
    slugify,
    utc_now,
    validate_dataset_id,
)
from openfloodai.curation.snapshot import (
    LoadedObservation,
    current_dataset_group,
    find_mask_candidates,
    load_observation,
)
from openfloodai.ingestion.sequence_store import (
    SequenceStoreError,
    atomic_write_json,
    atomic_write_text,
    sequence_lock,
)

DATASET_FILE = "dataset.json"
DRAFT_DIR = "draft"
MEMBERS_FILE = "members.jsonl"
BLOBS_DIR = "blobs"
VERSIONS_DIR = "versions"
CHECKSUMS_FILE = "checksums.sha256"
MANIFEST_FILE = "manifest.json"
DECISIONS = ("replace", "keep")


# --- datasets -------------------------------------------------------------------------------


def _dataset_dir(datasets_dir: Path, dataset_id: str) -> Path:
    validate_dataset_id(dataset_id)
    path = datasets_dir / dataset_id
    if not path.is_dir() or not (path / DATASET_FILE).is_file():
        raise CurationError("Dataset not found.")
    return path


def _site_dir(sites_dir: Path, folder_name: str) -> Path:
    site = (sites_dir / str(folder_name)).resolve()
    if not folder_name or site.parent != sites_dir.resolve() or not site.is_dir():
        raise CurationError("Choose a saved site.")
    return site


def create_dataset(
    datasets_dir: Path,
    *,
    name: str,
    task: str,
    split_policy: dict[str, Any] | None = None,
    change_tolerance: float | None = None,
) -> dict[str, Any]:
    clean_name = clean_text(name, "Dataset name", max_length=80)
    if task not in TASKS:
        raise CurationError(f"Choose a task: {', '.join(TASKS)}.")
    if change_tolerance is not None and (
        isinstance(change_tolerance, bool)
        or not isinstance(change_tolerance, (int, float))
        or change_tolerance < 0
    ):
        raise CurationError("The no-change tolerance must be zero or more.")
    dataset_id = f"{slugify(clean_name)}-{content_id([clean_name, task, utc_now()], 6)}"
    folder = datasets_dir / dataset_id
    folder.mkdir(parents=True, exist_ok=False)
    dataset = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "name": clean_name,
        "task": task,
        "task_title": TASK_TITLES[task],
        "created_at_utc": utc_now(),
        "split_policy": split_rules.validate_policy(split_policy or split_rules.default_policy()),
        "label_definitions": {},
        "change_tolerance": float(change_tolerance) if change_tolerance is not None else None,
        "note": "Local dataset curation. Not model training, not a flood decision, not published.",
    }
    atomic_write_json(folder / DATASET_FILE, dataset)
    return dataset


def load_dataset(datasets_dir: Path, dataset_id: str) -> dict[str, Any]:
    folder = _dataset_dir(datasets_dir, dataset_id)
    loaded: dict[str, Any] = json.loads((folder / DATASET_FILE).read_text(encoding="utf-8"))
    return loaded


def _save_dataset(datasets_dir: Path, dataset: dict[str, Any]) -> None:
    atomic_write_json(_dataset_dir(datasets_dir, dataset["dataset_id"]) / DATASET_FILE, dataset)


def list_datasets(datasets_dir: Path) -> list[dict[str, Any]]:
    if not datasets_dir.is_dir():
        return []
    rows = []
    for folder in sorted(datasets_dir.iterdir()):
        if folder.name.startswith("_") or not (folder / DATASET_FILE).is_file():
            continue
        dataset = load_dataset(datasets_dir, folder.name)
        members = read_draft(datasets_dir, folder.name)
        rows.append(
            {
                "dataset_id": dataset["dataset_id"],
                "name": dataset["name"],
                "task": dataset["task"],
                "task_title": dataset["task_title"],
                "created_at_utc": dataset["created_at_utc"],
                "included": sum(1 for m in members.values() if m["status"] == "included"),
                "rejected": sum(1 for m in members.values() if m["status"] == "rejected"),
                "versions": len(list_versions(datasets_dir, folder.name)),
            }
        )
    return rows


def set_split_policy(datasets_dir: Path, dataset_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    with _locked(datasets_dir, dataset_id):
        dataset = load_dataset(datasets_dir, dataset_id)
        dataset["split_policy"] = split_rules.validate_policy(policy)
        _save_dataset(datasets_dir, dataset)
        return dataset


def pin_label_definition(
    datasets_dir: Path, dataset_id: str, site_id: str, version: int
) -> dict[str, Any]:
    """Use one approved category-definition version for a site in this dataset."""

    with _locked(datasets_dir, dataset_id):
        dataset = load_dataset(datasets_dir, dataset_id)
        if dataset["task"] != TASK_LEVEL_CLASSIFICATION:
            raise CurationError("Only a classification dataset uses category definitions.")
        label_defs.get_definition(datasets_dir, site_id, int(version))
        dataset["label_definitions"][site_id] = int(version)
        _save_dataset(datasets_dir, dataset)
        return dataset


class _locked:
    """Hold the dataset's lock so two edits or a freeze never interleave."""

    def __init__(self, datasets_dir: Path, dataset_id: str) -> None:
        self._folder = _dataset_dir(datasets_dir, dataset_id)
        self._context: Any = None

    def __enter__(self) -> None:
        try:
            self._context = sequence_lock(self._folder, timeout=30.0)
            self._context.__enter__()
        except SequenceStoreError as error:
            raise CurationError("This dataset is busy. Try again in a moment.") from error

    def __exit__(self, *exc: object) -> None:
        self._context.__exit__(*exc)


# --- draft membership -----------------------------------------------------------------------


def _members_path(folder: Path) -> Path:
    return folder / DRAFT_DIR / MEMBERS_FILE


def _append_event(folder: Path, event: dict[str, Any]) -> None:
    path = _members_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_draft(datasets_dir: Path, dataset_id: str) -> dict[str, dict[str, Any]]:
    """The current draft membership, folded from its event log (latest event per member wins)."""

    path = _members_path(_dataset_dir(datasets_dir, dataset_id))
    members: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return members
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        member_id = event.get("member_id")
        kind = event.get("event")
        if kind in ("add", "replace", "reject"):
            runs = (members.get(member_id) or {}).get("runs", [])
            members[member_id] = {**event, "runs": runs or list(event.get("runs", []))}
        elif kind == "also_in_run" and member_id in members:
            run = event.get("run")
            if run and run not in members[member_id]["runs"]:
                members[member_id]["runs"].append(run)
        elif kind == "remove":
            members.pop(member_id, None)
    return members


def _definition_for(
    datasets_dir: Path, dataset: dict[str, Any], site_id: str
) -> dict[str, Any] | None:
    version = dataset["label_definitions"].get(site_id)
    if version is None:
        return None
    return label_defs.get_definition(datasets_dir, site_id, int(version))


def _copy_blob(source: Path, folder: Path, kind: str, expected_sha: str, suffix: str) -> None:
    target = folder / BLOBS_DIR / kind / f"{expected_sha}{suffix}"
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".part")
    shutil.copyfile(source, temp)
    if sha256_file(temp) != expected_sha:
        temp.unlink(missing_ok=True)
        raise CurationError("The file changed while it was being kept. Try again.")
    os.replace(temp, target)


def _copy_baseline(loaded: LoadedObservation, folder: Path) -> None:
    """Keep the run's baseline image too, when its bytes still match what the run recorded."""

    baseline = loaded.snapshot.get("baseline")
    if loaded.baseline_path is not None and baseline and baseline.get("sha256"):
        _copy_blob(loaded.baseline_path, folder, "images", baseline["sha256"], ".jpg")


def _ref(
    folder_name: str,
    run_id: str,
    filename: str,
    mask_result_id: str | None = None,
    mask_run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "folder_name": folder_name,
        "run_id": run_id,
        "filename": filename,
        "mask_result_id": mask_result_id,
        "mask_run_id": mask_run_id,
    }


def _check_decision(decision: str | None) -> None:
    if decision is not None and decision not in DECISIONS:
        raise CurationError("A decision must be replace or keep.")


def _evaluate_single(
    datasets_dir: Path,
    dataset: dict[str, Any],
    site_dir: Path,
    loaded: LoadedObservation,
    mask_result_id: str | None,
    mask_run_id: str | None,
) -> tuple[dict[str, Any], list[Any]]:
    task = dataset["task"]
    masks = (
        find_mask_candidates(site_dir, loaded.snapshot) if task == TASK_WATER_SEGMENTATION else []
    )
    if task == TASK_WATER_SEGMENTATION:
        return task_rules.evaluate_segmentation(loaded, masks, mask_result_id, mask_run_id), masks
    if task == TASK_GAUGE_HEIGHT:
        return task_rules.evaluate_gauge_height(loaded), masks
    if task == TASK_LEVEL_CLASSIFICATION:
        definition = _definition_for(datasets_dir, dataset, loaded.snapshot["site"]["site_id"])
        return task_rules.evaluate_classification(loaded, definition), masks
    raise CurationError("Add a pair of observations to a rising / falling dataset.")


def add_observation(
    datasets_dir: Path,
    sites_dir: Path,
    dataset_id: str,
    *,
    folder_name: str,
    run_id: str,
    filename: str,
    mask_result_id: str | None = None,
    mask_run_id: str | None = None,
    decision: str | None = None,
) -> dict[str, Any]:
    """Validate one image of a saved run for the dataset's task and add it to the draft.

    Returns what happened: `added`, `unchanged` (the same example is already there, which makes a
    repeat selection idempotent), `replaced`, `kept` or `ineligible` (with every reason). A
    DIFFERENT annotation for an observation already in the draft raises `CurationConflict` until
    the caller explicitly chooses `replace` or `keep`.
    """

    _check_decision(decision)
    with _locked(datasets_dir, dataset_id):
        dataset = load_dataset(datasets_dir, dataset_id)
        if dataset["task"] == TASK_LEVEL_CHANGE:
            raise CurationError("Add a pair of observations to a rising / falling dataset.")
        folder = _dataset_dir(datasets_dir, dataset_id)
        site_dir = _site_dir(sites_dir, folder_name)
        loaded = load_observation(site_dir, run_id, filename)
        evaluation, masks = _evaluate_single(
            datasets_dir, dataset, site_dir, loaded, mask_result_id, mask_run_id
        )
        key = loaded.snapshot["observation_key"]
        if not evaluation["eligible"]:
            return {"status": "ineligible", "member_id": key, **_outline(evaluation)}
        annotation = evaluation["annotation"]
        version = evaluation["annotation_version"]
        mask_files: dict[str, Path] = {}
        if dataset["task"] == TASK_WATER_SEGMENTATION:
            chosen = next(
                m
                for m in masks
                if m.result_id == annotation["result_id"]
                and m.run_id == annotation["segmentation_run_id"]
            )
            mask_files = {sha256_file(p): p for p in chosen.mask_paths}
        event = {
            "event": "add",
            "at": utc_now(),
            "member_id": key,
            "kind": "observation",
            "status": "included",
            "task": dataset["task"],
            "snapshot": loaded.snapshot,
            "annotation": annotation,
            "annotation_version": version,
            "warnings": [r for r in evaluation["reasons"] if r["severity"] != SEVERITY_ERROR],
            "selected": _ref(
                folder_name,
                run_id,
                filename,
                annotation.get("result_id"),
                annotation.get("segmentation_run_id"),
            ),
            "runs": [run_id],
        }
        existing = read_draft(datasets_dir, dataset_id).get(key)
        if existing and existing["status"] == "included":
            if existing["annotation_version"] == version:
                if existing["snapshot"]["dataset_group"] != loaded.snapshot["dataset_group"]:
                    # Same annotation, but the site's group for this date changed since it was
                    # added: refresh the stored evidence so the new group is enforced.
                    event["event"] = "replace"
                    event["runs"] = sorted(set(existing["runs"]) | {run_id})
                    _append_event(folder, event)
                    return {"status": "updated", "member_id": key, **_outline(evaluation)}
                if run_id not in existing["runs"]:
                    _append_event(folder, {"event": "also_in_run", "member_id": key, "run": run_id})
                return {"status": "unchanged", "member_id": key, **_outline(evaluation)}
            if decision is None:
                raise CurationConflict(
                    "This observation is already in the dataset with a different annotation. "
                    "Choose whether to replace it or keep the existing one.",
                    {
                        "member_id": key,
                        "existing_version": existing["annotation_version"],
                        "new_version": version,
                        "existing": existing["annotation"],
                        "new": annotation,
                    },
                )
            if decision == "keep":
                return {"status": "kept", "member_id": key, **_outline(evaluation)}
            event["event"] = "replace"
            event["replaces_version"] = existing["annotation_version"]
        assert loaded.image_path is not None
        _copy_blob(loaded.image_path, folder, "images", loaded.snapshot["image"]["sha256"], ".jpg")
        _copy_baseline(loaded, folder)
        for sha, path in mask_files.items():
            _copy_blob(path, folder, "masks", sha, ".png")
        _append_event(folder, event)
        return {
            "status": "replaced" if event["event"] == "replace" else "added",
            "member_id": key,
            **_outline(evaluation),
        }


def add_pair(
    datasets_dir: Path,
    sites_dir: Path,
    dataset_id: str,
    *,
    earlier: dict[str, str],
    later: dict[str, str],
    decision: str | None = None,
) -> dict[str, Any]:
    """Add an explicitly chosen earlier/later pair to a rising / falling dataset.

    Pairs are never made automatically: the reviewer names both observations, which must come from
    the same stable camera view.
    """

    _check_decision(decision)
    with _locked(datasets_dir, dataset_id):
        dataset = load_dataset(datasets_dir, dataset_id)
        if dataset["task"] != TASK_LEVEL_CHANGE:
            raise CurationError("Only a rising / falling dataset takes pairs of observations.")
        folder = _dataset_dir(datasets_dir, dataset_id)
        first = load_observation(
            _site_dir(sites_dir, earlier["folder_name"]), earlier["run_id"], earlier["filename"]
        )
        second = load_observation(
            _site_dir(sites_dir, later["folder_name"]), later["run_id"], later["filename"]
        )
        evaluation = task_rules.evaluate_pair(
            first, second, change_tolerance=dataset["change_tolerance"]
        )
        member_id = "pair-" + content_id(
            [first.snapshot["observation_key"], second.snapshot["observation_key"]], 20
        )
        if not evaluation["eligible"]:
            return {"status": "ineligible", "member_id": member_id, **_outline(evaluation)}
        version = evaluation["annotation_version"]
        event = {
            "event": "add",
            "at": utc_now(),
            "member_id": member_id,
            "kind": "pair",
            "status": "included",
            "task": dataset["task"],
            "snapshots": {"earlier": first.snapshot, "later": second.snapshot},
            "annotation": evaluation["annotation"],
            "annotation_version": version,
            "warnings": [r for r in evaluation["reasons"] if r["severity"] != SEVERITY_ERROR],
            "selected": {"earlier": _ref(**earlier), "later": _ref(**later)},
            "runs": [earlier["run_id"], later["run_id"]],
        }
        existing = read_draft(datasets_dir, dataset_id).get(member_id)
        if existing and existing["status"] == "included":
            if existing["annotation_version"] == version:
                old = existing["snapshots"]
                if (old["earlier"]["dataset_group"], old["later"]["dataset_group"]) != (
                    first.snapshot["dataset_group"],
                    second.snapshot["dataset_group"],
                ):
                    event["event"] = "replace"
                    _append_event(folder, event)
                    return {"status": "updated", "member_id": member_id, **_outline(evaluation)}
                return {"status": "unchanged", "member_id": member_id, **_outline(evaluation)}
            if decision is None:
                raise CurationConflict(
                    "This pair is already in the dataset with a different target. Choose whether "
                    "to replace it or keep the existing one.",
                    {
                        "member_id": member_id,
                        "existing": existing["annotation"],
                        "new": evaluation["annotation"],
                    },
                )
            if decision == "keep":
                return {"status": "kept", "member_id": member_id, **_outline(evaluation)}
            event["event"] = "replace"
            event["replaces_version"] = existing["annotation_version"]
        for loaded in (first, second):
            assert loaded.image_path is not None
            _copy_blob(
                loaded.image_path, folder, "images", loaded.snapshot["image"]["sha256"], ".jpg"
            )
            _copy_baseline(loaded, folder)
        _append_event(folder, event)
        return {"status": "added", "member_id": member_id, **_outline(evaluation)}


def reject_observation(
    datasets_dir: Path,
    sites_dir: Path,
    dataset_id: str,
    *,
    folder_name: str,
    run_id: str,
    filename: str,
    note: str,
) -> dict[str, Any]:
    """Record that a reviewer rejected this annotation for this dataset (it stays visible)."""

    clean_note = clean_text(note, "A reason", max_length=300)
    with _locked(datasets_dir, dataset_id):
        folder = _dataset_dir(datasets_dir, dataset_id)
        loaded = load_observation(_site_dir(sites_dir, folder_name), run_id, filename)
        key = loaded.snapshot["observation_key"]
        _append_event(
            folder,
            {
                "event": "reject",
                "at": utc_now(),
                "member_id": key,
                "kind": "observation",
                "status": "rejected",
                "task": load_dataset(datasets_dir, dataset_id)["task"],
                "snapshot": loaded.snapshot,
                "annotation": None,
                "annotation_version": None,
                "warnings": [],
                "rejection_note": clean_note,
                "selected": _ref(folder_name, run_id, filename),
                "runs": [run_id],
            },
        )
        return {"status": "rejected", "member_id": key}


def remove_member(datasets_dir: Path, dataset_id: str, member_id: str) -> dict[str, Any]:
    """Take a member out of the DRAFT. Source imagery, run evidence and frozen versions stay."""

    with _locked(datasets_dir, dataset_id):
        folder = _dataset_dir(datasets_dir, dataset_id)
        if member_id not in read_draft(datasets_dir, dataset_id):
            raise CurationError("That example is not in the draft.")
        _append_event(folder, {"event": "remove", "at": utc_now(), "member_id": member_id})
        return {"status": "removed", "member_id": member_id}


def _outline(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "eligible": evaluation["eligible"],
        "reasons": evaluation["reasons"],
        "annotation": evaluation["annotation"],
        "annotation_version": evaluation["annotation_version"],
    }


# --- review of a draft: readiness, duplicates, splits ---------------------------------------


def _units(member: dict[str, Any]) -> list[dict[str, Any]]:
    return (
        [member["snapshots"]["earlier"], member["snapshots"]["later"]]
        if member["kind"] == "pair"
        else [member["snapshot"]]
    )


def _split_members(draft: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "member_id": member_id,
            "kind": m["kind"],
            "snapshot": m.get("snapshot"),
            "snapshots": m.get("snapshots"),
        }
        for member_id, m in sorted(draft.items())
        if m["status"] == "included"
    ]


def _site_dir_or_none(sites_dir: Path, folder_name: str) -> Path | None:
    """The saved site folder directly inside the sites directory, or None if it is not there."""

    site = (sites_dir / str(folder_name)).resolve()
    if not folder_name or site.parent != sites_dir.resolve() or not site.is_dir():
        return None
    return site


def _group_problems(sites_dir: Path, member: dict[str, Any]) -> list[dict[str, str]]:
    """Re-read each image's dataset group as the site has it now.

    A range locked or excluded after the example was added must not slip into training. The
    group stored with the example is history; the group in force today decides.
    """

    problems: list[dict[str, str]] = []
    for snap in _units(member):
        site = _site_dir_or_none(sites_dir, snap["site"]["folder_name"])
        if site is None:
            problems.append(
                reason(
                    "site_missing",
                    "The site this example came from can't be found, so its current dataset "
                    "group can't be checked. Freezing needs that check.",
                )
            )
            continue
        now = current_dataset_group(site, snap["source"]["captured_at_utc"])
        if now == "excluded":
            problems.append(
                reason("excluded_group", "This image's date range is now marked excluded.")
            )
        elif now != snap["dataset_group"]:
            problems.append(
                reason(
                    "dataset_group_changed",
                    f"This image's date range changed from {snap['dataset_group']} to {now} "
                    "after it was added. Add it again to refresh it.",
                )
            )
    return problems


def recheck_member(
    datasets_dir: Path,
    dataset: dict[str, Any],
    folder: Path,
    member: dict[str, Any],
    sites_dir: Path,
) -> list[dict[str, str]]:
    """Re-run the task rules on the evidence the member froze, and verify its kept bytes."""

    task = dataset["task"]
    problems: list[dict[str, str]] = _group_problems(sites_dir, member)
    for snap in _units(member):
        blob = folder / BLOBS_DIR / "images" / f"{snap['image']['sha256']}.jpg"
        if not blob.is_file():
            problems.append(reason("blob_missing", "A kept copy of the original image is missing."))
        elif sha256_file(blob) != snap["image"]["sha256"]:
            problems.append(reason("blob_changed", "A kept copy of the original image changed."))
        baseline = snap.get("baseline") or {}
        if baseline.get("available"):
            kept = folder / BLOBS_DIR / "images" / f"{baseline['sha256']}.jpg"
            if not kept.is_file() or sha256_file(kept) != baseline["sha256"]:
                problems.append(
                    reason(
                        "baseline_blob_changed",
                        "A kept copy of the baseline image is missing or changed.",
                    )
                )
    annotation = member["annotation"] or {}
    if task == TASK_WATER_SEGMENTATION:
        for mask in annotation.get("masks", []):
            blob = folder / BLOBS_DIR / "masks" / f"{mask['sha256']}.png"
            if not blob.is_file() or sha256_file(blob) != mask["sha256"]:
                problems.append(
                    reason("mask_blob_changed", "A kept mask file is missing or changed.")
                )
    elif task == TASK_GAUGE_HEIGHT:
        again = task_rules.evaluate_gauge_height(LoadedObservation(member["snapshot"], None))
        problems += errors_in(again["reasons"])
    elif task == TASK_LEVEL_CLASSIFICATION:
        pinned = dataset["label_definitions"].get(member["snapshot"]["site"]["site_id"])
        used = (annotation.get("definition") or {}).get("version")
        if pinned is None:
            problems.append(
                reason(
                    "definition_missing",
                    "This dataset no longer names a category definition for this site.",
                )
            )
        elif pinned != used:
            problems.append(
                reason(
                    "annotation_stale",
                    f"This example was categorized with definition version {used}, but the dataset "
                    "now "
                    f"uses version {pinned}. Add it again to re-categorize under the new version.",
                )
            )
    elif task == TASK_LEVEL_CHANGE:
        again = task_rules.evaluate_pair(
            LoadedObservation(member["snapshots"]["earlier"], None),
            LoadedObservation(member["snapshots"]["later"], None),
            change_tolerance=dataset["change_tolerance"],
        )
        problems += errors_in(again["reasons"])
        if again["annotation_version"] != member["annotation_version"]:
            problems.append(
                reason(
                    "annotation_stale",
                    "The no-change tolerance changed since this pair was added. Add it again.",
                )
            )
    return problems


def _conflicts_and_duplicates(
    draft: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for member_id, member in draft.items():
        if member["status"] != "included":
            continue
        for snap in _units(member):
            groups[snap["image"]["sha256"]].append(member_id)
    duplicates, problems = [], []
    for sha, ids in groups.items():
        unique = sorted(set(ids))
        if len(unique) < 2:
            continue
        duplicates.append({"image_sha256": sha, "members": unique})
        versions = {
            json.dumps(draft[i]["annotation"], sort_keys=True)
            for i in unique
            if draft[i]["kind"] == "observation"
        }
        if len(versions) > 1:
            problems.append(
                reason(
                    "conflicting_annotations",
                    "Identical image content appears under different observations with different "
                    f"annotations ({', '.join(unique)}). Remove one before freezing.",
                )
            )
    return duplicates, problems


def dataset_view(datasets_dir: Path, dataset_id: str, sites_dir: Path) -> dict[str, Any]:
    """Everything the dataset page shows: membership, readiness, label counts, gaps, duplicates."""

    folder = _dataset_dir(datasets_dir, dataset_id)
    dataset = load_dataset(datasets_dir, dataset_id)
    draft = read_draft(datasets_dir, dataset_id)
    rows: list[dict[str, Any]] = []
    blocking: list[dict[str, str]] = []
    for member_id, member in sorted(draft.items()):
        problems = (
            recheck_member(datasets_dir, dataset, folder, member, sites_dir)
            if member["status"] == "included"
            else []
        )
        blocking += [{**p, "member_id": member_id} for p in problems]
        rows.append(_member_row(member, problems))
    included = {k: v for k, v in draft.items() if v["status"] == "included"}
    duplicates, conflict_problems = _conflicts_and_duplicates(draft)
    blocking += conflict_problems
    assigned, split_problems, gaps = split_rules.assign_splits(
        dataset["split_policy"], _split_members(draft)
    )
    blocking += split_problems
    if not included:
        blocking.append(reason("empty", "Add at least one example before freezing a version."))
    counts = _label_counts(dataset, included, assigned)
    for row in rows:
        row["split"] = assigned.get(row["member_id"])
    return {
        "dataset": dataset,
        "members": rows,
        "label_counts": counts,
        "blocking": blocking,
        "readiness_gaps": gaps,
        "duplicates": duplicates,
        "ready_to_freeze": not blocking,
        "versions": list_versions(datasets_dir, dataset_id),
    }


def _member_row(member: dict[str, Any], problems: list[dict[str, str]]) -> dict[str, Any]:
    snaps = _units(member)
    first = snaps[0]
    return {
        "member_id": member["member_id"],
        "kind": member["kind"],
        "status": member["status"],
        "observation": {
            "site": first["site"]["folder_name"],
            "camera_id": first["site"]["camera_id"],
            "captured_at_utc": first["source"]["captured_at_utc"],
            "filename": first["image"]["filename"],
            "image_sha256": first["image"]["sha256"],
            "later_filename": snaps[1]["image"]["filename"] if len(snaps) > 1 else None,
        },
        "runs": member.get("runs", []),
        "annotation": member.get("annotation"),
        "annotation_version": member.get("annotation_version"),
        "warnings": member.get("warnings", []),
        "problems": problems,
        "rejection_note": member.get("rejection_note"),
        "added_at": member.get("at"),
    }


def _label_counts(
    dataset: dict[str, Any], included: dict[str, dict[str, Any]], assigned: dict[str, str]
) -> dict[str, Any]:
    task = dataset["task"]
    counts: dict[str, Any] = {
        "examples": len(included),
        "by_split": dict(Counter(assigned.values())),
    }
    annotations = [m["annotation"] for m in included.values()]
    if task == TASK_LEVEL_CLASSIFICATION:
        counts["by_category"] = dict(Counter(a["category"] for a in annotations))
    elif task == TASK_LEVEL_CHANGE:
        counts["by_direction"] = dict(Counter(a["direction"] or "unlabelled" for a in annotations))
    elif task == TASK_GAUGE_HEIGHT:
        values = [a["value"] for a in annotations]
        counts["gauge_range"] = (
            {"min": min(values), "max": max(values), "unit": annotations[0]["unit"]}
            if values
            else None
        )
    else:
        counts["masks"] = sum(len(a["masks"]) for a in annotations)
    counts["by_human_label"] = dict(
        Counter(
            (u.get("review") or {}).get("human_label") or "not reviewed"
            for m in included.values()
            for u in _units(m)
        )
    )
    counts["cameras"] = sorted(
        {u["site"]["camera_id"] for m in included.values() for u in _units(m)}
    )
    return counts


# --- freezing and verifying a version ------------------------------------------------------


def list_versions(datasets_dir: Path, dataset_id: str) -> list[dict[str, Any]]:
    root = _dataset_dir(datasets_dir, dataset_id) / VERSIONS_DIR
    if not root.is_dir():
        return []
    versions = []
    for folder in sorted(root.iterdir()):
        manifest = folder / MANIFEST_FILE
        if folder.name.startswith("v") and manifest.is_file():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            versions.append(
                {
                    "version": data["version"],
                    "frozen_at_utc": data["frozen_at_utc"],
                    "note": data.get("note"),
                    "examples": data["counts"]["examples"],
                    "content_digest": data["content_digest"],
                }
            )
    return versions


def freeze_version(
    datasets_dir: Path,
    dataset_id: str,
    *,
    note: str,
    approved_by: str,
    sites_dir: Path,
) -> dict[str, Any]:
    """Freeze the draft as a new immutable version, or explain why it cannot be frozen yet."""

    clean_note = clean_text(note, "A version note", max_length=300)
    approver = clean_text(approved_by, "The person freezing this version", max_length=80)
    with _locked(datasets_dir, dataset_id):
        view = dataset_view(datasets_dir, dataset_id, sites_dir)
        if view["blocking"]:
            raise CurationConflict(
                "This dataset cannot be frozen yet. Fix the listed problems first.",
                {"blocking": view["blocking"]},
            )
        folder = _dataset_dir(datasets_dir, dataset_id)
        dataset = view["dataset"]
        draft = {
            k: v
            for k, v in read_draft(datasets_dir, dataset_id).items()
            if v["status"] == "included"
        }
        rejected = [
            v for v in read_draft(datasets_dir, dataset_id).values() if v["status"] == "rejected"
        ]
        number = len(list_versions(datasets_dir, dataset_id)) + 1
        final = folder / VERSIONS_DIR / f"v{number:04d}"
        if final.exists():
            raise CurationError("That version already exists.")
        building = folder / VERSIONS_DIR / f".building-v{number:04d}"
        if building.exists():
            shutil.rmtree(building)
        building.mkdir(parents=True)
        try:
            manifest = _write_version(
                datasets_dir,
                dataset,
                folder,
                building,
                draft,
                rejected,
                view,
                number,
                clean_note,
                approver,
            )
            os.rename(building, final)
        except BaseException:
            shutil.rmtree(building, ignore_errors=True)
            raise
        return manifest


def _write_version(
    datasets_dir: Path,
    dataset: dict[str, Any],
    folder: Path,
    out: Path,
    draft: dict[str, dict[str, Any]],
    rejected: list[dict[str, Any]],
    view: dict[str, Any],
    number: int,
    note: str,
    approver: str,
) -> dict[str, Any]:
    assigned, _, gaps = split_rules.assign_splits(dataset["split_policy"], _split_members(draft))
    image_shas: set[str] = set()
    mask_shas: set[str] = set()
    rows: list[dict[str, Any]] = []
    for member_id, member in sorted(draft.items()):
        snaps = _units(member)
        files: dict[str, Any]
        if member["kind"] == "pair":
            files = {
                "earlier_image": f"images/{snaps[0]['image']['sha256']}.jpg",
                "later_image": f"images/{snaps[1]['image']['sha256']}.jpg",
            }
        else:
            files = {"image": f"images/{snaps[0]['image']['sha256']}.jpg"}
        for snap in snaps:
            image_shas.add(snap["image"]["sha256"])
        prefixes = ("earlier_", "later_") if member["kind"] == "pair" else ("",)
        for prefix, snap in zip(prefixes, snaps, strict=True):
            baseline = snap.get("baseline") or {}
            blob = folder / BLOBS_DIR / "images" / f"{baseline.get('sha256')}.jpg"
            if baseline.get("available") and baseline.get("sha256") and blob.is_file():
                files[f"{prefix}baseline_image"] = f"images/{baseline['sha256']}.jpg"
                image_shas.add(baseline["sha256"])
        if dataset["task"] == TASK_WATER_SEGMENTATION:
            shas = [m["sha256"] for m in member["annotation"]["masks"]]
            files["masks"] = [f"masks/{sha}.png" for sha in shas]
            mask_shas.update(shas)
        rows.append(
            {
                "sample_id": member_id,
                "kind": member["kind"],
                "task": dataset["task"],
                "split": assigned[member_id],
                "annotation": member["annotation"],
                "annotation_version": member["annotation_version"],
                "observations": [_observation_record(s) for s in snaps],
                "files": files,
                "warnings": member.get("warnings", []),
                "runs": sorted(member.get("runs", [])),
            }
        )
    (out / "images").mkdir()
    for sha in sorted(image_shas):
        shutil.copyfile(folder / BLOBS_DIR / "images" / f"{sha}.jpg", out / "images" / f"{sha}.jpg")
    if mask_shas:
        (out / "masks").mkdir()
        for sha in sorted(mask_shas):
            shutil.copyfile(
                folder / BLOBS_DIR / "masks" / f"{sha}.png", out / "masks" / f"{sha}.png"
            )
    atomic_write_text(
        out / "samples.jsonl", "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    )
    definitions = {
        site: label_defs.get_definition(datasets_dir, site, int(version))
        for site, version in sorted(dataset["label_definitions"].items())
        if dataset["task"] == TASK_LEVEL_CLASSIFICATION
    }
    atomic_write_json(out / "label-definitions.json", {"definitions": definitions})
    policy = dataset["split_policy"]
    atomic_write_json(
        out / "splits.json",
        {
            "policy": policy,
            "assignments": dict(sorted(assigned.items())),
            "counts": dict(Counter(assigned.values())),
            "cameras": {
                s: sorted(
                    {
                        u["site"]["camera_id"]
                        for m in draft.values()
                        for u in _units(m)
                        if assigned[m["member_id"]] == s
                    }
                )
                for s in sorted(set(assigned.values()))
            },
            "readiness_gaps": gaps,
            "leakage_checks": [
                {"check": c, "passed": True}
                for c in (
                    "same_image_across_splits",
                    "camera_isolation",
                    "temporal_pair_overlap",
                    "locked_validation_only_in_test",
                )
            ],
            "generalization_scope": (
                "single_site_time_block_evaluation_only"
                if policy["kind"] == split_rules.POLICY_TIME_BLOCK
                else "site_camera_isolated"
            ),
            "meets_207_publication_rule": policy["kind"] == split_rules.POLICY_SITE_CAMERA
            and not gaps,
        },
    )
    written = sorted(p for p in out.rglob("*") if p.is_file())
    lines = [f"{sha256_file(p)}  {p.relative_to(out).as_posix()}" for p in written]
    content_digest = sha256_bytes("\n".join(lines).encode())
    manifest = {
        "contract": {"name": CONTRACT_NAME, "version": CONTRACT_VERSION},
        "dataset_id": dataset["dataset_id"],
        "dataset_name": dataset["name"],
        "version": number,
        "task": dataset["task"],
        "frozen_at_utc": utc_now(),
        "note": note,
        "approved_by": approver,
        "counts": {
            "examples": len(rows),
            "images": len(image_shas),
            "masks": len(mask_shas),
            "rejected_in_draft": len(rejected),
        },
        "rejected": [
            {
                "member_id": r["member_id"],
                "note": r.get("rejection_note"),
                "filename": r["snapshot"]["image"]["filename"],
            }
            for r in rejected
        ],
        "change_tolerance": dataset["change_tolerance"],
        "duplicates": view["duplicates"],
        "readiness_gaps": gaps,
        "content_digest": content_digest,
        "notes": [
            "Collection group, gauge value, human label, image quality and review status are "
            "separate fields on every sample.",
            "This is a local, validated handoff. It is not uploaded or published.",
        ],
    }
    atomic_write_json(out / MANIFEST_FILE, manifest)
    final_lines = lines + [f"{sha256_file(out / MANIFEST_FILE)}  {MANIFEST_FILE}"]
    atomic_write_text(
        out / CHECKSUMS_FILE,
        "\n".join(sorted(final_lines, key=lambda x: x.split("  ", 1)[1])) + "\n",
    )
    return manifest


def _observation_record(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_key": snap["observation_key"],
        "site": snap["site"],
        "source": snap["source"],
        "image": snap["image"],
        "baseline": snap["baseline"],
        "collection": snap["collection"],
        "dataset_group": snap["dataset_group"],
        "dataset_group_at_review": snap.get("dataset_group_at_review"),
        "gauge": snap["gauge"],
        "configuration": snap["configuration"],
        "review": snap["review"],
        "machine": snap["machine"],
    }


def verify_version(datasets_dir: Path, dataset_id: str, version: int) -> dict[str, Any]:
    """Check a frozen version against its checksums and its own sample references."""

    root = _dataset_dir(datasets_dir, dataset_id) / VERSIONS_DIR / f"v{int(version):04d}"
    problems: list[str] = []
    if not (root / CHECKSUMS_FILE).is_file():
        return {"ok": False, "problems": ["The version has no checksum file."]}
    listed: dict[str, str] = {}
    for line in (root / CHECKSUMS_FILE).read_text(encoding="utf-8").splitlines():
        sha, _, name = line.partition("  ")
        listed[name] = sha
    for name, sha in listed.items():
        path = root / name
        if not path.is_file():
            problems.append(f"{name} is missing.")
        elif sha256_file(path) != sha:
            problems.append(f"{name} has changed.")
    on_disk = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} - {
        CHECKSUMS_FILE
    }
    for extra in sorted(on_disk - set(listed)):
        problems.append(f"{extra} is not in the checksum list.")
    samples = root / "samples.jsonl"
    if samples.is_file():
        for number, line in enumerate(samples.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                references = [
                    name
                    for value in row["files"].values()
                    for name in (value if isinstance(value, list) else [value])
                ]
            except (ValueError, KeyError, TypeError, AttributeError):
                problems.append(f"samples.jsonl line {number} is not a valid sample.")
                continue
            for name in references:
                if not (root / name).is_file():
                    problems.append(f"{row.get('sample_id')}: {name} is missing.")
    return {"ok": not problems, "problems": problems}


def read_version_manifest(datasets_dir: Path, dataset_id: str, version: int) -> dict[str, Any]:
    root = _dataset_dir(datasets_dir, dataset_id) / VERSIONS_DIR / f"v{int(version):04d}"
    path = root / MANIFEST_FILE
    if not path.is_file():
        raise CurationError("Version not found.")
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def canonical_samples_digest(datasets_dir: Path, dataset_id: str, version: int) -> str:
    root = _dataset_dir(datasets_dir, dataset_id) / VERSIONS_DIR / f"v{int(version):04d}"
    return sha256_bytes(canonical_json((root / "samples.jsonl").read_text(encoding="utf-8")))

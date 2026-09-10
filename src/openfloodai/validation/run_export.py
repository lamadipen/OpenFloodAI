"""Build portable, shareable copies of local validation results.

Two kinds of export are supported:

- ``build_run_export`` copies one saved run's own folder, unchanged in
  layout, so it can be dropped straight into another machine's
  ``<site>/outputs/runs/`` and be picked up by that machine's own run
  history scan with no separate import step.
- ``build_export_all`` copies every site's config, labels, manifest, and
  runs into one bundle, so a teammate who does not have the site set up
  locally at all can copy the whole thing into their own sites directory
  and start reviewing.

Both read only a run's own saved outputs and its ``inputs-used`` snapshot
(see :mod:`openfloodai.validation.input_snapshot`) for anything
run-specific; neither silently substitutes today's live site state for a
past run. Raw video is excluded unless the caller explicitly opts in.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from openfloodai.validation.input_snapshot import read_input_snapshot

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

RUN_METADATA_PATH_FIELDS = (
    "report_path",
    "scorecard_path",
    "records_path",
    "review_images_path",
    "inputs_used_path",
)


@dataclass(frozen=True)
class RunExportResult:
    """Result of building one portable run export."""

    site_dir: Path
    run_dir: Path
    export_dir: Path
    created: bool
    message: str
    included_raw_video: bool
    excluded_video_filenames: list[str]


@dataclass(frozen=True)
class SiteExportAllResult:
    """Result of building a multi-site export bundle."""

    sites_dir: Path
    export_dir: Path
    created: bool
    message: str
    exported_site_names: list[str]
    included_raw_video: bool


def build_run_export(
    site_dir: Path,
    run_id: str,
    destination_dir: Path,
    *,
    include_raw_video: bool = False,
) -> RunExportResult:
    """Build a portable copy of one saved run at ``destination_dir/<run_id>``.

    The copy keeps the run's own filenames and layout (``validation-report.md``,
    ``scorecard.json``, ``records/``, ``review-images/``, ``inputs-used/``,
    ``run-metadata.json``) so it can be copied straight into another site's
    ``outputs/runs/`` folder and be recognized there without translation.
    """

    empty = RunExportResult(
        site_dir=site_dir,
        run_dir=Path(),
        export_dir=Path(),
        created=False,
        message="",
        included_raw_video=False,
        excluded_video_filenames=[],
    )

    if not site_dir.exists() or not site_dir.is_dir():
        return replace(empty, message=f"Site folder does not exist: {site_dir}")

    if not run_id or _RUN_ID_PATTERN.fullmatch(run_id) is None:
        return replace(
            empty,
            message="Invalid run_id: use only letters, numbers, dash, and underscore.",
        )

    runs_dir = site_dir / "outputs" / "runs"
    run_dir = (runs_dir / run_id).resolve()
    try:
        run_dir.relative_to(runs_dir.resolve())
    except ValueError:
        return replace(empty, message="Invalid run_id: run folder must stay inside outputs/runs.")

    if not run_dir.is_dir():
        return replace(empty, run_dir=run_dir, message=f"Run folder does not exist: {run_dir}")

    report_path = run_dir / "validation-report.md"
    scorecard_path = run_dir / "scorecard.json"
    metadata_path = run_dir / "run-metadata.json"
    for required_path in (report_path, scorecard_path, metadata_path):
        if not required_path.is_file():
            return replace(
                empty,
                run_dir=run_dir,
                message=f"Run is missing an expected file and cannot be exported: {required_path}",
            )

    try:
        snapshot = read_input_snapshot(run_dir)
    except FileNotFoundError as error:
        return replace(
            empty,
            run_dir=run_dir,
            message=f"Run has no saved input snapshot and cannot be exported: {error}",
        )

    export_dir = destination_dir / run_id
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True)

    _copy_run_folder(run_dir, export_dir)

    receipt = snapshot["receipt"]
    included_video_filenames, excluded_video_filenames = (
        _copy_approved_raw_video(
            site_dir=site_dir, export_dir=export_dir, videos=snapshot["videos"]
        )
        if include_raw_video
        else ([], [])
    )

    _write_run_readme(
        export_dir=export_dir,
        receipt=receipt,
        include_raw_video=include_raw_video,
        included_video_filenames=included_video_filenames,
        excluded_video_filenames=excluded_video_filenames,
    )

    return RunExportResult(
        site_dir=site_dir,
        run_dir=run_dir,
        export_dir=export_dir,
        created=True,
        message="Run export completed.",
        included_raw_video=bool(included_video_filenames),
        excluded_video_filenames=excluded_video_filenames,
    )


def build_export_all(
    sites_dir: Path,
    destination_dir: Path,
    *,
    include_raw_video: bool = False,
) -> SiteExportAllResult:
    """Build a portable bundle of every site under ``sites_dir``.

    Each site is copied as a self-contained site folder (config, labels,
    manifest, and every saved run) so a teammate without that site set up
    locally can copy it straight into their own sites directory and see
    the same sites and run history.
    """

    empty = SiteExportAllResult(
        sites_dir=sites_dir,
        export_dir=Path(),
        created=False,
        message="",
        exported_site_names=[],
        included_raw_video=False,
    )

    if not sites_dir.exists() or not sites_dir.is_dir():
        return replace(empty, message=f"Sites folder does not exist: {sites_dir}")

    site_dirs = sorted(path for path in sites_dir.iterdir() if path.is_dir())
    if not site_dirs:
        return replace(empty, message="No sites were found to export.")

    if destination_dir.exists():
        shutil.rmtree(destination_dir)
    destination_dir.mkdir(parents=True)

    exported_site_names: list[str] = []
    any_video_included = False
    for site_dir in site_dirs:
        site_export_dir = destination_dir / site_dir.name
        site_export_dir.mkdir(parents=True)

        for name in ("configs", "labels"):
            source = site_dir / name
            if source.is_dir():
                shutil.copytree(source, site_export_dir / name)

        manifest_path = site_dir / "manifest.jsonl"
        if manifest_path.is_file():
            shutil.copy2(manifest_path, site_export_dir / "manifest.jsonl")

        runs_dir = site_dir / "outputs" / "runs"
        if runs_dir.is_dir():
            for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
                result = build_run_export(
                    site_dir,
                    run_dir.name,
                    site_export_dir / "outputs" / "runs",
                    include_raw_video=False,
                )
                if not result.created:
                    continue

        if include_raw_video:
            videos_dir = site_dir / "inputs" / "videos"
            if videos_dir.is_dir() and any(videos_dir.iterdir()):
                shutil.copytree(videos_dir, site_export_dir / "inputs" / "videos")
                any_video_included = True

        exported_site_names.append(site_dir.name)

    _write_export_all_readme(
        destination_dir=destination_dir,
        exported_site_names=exported_site_names,
        include_raw_video=include_raw_video,
    )

    return SiteExportAllResult(
        sites_dir=sites_dir,
        export_dir=destination_dir,
        created=True,
        message="Export of all sites completed.",
        exported_site_names=exported_site_names,
        included_raw_video=any_video_included,
    )


def _copy_run_folder(run_dir: Path, export_dir: Path) -> None:
    """Copy a run's own files into export_dir, keeping their original names."""

    shutil.copy2(run_dir / "validation-report.md", export_dir / "validation-report.md")
    shutil.copy2(run_dir / "scorecard.json", export_dir / "scorecard.json")
    if (run_dir / "records").is_dir():
        shutil.copytree(run_dir / "records", export_dir / "records")
    if (run_dir / "review-images").is_dir():
        shutil.copytree(run_dir / "review-images", export_dir / "review-images")
    shutil.copytree(run_dir / "inputs-used", export_dir / "inputs-used")

    metadata = json.loads((run_dir / "run-metadata.json").read_text(encoding="utf-8"))
    metadata.update(
        report_path="validation-report.md",
        scorecard_path="scorecard.json",
        records_path="records",
        review_images_path="review-images",
        inputs_used_path="inputs-used",
    )
    (export_dir / "run-metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )


def _copy_approved_raw_video(
    *, site_dir: Path, export_dir: Path, videos: object
) -> tuple[list[str], list[str]]:
    """Copy raw video only when the current file still matches its run checksum."""

    included: list[str] = []
    excluded: list[str] = []
    videos_dir = site_dir / "inputs" / "videos"
    for entry in videos if isinstance(videos, list) else []:
        filename = str(entry.get("filename", ""))
        expected_sha256 = str(entry.get("sha256", ""))
        source = videos_dir / filename
        if not filename or not source.is_file() or _sha256(source) != expected_sha256:
            excluded.append(filename or "(unknown filename)")
            continue
        destination_dir = export_dir / "videos"
        destination_dir.mkdir(exist_ok=True)
        shutil.copy2(source, destination_dir / filename)
        included.append(filename)
    return included, excluded


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_run_readme(
    *,
    export_dir: Path,
    receipt: dict[str, object],
    include_raw_video: bool,
    included_video_filenames: list[str],
    excluded_video_filenames: list[str],
) -> None:
    lines = [
        "# Exported Validation Run",
        "",
        f"- Site: {receipt.get('site_name', 'unknown')}",
        f"- Site ID: {receipt.get('site_id', 'unknown')}",
        f"- Camera ID: {receipt.get('camera_id', 'unknown')}",
        f"- Run ID: {receipt.get('run_id', 'unknown')}",
        f"- Run status: {receipt.get('status', 'unknown')}",
        f"- Exported at: {datetime.now(tz=UTC).isoformat()}",
        "",
        "## How to use this on another machine",
        "This folder is a copy of the run's own outputs/runs/<run-id>/ folder,",
        "unchanged. Copy it into another OpenFloodAI checkout's",
        "data/sites/<site-name>/outputs/runs/ folder and that site's run",
        "history will pick it up the next time its Home UI loads.",
        "",
        "## What is included",
        "- validation-report.md, scorecard.json, run-metadata.json: this run's own outputs",
        "- records/: this run's machine records, one file per video",
        "- review-images/: evidence images captured during this run",
        "- inputs-used/: the exact config, watched area, manifest, labels, and video "
        "identities used by this run",
        "",
        "## Raw video",
    ]

    if not include_raw_video:
        lines.append("Raw video was not requested for this export and is not included.")
    elif included_video_filenames:
        lines.append("Raw video was approved for this export and is included for:")
        lines.extend(f"- {name}" for name in included_video_filenames)
    else:
        lines.append("Raw video was requested, but no video could be safely included.")

    if excluded_video_filenames:
        lines.append("")
        lines.append(
            "The following video(s) were left out because the current site copy no "
            "longer matches the file used by this run (missing or changed since capture):"
        )
        lines.extend(f"- {name}" for name in excluded_video_filenames)

    lines.extend(
        [
            "",
            "## Notes",
            "This uses the run's own saved inputs, not today's live site files. "
            "This is local validation review evidence only. It is not a production "
            "flood warning or official alert, and it was not uploaded or published "
            "anywhere by this export.",
            "",
        ]
    )
    (export_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_export_all_readme(
    *,
    destination_dir: Path,
    exported_site_names: list[str],
    include_raw_video: bool,
) -> None:
    lines = [
        "# Exported OpenFloodAI Sites",
        "",
        f"- Exported at: {datetime.now(tz=UTC).isoformat()}",
        f"- Sites included: {len(exported_site_names)}",
        "",
        "## How to use this on another machine",
        "Each top-level folder here is a complete site folder (config, labels,",
        "manifest, and run history). Copy any of them into another OpenFloodAI",
        "checkout's data/sites/ folder and that site will appear in its Home UI",
        "with its full run history, ready to review, with no setup needed.",
        "",
        "## Sites",
    ]
    lines.extend(f"- {name}" for name in exported_site_names)
    lines.extend(
        [
            "",
            "## Raw video",
            "Raw video is included for every site's inputs/videos/ folder."
            if include_raw_video
            else "Raw video was not requested for this export and is not included.",
            "",
            "## Notes",
            "This is local validation review evidence only. It is not a production "
            "flood warning or official alert, and it was not uploaded or published "
            "anywhere by this export.",
            "",
        ]
    )
    (destination_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")

"""Export one saved validation run into a shareable local review package.

The package is built only from the run's own saved outputs and its
``inputs-used`` snapshot (see :mod:`openfloodai.validation.input_snapshot`),
never from the site's current live files. Raw video is excluded unless the
caller explicitly opts in, and even then only when the current file on disk
still matches the checksum captured at run time.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from openfloodai.contracts.local_store import read_jsonl_records, write_jsonl_records
from openfloodai.validation.input_snapshot import read_input_snapshot

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class RunExportResult:
    """Result of exporting one local validation run into a review package."""

    site_dir: Path
    run_dir: Path
    export_dir: Path
    zip_path: Path | None
    created: bool
    message: str
    included_raw_video: bool
    excluded_video_filenames: list[str]


def export_run(
    site_dir: Path,
    run_id: str,
    *,
    include_raw_video: bool = False,
    as_zip: bool = False,
) -> RunExportResult:
    """Export one saved run into ``<site_dir>/exports/`` as a review package.

    The default package excludes raw video. Raw video is only ever copied in
    when ``include_raw_video`` is True, and only for videos whose current
    on-disk checksum still matches the checksum saved for that run; any other
    video is left out and named in the generated README instead of being
    silently substituted or silently dropped.
    """

    empty = RunExportResult(
        site_dir=site_dir,
        run_dir=Path(),
        export_dir=Path(),
        zip_path=None,
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

    receipt = snapshot["receipt"]
    site_name = str(receipt.get("site_name") or site_dir.name)

    exports_root = (site_dir / "exports").resolve()
    export_dir = (exports_root / f"{site_name}_{run_id}_review-package").resolve()
    try:
        export_dir.relative_to(exports_root)
    except ValueError:
        return replace(
            empty,
            run_dir=run_dir,
            message="Invalid export path: export must stay inside the site exports directory.",
        )

    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True)

    shutil.copy2(report_path, export_dir / "report.md")
    shutil.copy2(scorecard_path, export_dir / "scorecard.json")
    shutil.copy2(metadata_path, export_dir / "run-metadata.json")
    shutil.copytree(run_dir / "inputs-used", export_dir / "inputs-used")
    if (run_dir / "review-images").is_dir():
        shutil.copytree(run_dir / "review-images", export_dir / "review-images")

    _write_combined_records(run_dir / "records", export_dir / "records.jsonl")
    _write_json(export_dir / "site-summary.json", _build_site_summary(receipt, snapshot))

    included_video_filenames, excluded_video_filenames = (
        _copy_approved_raw_video(
            site_dir=site_dir, export_dir=export_dir, videos=snapshot["videos"]
        )
        if include_raw_video
        else ([], [])
    )

    _write_readme(
        export_dir=export_dir,
        receipt=receipt,
        include_raw_video=include_raw_video,
        included_video_filenames=included_video_filenames,
        excluded_video_filenames=excluded_video_filenames,
    )

    zip_path: Path | None = None
    if as_zip:
        archive_base = str(export_dir)
        shutil.make_archive(
            archive_base, "zip", root_dir=export_dir.parent, base_dir=export_dir.name
        )
        shutil.rmtree(export_dir)
        zip_path = Path(f"{archive_base}.zip")
        export_dir = Path()

    return RunExportResult(
        site_dir=site_dir,
        run_dir=run_dir,
        export_dir=export_dir,
        zip_path=zip_path,
        created=True,
        message="Run export completed.",
        included_raw_video=bool(included_video_filenames),
        excluded_video_filenames=excluded_video_filenames,
    )


def _write_combined_records(records_dir: Path, destination: Path) -> None:
    """Combine every per-video records file for a run into one records.jsonl."""

    if not records_dir.is_dir():
        destination.write_text("", encoding="utf-8")
        return

    for records_path in sorted(records_dir.glob("*.jsonl")):
        write_jsonl_records(destination, read_jsonl_records(records_path))
    if not destination.exists():
        destination.write_text("", encoding="utf-8")


def _build_site_summary(
    receipt: dict[str, object], snapshot: dict[str, object]
) -> dict[str, object]:
    """Build a small, non-sensitive site summary from the run's own snapshot."""

    config = snapshot.get("config")
    config = config if isinstance(config, dict) else {}
    videos = snapshot.get("videos")
    video_count = len(videos) if isinstance(videos, list) else 0
    return {
        "site_name": receipt.get("site_name"),
        "site_id": receipt.get("site_id") or config.get("site_id"),
        "camera_id": receipt.get("camera_id") or config.get("camera_id"),
        "run_id": receipt.get("run_id"),
        "run_status": receipt.get("status"),
        "captured_at": receipt.get("captured_at"),
        "human_label_count": receipt.get("human_label_count"),
        "video_count": video_count,
    }


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


def _write_readme(
    *,
    export_dir: Path,
    receipt: dict[str, object],
    include_raw_video: bool,
    included_video_filenames: list[str],
    excluded_video_filenames: list[str],
) -> None:
    lines = [
        "# Validation Run Review Package",
        "",
        f"- Site: {receipt.get('site_name', 'unknown')}",
        f"- Site ID: {receipt.get('site_id', 'unknown')}",
        f"- Camera ID: {receipt.get('camera_id', 'unknown')}",
        f"- Run ID: {receipt.get('run_id', 'unknown')}",
        f"- Run status: {receipt.get('status', 'unknown')}",
        f"- Exported at: {datetime.now(tz=UTC).isoformat()}",
        "",
        "## What is included",
        "- report.md: the validation report for this run",
        "- scorecard.json: the plain-language scorecard for this run",
        "- records.jsonl: the machine records produced during this run",
        "- run-metadata.json: the run's own metadata",
        "- site-summary.json: a small, non-sensitive site summary",
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
            "This package uses the selected run's saved inputs, not today's live site "
            "files. Later changes to labels, manifest, watched area, or videos are not "
            "reflected here; export the site again after a new run to capture them.",
            "This package is local validation review evidence only. It is not a "
            "production flood warning or official alert, and it was not uploaded or "
            "published anywhere by this export.",
            "",
        ]
    )
    (export_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

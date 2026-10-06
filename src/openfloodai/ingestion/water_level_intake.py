"""Create or extend an image sequence from approved water-level samples (Issue #214 / OF-093).

Two destinations, one set of rules:

- **New sequence**: a fresh, unique sequence ID (never reused, even for an identical
  request), built in a hidden staging folder and renamed into place in one step, so a
  failed or interrupted creation leaves nothing half made. An optional display name is
  stored as metadata; the ID stays the real identity.
- **Append**: add only NEW images to an existing, compatible sequence. Existing images,
  labels, baseline choices, guides and image-to-gauge matches are never rewritten.

Append safety, in the order things happen:

1. Compatibility is checked on the server (same camera, timezone, source, gauge
   parameter, and consistent timestamps). Mixing cameras is refused with reasons.
2. Each approved image is classified against the saved manifest: new, exact duplicate
   (same source identity and size), or conflict (same capture time from another source,
   or the same file name with different content). Duplicates are skipped and conflicts
   are reported; neither is overwritten or renamed.
3. New images download to a staging folder outside `images/`.
4. Under the sequence lock, the plan is re-checked, files are moved into place, the
   batch provenance and merged gauge readings are saved, and the manifest is replaced
   LAST. The manifest is the commit point: it never lists a file that is not there, and
   a crash before it leaves only harmless extra files that a retry adopts.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from openfloodai.contracts import read_jsonl_records
from openfloodai.ingestion import river_images
from openfloodai.ingestion.river_images import (
    MAX_IMAGE_BYTES,
    WATER_LEVEL_SAMPLING_MODE,
    ImageSequenceCandidate,
    ImageSequenceRecord,
    RiverImageError,
)
from openfloodai.ingestion.sequence_store import (
    BATCHES_DIRNAME,
    atomic_write_json,
    atomic_write_text,
    next_batch_number,
    read_display_name,
    sequence_label,
    sequence_lock,
    validate_display_name,
    write_batch,
    write_display_name,
)
from openfloodai.ingestion.usgs_gage_data import (
    PARAMETER_GAGE_HEIGHT,
    GageDataError,
    GageSeries,
    load_gauge_source,
    merge_batch_into_gauge_source,
)

ImageFetcher = Callable[[str], bytes]

STATUS_NEW = "new"
STATUS_DUPLICATE = "duplicate"
STATUS_CONFLICT = "conflict"
STATUS_RETRY = (
    "retry"  # an earlier failed/missing record, or an orphan file from an interrupted append
)

PENDING_PREFIX = ".batch-"
PENDING_SUFFIX = ".pending"


class IntakeError(RiverImageError):
    """A destination or request that cannot be used, with a reason a person can act on."""


def default_fetch_image(url: str) -> bytes:
    """One image from the archive, checked to be a JPEG. Looked up at call time for tests."""

    data, content_type = river_images._fetch(url, limit=MAX_IMAGE_BYTES)
    if content_type != "image/jpeg" or not data.startswith(b"\xff\xd8\xff"):
        raise RiverImageError("The archive did not return a JPEG image.")
    return data


@dataclass(frozen=True)
class ItemPlan:
    candidate: ImageSequenceCandidate
    status: str
    reason: str = ""

    @property
    def filename(self) -> str:
        return self.candidate.source_url.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class IntakePlan:
    """What an approved set would do to a destination, before anything is changed."""

    items: tuple[ItemPlan, ...]

    def _count(self, *statuses: str) -> int:
        return sum(1 for item in self.items if item.status in statuses)

    @property
    def new_count(self) -> int:
        return self._count(STATUS_NEW, STATUS_RETRY)

    @property
    def duplicate_count(self) -> int:
        return self._count(STATUS_DUPLICATE)

    @property
    def conflict_count(self) -> int:
        return self._count(STATUS_CONFLICT)

    def to_dict(self) -> dict[str, Any]:
        return {
            "new": self.new_count,
            "duplicates": self.duplicate_count,
            "conflicts": self.conflict_count,
            "items": [
                {"filename": item.filename, "status": item.status, "reason": item.reason}
                for item in self.items
            ],
        }


@dataclass
class IntakeResult:
    sequence_id: str
    display_name: str | None
    mode: str  # "new" | "append"
    added: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    batch_number: int | None = None
    gauge_available: bool | None = None
    no_op: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence_id": self.sequence_id,
            "display_name": self.display_name,
            "label": sequence_label(self.sequence_id, self.display_name),
            "mode": self.mode,
            "added_count": len(self.added),
            "duplicate_count": len(self.duplicates),
            "conflict_count": len(self.conflicts),
            "failed_count": len(self.failed),
            "added": list(self.added),
            "duplicates": list(self.duplicates),
            "conflicts": list(self.conflicts),
            "failed": list(self.failed),
            "batch_number": self.batch_number,
            "gage_available": self.gauge_available,
            "no_op": self.no_op,
        }


# --- compatibility ----------------------------------------------------------


def _read_summary(sequence_dir: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads((sequence_dir / "download-summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _read_manifest(sequence_dir: Path) -> list[dict[str, Any]] | None:
    path = sequence_dir / "sequence-manifest.jsonl"
    if not path.is_file():
        return None
    try:
        return read_jsonl_records(path)
    except ValueError:
        return None


def compatibility_problems(
    sequence_dir: Path,
    *,
    camera_slug: str,
    timezone_name: str,
    site_id: str,
    nwis_site_id: str,
) -> list[str]:
    """Why this sequence cannot take the camera's new images (empty list: compatible)."""

    problems: list[str] = []
    if sequence_dir.is_symlink() or not sequence_dir.is_dir():
        return ["The sequence folder is missing or not a regular folder."]
    summary = _read_summary(sequence_dir)
    records = _read_manifest(sequence_dir)
    if summary is None or records is None:
        return ["Its saved manifest or summary could not be read."]
    cameras = {str(r.get("camera_id", "")) for r in records if r.get("camera_id")}
    if cameras != {camera_slug}:
        other = ", ".join(sorted(cameras - {camera_slug})) or "unknown"
        problems.append(f"It holds images from a different camera ({other}), not {camera_slug}.")
    if str(summary.get("timezone") or "") != timezone_name:
        problems.append(
            f"Its timestamps use the time zone {summary.get('timezone') or 'unknown'}, "
            f"not {timezone_name}."
        )
    sites = {str(r.get("site_id", "")) for r in records if r.get("site_id")}
    if sites and sites != {site_id}:
        problems.append("It belongs to a different site configuration.")
    if {str(r.get("source_system", "usgs_nims")) for r in records} - {"usgs_nims"}:
        problems.append("It includes images from a source other than the USGS camera archive.")
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001
        return [*problems, "The time zone is not valid."]
    for record in records:
        if record.get("download_status") != "downloaded":
            continue
        try:
            captured = datetime.fromisoformat(str(record["captured_at_utc"]))
            local = datetime.fromisoformat(str(record["local_time"]))
        except (KeyError, ValueError):
            problems.append("Some of its timestamps are missing or unreadable.")
            break
        if captured.utcoffset() is None or captured.astimezone(zone) != local:
            problems.append("Some of its local times do not match its time zone.")
            break
    source = load_gauge_source(sequence_dir)
    if source is not None and source.get("status") == "available":
        parameter = (source.get("parameter") or {}).get("code")
        association = source.get("association") or {}
        if parameter != PARAMETER_GAGE_HEIGHT:
            problems.append("Its saved gauge data is not gauge height, so it cannot be mixed.")
        if association.get("nwis_site_id") not in (None, nwis_site_id):
            problems.append("Its saved gauge data is for a different USGS station.")
    return problems


def list_destinations(
    site_dir: Path, *, camera_slug: str, timezone_name: str, site_id: str, nwis_site_id: str
) -> list[dict[str, Any]]:
    """Every sequence in the site, marked compatible or not, with the reasons if not."""

    root = site_dir / "inputs" / "image-sequences"
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for child in sorted(root.iterdir()):
        if child.name.startswith(".") or not child.is_dir():
            continue
        summary = _read_summary(child)
        if summary is None:
            continue
        problems = compatibility_problems(
            child,
            camera_slug=camera_slug,
            timezone_name=timezone_name,
            site_id=site_id,
            nwis_site_id=nwis_site_id,
        )
        display_name = read_display_name(child)
        rows.append(
            {
                "sequence_id": child.name,
                "display_name": display_name,
                "label": sequence_label(child.name, display_name),
                "downloaded_count": summary.get("downloaded_count", 0),
                "compatible": not problems,
                "reasons": problems,
            }
        )
    return rows


# --- planning ---------------------------------------------------------------


def _same_size(path: Path, candidate: ImageSequenceCandidate) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return candidate.size_bytes in (0, size)


def classify(
    candidates: Sequence[ImageSequenceCandidate],
    records: Sequence[Mapping[str, Any]],
    images_dir: Path,
) -> IntakePlan:
    """Decide, for each approved image, whether it is new, a duplicate, or a conflict."""

    by_url = {str(r.get("source_url")): r for r in records if r.get("source_url")}
    by_time: dict[str, str] = {}
    for record in records:
        if record.get("download_status") == "downloaded" and record.get("captured_at_utc"):
            by_time.setdefault(
                _utc_key(str(record["captured_at_utc"])), str(record.get("source_url"))
            )
    items: list[ItemPlan] = []
    for candidate in candidates:
        name = candidate.source_url.rsplit("/", 1)[-1]
        on_disk = images_dir / name
        existing = by_url.get(candidate.source_url)
        if existing is not None:
            if existing.get("download_status") == "downloaded":
                if not on_disk.is_file():
                    items.append(ItemPlan(candidate, STATUS_RETRY, "Its saved file is missing."))
                elif _same_size(on_disk, candidate):
                    items.append(ItemPlan(candidate, STATUS_DUPLICATE, "Already in the sequence."))
                else:
                    items.append(
                        ItemPlan(
                            candidate,
                            STATUS_CONFLICT,
                            "The saved file has a different size than the archive's image.",
                        )
                    )
            else:
                items.append(
                    ItemPlan(candidate, STATUS_RETRY, "An earlier download did not finish.")
                )
            continue
        clash = by_time.get(_utc_key(candidate.captured_utc.isoformat()))
        if clash is not None and clash != candidate.source_url:
            items.append(
                ItemPlan(candidate, STATUS_CONFLICT, "Another image already has this capture time.")
            )
        elif on_disk.exists():
            if on_disk.is_file() and _same_size(on_disk, candidate):
                items.append(
                    ItemPlan(candidate, STATUS_RETRY, "A file from an interrupted add is reused.")
                )
            else:
                items.append(
                    ItemPlan(candidate, STATUS_CONFLICT, "A different file has this name already.")
                )
        else:
            items.append(ItemPlan(candidate, STATUS_NEW))
    return IntakePlan(tuple(items))


def _utc_key(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(UTC).isoformat()


def plan_for_destination(
    site_dir: Path,
    destination_id: str | None,
    candidates: Sequence[ImageSequenceCandidate],
) -> IntakePlan:
    """The plan for a new sequence (everything is new) or for an existing destination."""

    if destination_id is None:
        return IntakePlan(tuple(ItemPlan(c, STATUS_NEW) for c in candidates))
    sequence_dir = _destination_dir(site_dir, destination_id)
    records = _read_manifest(sequence_dir) or []
    return classify(candidates, records, sequence_dir / "images")


def _destination_dir(site_dir: Path, sequence_id: str) -> Path:
    if not river_images._SEQUENCE_ID_PATTERN.fullmatch(sequence_id):
        raise IntakeError("That is not a valid sequence.")
    root = (site_dir / "inputs" / "image-sequences").resolve()
    path = root / sequence_id
    if path.is_symlink() or not path.is_dir() or path.parent != root:
        raise IntakeError("That sequence was not found in this site.")
    return path


# --- shared record building -------------------------------------------------


def _record(
    candidate: ImageSequenceCandidate, *, site_id: str, slug: str, zone: ZoneInfo, size: int
) -> ImageSequenceRecord:
    return ImageSequenceRecord(
        site_id=site_id,
        camera_id=slug,
        source_url=candidate.source_url,
        captured_at_utc=candidate.captured_utc.isoformat(),
        local_time=candidate.captured_utc.astimezone(zone).isoformat(),
        filename=candidate.source_url.rsplit("/", 1)[-1],
        file_size_bytes=size,
        download_status="downloaded",
    )


def _sample_names(samples: Sequence[Any]) -> set[str]:
    return {str(s["filename"]) for s in samples if isinstance(s, Mapping) and s.get("filename")}


def _batch_record(
    provenance: Mapping[str, Any],
    *,
    batch_id: str,
    mode: str,
    sequence_id: str,
    display_name: str | None,
    added_names: set[str],
    result: IntakeResult,
) -> dict[str, Any]:
    """The saved batch: the sampling provenance, narrowed to what this batch really added."""

    samples = [s for s in provenance.get("samples", []) if s.get("filename") in added_names]
    groups = []
    for group in provenance.get("groups", []):
        added = sum(1 for s in samples if s.get("group") == group.get("group"))
        groups.append({**group, "added": added})
    return {
        **provenance,
        "batch_id": batch_id,
        "committed_at_utc": datetime.now(tz=UTC).isoformat(),
        "destination": {"mode": mode, "sequence_id": sequence_id, "display_name": display_name},
        "samples": samples,
        "groups": groups,
        "skipped_duplicates": list(result.duplicates),
        "conflicts": list(result.conflicts),
        "failed": list(result.failed),
        "relative_note": (
            "Low, middle, and high are relative to THIS batch's date range, not to the whole "
            "sequence, and are never confirmed flood categories."
        ),
    }


def _download_into(
    items: Sequence[ItemPlan], staging_images: Path, fetch: ImageFetcher, result: IntakeResult
) -> dict[str, int]:
    """Download new images into a staging folder; record failures. Returns name -> size."""

    staging_images.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for item in items:
        if item.status == STATUS_RETRY and "reused" in item.reason:
            continue  # the file is already on disk from an interrupted add
        try:
            data = fetch(item.candidate.source_url)
        except RiverImageError as error:
            result.failed.append({"filename": item.filename, "reason": str(error)})
            continue
        (staging_images / item.filename).write_bytes(data)
        sizes[item.filename] = len(data)
    return sizes


# --- new sequence -----------------------------------------------------------


def create_sequence(
    *,
    site_dir: Path,
    site_id: str,
    camera_slug: str,
    timezone_name: str,
    start_date: str,
    end_date: str,
    candidates: Sequence[ImageSequenceCandidate],
    provenance: Mapping[str, Any],
    series: GageSeries,
    gage_relationship: str,
    gage_relationship_note: str | None,
    display_name: object = None,
    fetch: ImageFetcher | None = None,
) -> IntakeResult:
    """Create a new, uniquely named sequence from the approved images."""

    name = validate_display_name(display_name)
    fetch = fetch or default_fetch_image
    if not candidates:
        raise IntakeError("Approve at least one sample before downloading.")
    zone = ZoneInfo(timezone_name)
    root = site_dir / "inputs" / "image-sequences"
    root.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex[:8]
    sequence_id = f"usgs-{camera_slug}-{start_date}-{end_date}-{WATER_LEVEL_SAMPLING_MODE}-{token}"
    final = root / sequence_id
    staging = root / f".staging-{token}"
    result = IntakeResult(sequence_id, name, "new")
    try:
        sizes = _download_into(
            [ItemPlan(c, STATUS_NEW) for c in candidates], staging / "images", fetch, result
        )
        if not sizes:
            raise IntakeError(
                "None of the approved images could be downloaded, so no sequence was created."
            )
        records = sorted(
            (
                _record(c, site_id=site_id, slug=camera_slug, zone=zone, size=sizes[n])
                for c in candidates
                if (n := c.source_url.rsplit("/", 1)[-1]) in sizes
            ),
            key=lambda r: r.captured_at_utc,
        )
        result.added = [r.filename for r in records]
        created = datetime.now(tz=UTC).isoformat()
        if name:
            write_display_name(staging, name, created)
        manifest_rows = [asdict(r) for r in records]
        try:
            summary = merge_batch_into_gauge_source(
                staging,
                series=series,
                batch_start_date=start_date,
                batch_end_date=end_date,
                association=dict(provenance.get("association") or {}),
                manifest_records=manifest_rows,
                gage_relationship=gage_relationship,
                gage_relationship_note=gage_relationship_note,
                batch_id="batch-0001",
            )
            result.gauge_available = summary.available
        except GageDataError:
            result.gauge_available = False
        write_batch(
            staging,
            1,
            _batch_record(
                provenance,
                batch_id="batch-0001",
                mode="new",
                sequence_id=sequence_id,
                display_name=name,
                added_names=set(result.added),
                result=result,
            ),
        )
        result.batch_number = 1
        atomic_write_text(
            staging / "sequence-manifest.jsonl",
            "".join(json.dumps(row) + "\n" for row in manifest_rows),
        )
        atomic_write_json(
            staging / "download-summary.json",
            _summary(
                sequence_id=sequence_id,
                timezone_name=timezone_name,
                camera_slug=camera_slug,
                start_date=start_date,
                end_date=end_date,
                records=manifest_rows,
                display_name=name,
                downloaded_at=created,
                directory=final,
            ),
        )
        os.replace(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return result


def _summary(
    *,
    sequence_id: str,
    timezone_name: str,
    camera_slug: str,
    start_date: str,
    end_date: str,
    records: Sequence[Mapping[str, Any]],
    display_name: str | None,
    downloaded_at: str,
    directory: Path,
    previous: Mapping[str, Any] | None = None,
    batch_count: int = 1,
) -> dict[str, Any]:
    downloaded = sum(1 for r in records if r.get("download_status") == "downloaded")
    missing = sum(1 for r in records if r.get("download_status") == "missing")
    failed = sum(1 for r in records if r.get("download_status") == "failed")
    base: dict[str, Any] = dict(previous or {})
    base.update(
        {
            "success": failed == 0,
            "message": f"Downloaded {downloaded} image(s); {missing} missing; {failed} failed.",
            "output_directory": str(directory),
            "sequence_id": sequence_id,
            "timezone": timezone_name,
            "downloaded_count": downloaded,
            "missing_count": missing,
            "failed_count": failed,
            "records": list(records),
            "camera_url": f"https://apps.usgs.gov/hivis/camera/{camera_slug}",
            "requested_start_date": (
                min(str(previous["requested_start_date"]), start_date) if previous else start_date
            ),
            "requested_end_date": (
                max(str(previous["requested_end_date"]), end_date) if previous else end_date
            ),
            "downloaded_at_utc": base.get("downloaded_at_utc", downloaded_at),
            "sampling_mode": base.get("sampling_mode", WATER_LEVEL_SAMPLING_MODE),
            "batch_count": batch_count,
        }
    )
    if previous:
        base["last_appended_at_utc"] = downloaded_at
    if display_name:
        base["display_name"] = display_name
    return base


# --- append -----------------------------------------------------------------


def recover_pending_batches(sequence_dir: Path) -> None:
    """Finish or discard a batch file left by an interrupted append (call under the lock).

    A pending batch is only made real if every image it claims is in the manifest;
    otherwise the append never committed and its provenance is dropped.
    """

    batches = sequence_dir / BATCHES_DIRNAME
    if not batches.is_dir():
        return
    records = _read_manifest(sequence_dir) or []
    present = {r.get("filename") for r in records if r.get("download_status") == "downloaded"}
    for pending in sorted(batches.glob(f"{PENDING_PREFIX}*{PENDING_SUFFIX}")):
        number = pending.name[len(PENDING_PREFIX) : -len(PENDING_SUFFIX)]
        try:
            loaded = json.loads(pending.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pending.unlink(missing_ok=True)
            continue
        claimed = _sample_names(loaded.get("samples", []))
        target = batches / f"batch-{number}.json"
        if claimed and claimed <= present and not target.exists():
            os.replace(pending, target)
        else:
            pending.unlink(missing_ok=True)


def append_to_sequence(
    *,
    site_dir: Path,
    sequence_id: str,
    site_id: str,
    camera_slug: str,
    timezone_name: str,
    nwis_site_id: str,
    start_date: str,
    end_date: str,
    candidates: Sequence[ImageSequenceCandidate],
    provenance: Mapping[str, Any],
    series: GageSeries,
    gage_relationship: str,
    gage_relationship_note: str | None,
    fetch: ImageFetcher | None = None,
) -> IntakeResult:
    """Add the approved images that are NEW to an existing compatible sequence."""

    fetch = fetch or default_fetch_image
    sequence_dir = _destination_dir(site_dir, sequence_id)
    problems = compatibility_problems(
        sequence_dir,
        camera_slug=camera_slug,
        timezone_name=timezone_name,
        site_id=site_id,
        nwis_site_id=nwis_site_id,
    )
    if problems:
        raise IntakeError("This sequence cannot take these images: " + " ".join(problems))
    zone = ZoneInfo(timezone_name)
    display_name = read_display_name(sequence_dir)
    result = IntakeResult(sequence_id, display_name, "append")

    plan = classify(candidates, _read_manifest(sequence_dir) or [], sequence_dir / "images")
    staging = sequence_dir / f".staging-{uuid4().hex[:8]}"
    try:
        to_get = [i for i in plan.items if i.status in (STATUS_NEW, STATUS_RETRY)]
        sizes = _download_into(to_get, staging / "images", fetch, result)
        with sequence_lock(sequence_dir):
            recover_pending_batches(sequence_dir)
            records = _read_manifest(sequence_dir)
            summary_before = _read_summary(sequence_dir)
            if records is None or summary_before is None:
                raise IntakeError("The sequence's saved metadata could not be read.")
            # Re-check under the lock: another append may have added some of these meanwhile.
            final_plan = classify(candidates, records, sequence_dir / "images")
            adopted: list[tuple[ItemPlan, int]] = []
            for item in final_plan.items:
                if item.status == STATUS_DUPLICATE:
                    result.duplicates.append(item.filename)
                elif item.status == STATUS_CONFLICT:
                    result.conflicts.append({"filename": item.filename, "reason": item.reason})
                elif item.filename in sizes:
                    adopted.append((item, sizes[item.filename]))
                elif item.status == STATUS_RETRY and "reused" in item.reason:
                    adopted.append((item, (sequence_dir / "images" / item.filename).stat().st_size))
            failed_names = {f["filename"] for f in result.failed}
            adopted = [(i, s) for i, s in adopted if i.filename not in failed_names]
            if not adopted:
                result.no_op = True
                return result
            number = next_batch_number(sequence_dir)
            batch_id = f"batch-{number:04d}"
            images_dir = sequence_dir / "images"
            images_dir.mkdir(exist_ok=True)
            moved: list[Path] = []
            new_rows: list[dict[str, Any]] = []
            for item, size in adopted:
                target = images_dir / item.filename
                staged = staging / "images" / item.filename
                if staged.is_file():
                    if target.exists() and not _same_size(target, item.candidate):
                        result.conflicts.append(
                            {"filename": item.filename, "reason": "A different file has this name."}
                        )
                        continue
                    os.replace(staged, target)
                    moved.append(target)
                new_rows.append(
                    asdict(
                        _record(
                            item.candidate, site_id=site_id, slug=camera_slug, zone=zone, size=size
                        )
                    )
                )
                result.added.append(item.filename)
            if not new_rows:
                result.no_op = True
                return result
            retried = {r["filename"] for r in new_rows}
            merged_rows = [r for r in records if r.get("filename") not in retried] + new_rows
            merged_rows.sort(key=lambda r: str(r.get("captured_at_utc", "")))
            batch = _batch_record(
                provenance,
                batch_id=batch_id,
                mode="append",
                sequence_id=sequence_id,
                display_name=display_name,
                added_names=set(result.added),
                result=result,
            )
            pending = (
                sequence_dir / BATCHES_DIRNAME / f"{PENDING_PREFIX}{number:04d}{PENDING_SUFFIX}"
            )
            atomic_write_json(pending, batch)
            try:
                gauge = merge_batch_into_gauge_source(
                    sequence_dir,
                    series=series,
                    batch_start_date=start_date,
                    batch_end_date=end_date,
                    association=dict(provenance.get("association") or {}),
                    manifest_records=merged_rows,
                    gage_relationship=gage_relationship,
                    gage_relationship_note=gage_relationship_note,
                    batch_id=batch_id,
                )
                result.gauge_available = gauge.available
            except GageDataError:
                result.gauge_available = False
            # The manifest is the commit point: written last, and only after every file it
            # lists is in place. Then the batch is made real and the summary refreshed.
            atomic_write_text(
                sequence_dir / "sequence-manifest.jsonl",
                "".join(json.dumps(row) + "\n" for row in merged_rows),
            )
            result.batch_number = number
            os.replace(pending, sequence_dir / BATCHES_DIRNAME / f"{batch_id}.json")
            atomic_write_json(
                sequence_dir / "download-summary.json",
                _summary(
                    sequence_id=sequence_id,
                    timezone_name=timezone_name,
                    camera_slug=camera_slug,
                    start_date=start_date,
                    end_date=end_date,
                    records=merged_rows,
                    display_name=display_name,
                    downloaded_at=datetime.now(tz=UTC).isoformat(),
                    directory=sequence_dir,
                    previous=summary_before,
                    batch_count=number,
                ),
            )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return result

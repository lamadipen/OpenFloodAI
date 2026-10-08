"""Build a small, realistic saved run on disk for dataset-curation tests (no network).

The layout mirrors what a real image-sequence run saves: the downloaded sequence with its
manifest and sampling batch, and a run folder with its frozen inputs (image checksums, gauge
matches, gauge source, site configuration), image records and human review observations.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from openfloodai.curation.common import sha256_bytes

REGION = {"x": 10.0, "y": 20.0, "width": 60.0, "height": 40.0}


@dataclass
class Img:
    day: int  # day of January 2026
    level: float | None = 3.0
    human: str | None = "no_water_level_change"  # None = not reviewed
    match: str = "matched"
    quality: str = "approved"
    group: str = "middle"
    dataset_group: str = "development_candidate"
    camera_stable: str | None = None
    seed: int | None = None
    hour: int = 18
    gap_seconds: int = 30
    qualifiers: list[str] = field(default_factory=lambda: ["A"])

    @property
    def filename_part(self) -> str:
        return f"2026-01-{self.day:02d}T{self.hour:02d}-00-00Z"


@dataclass
class Fixture:
    site_dir: Path
    sites_dir: Path
    run_id: str
    sequence_id: str
    camera: str
    site_id: str
    filenames: list[str]
    shas: dict[str, str]

    @property
    def folder_name(self) -> str:
        return self.site_dir.name


def jpeg_bytes(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    frame = rng.integers(0, 255, size=(24, 32, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    return bytes(encoded)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def make_run(
    root: Path,
    images: list[Img],
    *,
    folder: str = "site-a",
    camera: str = "CAM_A",
    run_id: str = "20261001T100000Z-aaaaaaaa",
    station: str = "09034250",
    relationship: str = "same_site",
    baseline: int = 0,
    parameter_code: str = "00065",
    unit: str = "ft",
) -> Fixture:
    sites_dir = root / "sites"
    site_dir = sites_dir / folder
    site_id = f"{folder}_sid"
    sequence_id = f"usgs-{camera}-2026-01-01-2026-01-31-water_level-{run_id[-8:]}"
    seq_dir = site_dir / "inputs" / "image-sequences" / sequence_id
    run_dir = site_dir / "outputs" / "image-sequence-runs" / run_id
    inputs = run_dir / "inputs-used"
    (seq_dir / "images").mkdir(parents=True)
    inputs.mkdir(parents=True)
    (site_dir / "configs").mkdir(parents=True, exist_ok=True)

    filenames: list[str] = []
    shas: dict[str, str] = {}
    manifest: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    snaps: list[dict[str, Any]] = []
    matches: dict[str, Any] = {}
    observations: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for index, img in enumerate(images):
        name = f"{camera}___{img.filename_part}.jpg"
        data = jpeg_bytes(
            img.seed
            if img.seed is not None
            else zlib.crc32(f"{folder}/{camera}/{run_id}".encode()) % 100000 + index + img.day * 100
        )
        (seq_dir / "images" / name).write_bytes(data)
        sha = sha256_bytes(data)
        filenames.append(name)
        shas[name] = sha
        captured = f"2026-01-{img.day:02d}T{img.hour:02d}:00:00+00:00"
        manifest.append(
            {
                "site_id": site_id,
                "camera_id": camera,
                "source_url": f"https://example.test/720/{camera}/{name}",
                "captured_at_utc": captured,
                "local_time": captured.replace("+00:00", "-07:00"),
                "filename": name,
                "file_size_bytes": len(data),
                "download_status": "downloaded",
                "source_system": "usgs_nims",
            }
        )
        records.append(
            {
                "captured_at_utc": captured,
                "download_status": "downloaded",
                "filename": name,
                "result": "no_water_level_change",
                "region_change_score": 0.1,
                "reason": "machine note",
            }
        )
        snaps.append({"filename": name, "sha256": sha, "size_bytes": len(data)})
        samples.append({"filename": name, "group": img.group})
        if img.level is None or img.match != "matched":
            matches[name] = {
                "match_status": img.match if img.match != "matched" else "missing",
                "reason": "no reading",
                "reading": None,
            }
        else:
            matches[name] = {
                "match_status": "matched",
                "reason": None,
                "reading": {
                    "datetime_utc": captured,
                    "value": img.level,
                    "parameter_code": parameter_code,
                    "parameter_label": "gage height",
                    "unit": unit,
                    "used_fallback_discharge": parameter_code != "00065",
                    "qualifiers": img.qualifiers,
                    "quality_status": img.quality,
                },
                "time_difference_seconds": img.gap_seconds,
            }
        if img.human is not None:
            label: dict[str, Any] = {"human_label": img.human, "confidence": "high"}
            if img.camera_stable:
                label["camera_stable"] = img.camera_stable
            observations.append(
                {
                    "kind": "image",
                    "filename": name,
                    "media_id": sequence_id,
                    "observation_id": f"obs-{index}",
                    "label": label,
                    "label_revision": 1,
                    "reviewed_at_utc": "2026-10-07T20:00:00+00:00",
                    "change_presence": "no_change",
                    "event_validity": "not_reviewed",
                    "dataset_group": img.dataset_group,
                    "config_sha256": "c" * 64,
                    "baseline_filename": filenames[baseline] if baseline < len(filenames) else None,
                }
            )

    _write_jsonl(seq_dir / "sequence-manifest.jsonl", manifest)
    (seq_dir / "sampling-batches").mkdir()
    (seq_dir / "sampling-batches" / "batch-0001.json").write_text(
        json.dumps({"samples": samples}), encoding="utf-8"
    )
    _write_jsonl(inputs / "sequence-manifest.snapshot.jsonl", manifest)
    (inputs / "images.snapshot.json").write_text(json.dumps(snaps), encoding="utf-8")
    (inputs / "gauge-matches.snapshot.json").write_text(
        json.dumps({"matches": matches}), encoding="utf-8"
    )
    (inputs / "gauge-readings.snapshot.json").write_text(
        json.dumps(
            {
                "status": "available",
                "association": {
                    "camera_id": camera,
                    "nwis_site_id": station,
                    "relationship": relationship,
                    "source": "https://example.test/registry",
                    "registry": "demo-river",
                },
                "parameter": {"code": parameter_code, "label": "gage height", "unit": unit},
                "source_url": "https://example.test/nwis",
                "readings": [],
            }
        ),
        encoding="utf-8",
    )
    (inputs / "site-config.snapshot.json").write_text(
        json.dumps({"reference_region": REGION, "normal_waterline_guides": []}), encoding="utf-8"
    )
    (inputs / "receipt.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    (run_dir / "run-summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "sequence_id": sequence_id,
                "site_id": site_id,
                "baseline_filename": filenames[baseline],
                "watched_area_used": REGION,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(run_dir / "image-sequence-records.jsonl", records)
    _write_jsonl(run_dir / "human-review" / "observations.jsonl", observations)
    return Fixture(site_dir, sites_dir, run_id, sequence_id, camera, site_id, filenames, shas)


def add_mask_result(
    fixture: Fixture,
    filename: str,
    *,
    review: str | None = "accepted",
    run_id: str = "20261002T100000Z-bbbbbbbb",
    prompt: str = "river water",
    mask_seed: int = 7,
    detections: bool = True,
    status: str = "completed",
) -> str:
    """A saved hosted-segmentation result with a mask file; returns its result id."""

    run_dir = fixture.site_dir / "outputs" / "hosted-sam-runs" / run_id
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "masks").mkdir()
    result_id = f"001-{prompt.replace(' ', '-')}-{run_id[-4:]}"
    mask = np.random.default_rng(mask_seed).integers(0, 2, size=(8, 8), dtype=np.uint8) * 255
    ok, encoded = cv2.imencode(".png", mask)
    assert ok
    mask_name = f"masks/{result_id}-0.png"
    (run_dir / mask_name).write_bytes(bytes(encoded))
    detection_rows = (
        [
            {
                "object_id": "0",
                "mask_png": mask_name,
                "mask_size": [8, 8],
                "box_source_px": [0, 0, 8, 8],
            }
        ]
        if detections
        else []
    )
    (run_dir / "results" / f"{result_id}.json").write_text(
        json.dumps(
            {
                "result_id": result_id,
                "filename": filename,
                "image_sha256": fixture.shas[filename],
                "prompt": prompt,
                "model_requested": "sam-3.1",
                "status": status,
                "processed_at_utc": "2026-10-07T20:54:30+00:00",
                "transform": {"crop_px": [0, 0, 8, 8]},
                "detections": detection_rows,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-summary.json").write_text(
        json.dumps(
            {"run_id": run_id, "sequence_id": fixture.sequence_id, "result_ids": [result_id]}
        ),
        encoding="utf-8",
    )
    if review:
        (run_dir / "reviews.jsonl").write_text(
            json.dumps(
                {
                    "result_id": result_id,
                    "decision": review,
                    "reviewed_at_utc": "2026-10-07T21:00:00+00:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )
    return result_id

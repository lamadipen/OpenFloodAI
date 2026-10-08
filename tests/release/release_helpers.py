"""Shared builders for release tests: a frozen curated dataset, approvals and a registry."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "curation"))

from curation_fixtures import Fixture, Img, add_mask_result, make_run  # noqa: E402

from openfloodai.curation import (  # noqa: E402
    add_observation,
    add_pair,
    create_dataset,
    freeze_version,
    pin_label_definition,  # noqa: E402
)
from openfloodai.curation import labels as label_defs  # noqa: E402
from openfloodai.release import (  # noqa: E402
    approve_annotation_license,
    approve_site,
    approve_source,
)

CAMERAS = (
    ("site-a", "CAM_A", "train"),
    ("site-b", "CAM_B", "validation"),
    ("site-c", "CAM_C", "test"),
)
RUN_IDS = {
    "CAM_A": "20261001T100000Z-aaaaaaaa",
    "CAM_B": "20261002T100000Z-bbbbbbbb",
    "CAM_C": "20261003T100000Z-cccccccc",
}


def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


def make_data(tmp_path: Path) -> Path:
    """`<tmp>/data` with sites/, datasets/ and reference/ the way the app lays them out."""

    root = data_dir(tmp_path)
    (root / "reference" / "rivers").mkdir(parents=True)
    (root / "reference" / "rivers" / "demo-river.json").write_text(
        json.dumps(
            {
                "river_id": "demo-river",
                "display_name": "Demo River",
                "source": "https://example.test/registry",
                "source_checked": "2026-10-01",
                "notes": "test",
                "cameras": [
                    {
                        "river_id": "demo-river",
                        "camera_id": camera,
                        "nwis_id": "09034250",
                        "state": "CO",
                        "latitude": 40.108319 + index,
                        "longitude": -106.004185,
                        "display_name": camera,
                        "folder_name": folder,
                        "gage_relationship": "same_site",
                        "timezone": "America/Denver",
                    }
                    for index, (folder, camera, _) in enumerate(CAMERAS)
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def approvals(root: Path, *, sites: tuple[str, ...] | None = None, source: bool = True) -> Path:
    policy = root / "release-policy.json"
    if source:
        approve_source(
            policy,
            source_system="usgs_nims",
            license_name="U.S. Government work",
            credit="Images courtesy of the U.S. Geological Survey (USGS).",
            reuse_note="Public USGS camera imagery.",
            approved_by="Lead B",
        )
    approve_annotation_license(
        policy, spdx_id="CC-BY-4.0", holder="OpenFloodAI contributors", approved_by="Lead B"
    )
    for folder, _, _ in CAMERAS:
        if sites is None or folder in sites:
            approve_site(
                policy,
                site_id=f"{folder}_sid",
                location_mode="generalized",
                precision_decimals=1,
                reviewed_by="Reviewer C",
                checks={
                    "faces_reviewed": True,
                    "license_plates_reviewed": True,
                    "private_property_reviewed": True,
                },
            )
    return policy


def frozen_dataset(
    tmp_path: Path,
    *,
    task: str = "gauge_height",
    cameras: tuple[tuple[str, str, str], ...] = CAMERAS,
    images: dict[str, list[Img]] | None = None,
    source_system: str = "usgs_nims",
) -> tuple[Path, str, dict[str, Fixture]]:
    """Curate and freeze a dataset across cameras; returns (datasets_dir, dataset_id, runs)."""

    root = make_data(tmp_path)
    datasets_dir = root / "datasets"
    runs: dict[str, Fixture] = {}
    for folder, camera, _ in cameras:
        imgs = (images or {}).get(camera) or [Img(day=2, level=3.5), Img(day=3, level=4.5)]
        runs[camera] = make_run(
            root,  # make_run puts the site under <root>/sites
            imgs,
            folder=folder,
            camera=camera,
            run_id=RUN_IDS[camera],
            source_system=source_system,
        )
    policy: dict[str, Any] = {
        "kind": "site_camera",
        "assignments": {camera: split for _, camera, split in cameras},
    }
    dataset = create_dataset(
        datasets_dir, name="Release source", task=task, split_policy=policy, change_tolerance=0.1
    )
    if task == "level_classification":
        for folder, _, _ in cameras:
            label_defs.create_definition(
                datasets_dir,
                {
                    "site_id": f"{folder}_sid",
                    "unit": "ft",
                    "station_nwis_id": "09034250",
                    "boundary": "upper_inclusive",
                    "bands": [
                        {"name": "low", "lower": None, "upper": 4.0},
                        {"name": "high", "lower": 4.0, "upper": None},
                    ],
                    "rationale": "Local marks",
                    "author": "Private Author",
                    "approved_by": "Private Approver",
                },
            )
            pin_label_definition(datasets_dir, dataset["dataset_id"], f"{folder}_sid", 1)
    for _folder, camera, _ in cameras:
        fx = runs[camera]
        count = len((images or {}).get(camera) or [0, 0])
        for index in range(count):
            if task == "level_change":
                if index == 0:
                    add_pair(
                        datasets_dir,
                        fx.sites_dir,
                        dataset["dataset_id"],
                        earlier={
                            "folder_name": fx.folder_name,
                            "run_id": fx.run_id,
                            "filename": fx.filenames[0],
                        },
                        later={
                            "folder_name": fx.folder_name,
                            "run_id": fx.run_id,
                            "filename": fx.filenames[1],
                        },
                    )
            else:
                result = add_observation(
                    datasets_dir,
                    fx.sites_dir,
                    dataset["dataset_id"],
                    folder_name=fx.folder_name,
                    run_id=fx.run_id,
                    filename=fx.filenames[index],
                )
                assert result["status"] == "added", result
    freeze_version(
        datasets_dir,
        dataset["dataset_id"],
        note="frozen for release",
        approved_by="Lead B",
        sites_dir=next(iter(runs.values())).sites_dir,
    )
    return datasets_dir, dataset["dataset_id"], runs


__all__ = ["Img", "add_mask_result", "make_run"]

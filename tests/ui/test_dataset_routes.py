"""The dataset curation routes: create, add, conflict decisions, freeze and verify over HTTP."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "curation"))

from curation_fixtures import Img, make_run  # noqa: E402
from test_home_server import get_json, serve_home_ui  # noqa: E402


def post(base: str, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return int(response.status), json.loads(response.read())
    except HTTPError as error:
        return int(error.code), json.loads(error.read())


def test_curating_across_two_runs_over_http_freezes_a_verified_version(tmp_path: Path) -> None:
    a = make_run(tmp_path, [Img(day=2, level=3.5)], folder="site-a", camera="CAM_A")
    b = make_run(
        tmp_path,
        [Img(day=2, level=5.5)],
        folder="site-b",
        camera="CAM_B",
        run_id="20261005T100000Z-bbbbbbbb",
    )
    policy = {"kind": "site_camera", "assignments": {"CAM_A": "train", "CAM_B": "test"}}

    with serve_home_ui(tmp_path / "sites") as base:
        status, created = post(
            base,
            "/api/dataset-create",
            {"name": "Heights", "task": "gauge_height", "split_policy": policy},
        )
        assert status == 200
        dataset_id = created["dataset"]["dataset_id"]
        for fx in (a, b):
            status, added = post(
                base,
                "/api/dataset-add",
                {
                    "dataset_id": dataset_id,
                    "folder_name": fx.folder_name,
                    "run_id": fx.run_id,
                    "filename": fx.filenames[0],
                },
            )
            assert status == 200 and added["status"] == "added"

        view = get_json(f"{base}/api/dataset?dataset_id={dataset_id}")
        assert view["ready_to_freeze"] is True and view["label_counts"]["examples"] == 2
        assert [d["included"] for d in get_json(f"{base}/api/datasets")["datasets"]] == [2]

        # each site's images say which dataset holds them, for the badges on the review pages
        held = get_json(f"{base}/api/dataset-memberships?folder_name={a.folder_name}")[
            "memberships"
        ]
        assert list(held) == [a.filenames[0]]
        assert held[a.filenames[0]] == [
            {
                "dataset_id": dataset_id,
                "name": "Heights",
                "task": "gauge_height",
                "status": "included",
                "role": "single",
                "with_filename": None,
            }
        ]
        assert get_json(f"{base}/api/dataset-memberships?folder_name=nowhere") == {
            "memberships": {}
        }

        status, frozen = post(
            base,
            "/api/dataset-freeze",
            {"dataset_id": dataset_id, "note": "pilot", "approved_by": "Lead B"},
        )
        assert status == 200 and frozen["manifest"]["version"] == 1
        verified = get_json(f"{base}/api/dataset-verify?dataset_id={dataset_id}&version=1")
        assert verified == {"ok": True, "problems": []}


def test_an_ineligible_image_returns_every_reason_and_adds_nothing(tmp_path: Path) -> None:
    fx = make_run(
        tmp_path, [Img(day=2, level=None, match="missing", human="cannot_judge_water_level")]
    )

    with serve_home_ui(tmp_path / "sites") as base:
        _, created = post(base, "/api/dataset-create", {"name": "Heights", "task": "gauge_height"})
        dataset_id = created["dataset"]["dataset_id"]
        status, result = post(
            base,
            "/api/dataset-add",
            {
                "dataset_id": dataset_id,
                "folder_name": fx.folder_name,
                "run_id": fx.run_id,
                "filename": fx.filenames[0],
            },
        )

        assert status == 200 and result["status"] == "ineligible"
        assert {"gauge_not_matched", "unassessable_image"} <= {r["code"] for r in result["reasons"]}
        assert get_json(f"{base}/api/dataset?dataset_id={dataset_id}")["members"] == []


def test_a_conflicting_annotation_is_a_409_until_an_explicit_decision(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=4.0)])
    body = {"folder_name": fx.folder_name, "run_id": fx.run_id, "filename": fx.filenames[0]}

    with serve_home_ui(tmp_path / "sites") as base:
        _, created = post(base, "/api/dataset-create", {"name": "Heights", "task": "gauge_height"})
        body["dataset_id"] = created["dataset"]["dataset_id"]
        post(base, "/api/dataset-add", body)
        matches = (
            fx.site_dir
            / "outputs"
            / "image-sequence-runs"
            / fx.run_id
            / "inputs-used"
            / "gauge-matches.snapshot.json"
        )
        matches.write_text(
            matches.read_text().replace('"value": 4.0', '"value": 4.5'), encoding="utf-8"
        )

        status, conflict = post(base, "/api/dataset-add", body)
        assert status == 409 and conflict["conflict"] is True
        assert conflict["existing"]["value"] == 4.0 and conflict["new"]["value"] == 4.5
        status, kept = post(base, "/api/dataset-add", {**body, "decision": "keep"})
        assert status == 200 and kept["status"] == "kept"
        status, replaced = post(base, "/api/dataset-add", {**body, "decision": "replace"})
        assert status == 200 and replaced["status"] == "replaced"


def test_freezing_an_unready_dataset_explains_what_is_blocking(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2)])

    with serve_home_ui(tmp_path / "sites") as base:
        _, created = post(base, "/api/dataset-create", {"name": "Heights", "task": "gauge_height"})
        dataset_id = created["dataset"]["dataset_id"]
        post(
            base,
            "/api/dataset-add",
            {
                "dataset_id": dataset_id,
                "folder_name": fx.folder_name,
                "run_id": fx.run_id,
                "filename": fx.filenames[0],
            },
        )

        status, result = post(
            base,
            "/api/dataset-freeze",
            {"dataset_id": dataset_id, "note": "n", "approved_by": "me"},
        )

        assert status == 409
        assert "split_unassigned" in {p["code"] for p in result["blocking"]}


def test_definitions_are_created_listed_and_pinned_over_http(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=2, level=4.0)])
    definition = {
        "site_id": fx.site_id,
        "unit": "ft",
        "station_nwis_id": "09034250",
        "boundary": "upper_inclusive",
        "bands": [
            {"name": "low", "lower": None, "upper": 3.0},
            {"name": "high", "lower": 3.0, "upper": None},
        ],
        "rationale": "Local marks",
        "author": "A",
        "approved_by": "B",
    }

    with serve_home_ui(tmp_path / "sites") as base:
        status, made = post(base, "/api/dataset-create-definition", definition)
        assert status == 200 and made["definition"]["version"] == 1
        listed = get_json(f"{base}/api/dataset-label-definitions?site_id={fx.site_id}")
        assert [d["version"] for d in listed["definitions"]] == [1]
        _, created = post(
            base, "/api/dataset-create", {"name": "Classes", "task": "level_classification"}
        )
        status, pinned = post(
            base,
            "/api/dataset-pin-definition",
            {"dataset_id": created["dataset"]["dataset_id"], "site_id": fx.site_id, "version": 1},
        )
        assert status == 200 and pinned["dataset"]["label_definitions"] == {fx.site_id: 1}
        status, bad = post(base, "/api/dataset-create-definition", {**definition, "rationale": ""})
        assert status == 400 and "rationale" in bad["message"].lower()


def test_invalid_requests_are_refused_without_touching_anything(tmp_path: Path) -> None:
    make_run(tmp_path, [Img(day=2)])

    with serve_home_ui(tmp_path / "sites") as base:
        assert post(base, "/api/dataset-create", {"name": "", "task": "gauge_height"})[0] == 400
        assert post(base, "/api/dataset-create", {"name": "X", "task": "nonsense"})[0] == 400
        assert (
            post(base, "/api/dataset-add", {"dataset_id": "../etc", "folder_name": "site-a"})[0]
            == 400
        )
        assert get_json(f"{base}/api/datasets") == {"datasets": []}


def test_dataset_check_is_read_only_for_images_and_for_visual_pairs(tmp_path: Path) -> None:
    fx = make_run(tmp_path, [Img(day=1, level=3.0, human=None), Img(day=2, level=4.0, human=None)])
    for name in (fx.filenames[1],):
        rows = fx.site_dir / "outputs" / "image-sequence-runs" / fx.run_id / "human-review"
        rows.mkdir(parents=True, exist_ok=True)
        with (rows / "observations.jsonl").open("a", encoding="utf-8") as handle:
            for reviewer in ("reviewer-a", "reviewer-b"):
                handle.write(
                    json.dumps(
                        {
                            "kind": "image",
                            "filename": name,
                            "media_id": fx.sequence_id,
                            "observation_id": f"o-{reviewer}",
                            "label": {
                                "human_label": "water_level_rising",
                                "reviewer_id": reviewer,
                                "camera_stable": "yes",
                            },
                            "label_revision": 1,
                            "reviewed_at_utc": "2026-10-08T10:00:00+00:00",
                            "review_stage": "blind",
                            "baseline_filename": fx.filenames[0],
                            "reference": {
                                "sequence_id": fx.sequence_id,
                                "run_id": fx.run_id,
                                "filename": fx.filenames[0],
                            },
                        }
                    )
                    + "\n"
                )
    one = {"folder_name": fx.folder_name, "run_id": fx.run_id}

    with serve_home_ui(tmp_path / "sites") as base:
        _, gauge = post(base, "/api/dataset-create", {"name": "Heights", "task": "gauge_height"})
        _, visual = post(base, "/api/dataset-create", {"name": "Visible", "task": "visual_change"})
        gid, vid = gauge["dataset"]["dataset_id"], visual["dataset"]["dataset_id"]

        single = post(
            base,
            "/api/dataset-check",
            {"dataset_id": gid, **one, "filename": fx.filenames[1]},
        )
        pair = post(
            base,
            "/api/dataset-check",
            {
                "dataset_id": vid,
                "earlier": {**one, "filename": fx.filenames[0]},
                "later": {**one, "filename": fx.filenames[1]},
            },
        )
        wrong = post(
            base,
            "/api/dataset-check",
            {"dataset_id": vid, **one, "filename": fx.filenames[1]},
        )
        listing = get_json(f"{base}/api/datasets")["datasets"]

    assert single[0] == 200 and single[1]["status"] == "eligible"
    assert pair[0] == 200 and pair[1]["status"] == "eligible"
    assert pair[1]["annotation"]["direction"] == "more_water"
    assert pair[1]["agreement"]["reviewers"] == 2
    assert wrong[0] == 400 and "pair" in wrong[1]["message"]
    assert [d["included"] for d in listing] == [0, 0]  # checking added nothing

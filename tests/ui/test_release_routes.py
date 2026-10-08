"""The release routes: approvals, build, verify, checklist and a guarded private upload."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "release"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "curation"))

from release_helpers import approvals, data_dir, frozen_dataset  # noqa: E402
from test_home_server import get_json, serve_home_ui  # noqa: E402

from openfloodai.ui import release_routes  # noqa: E402

CHECKS = {
    "faces_reviewed": True,
    "license_plates_reviewed": True,
    "private_property_reviewed": True,
}


def post(
    base: str, path: str, payload: dict[str, Any], headers: dict[str, str] | None = None
) -> tuple[int, dict[str, Any]]:
    request = Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return int(response.status), json.loads(response.read())
    except HTTPError as error:
        return int(error.code), json.loads(error.read())


def get(base: str, path: str) -> tuple[int, dict[str, Any]]:
    try:
        with urlopen(base + path, timeout=10) as response:
            return int(response.status), json.loads(response.read())
    except HTTPError as error:
        return int(error.code), json.loads(error.read())


class FakeHub:
    def __init__(self, privacy: bool | None = None, files: list[str] | None = None) -> None:
        self.privacy, self.files = privacy, files or []
        self.calls: list[str] = []

    def repo_privacy(self, repo_id: str) -> bool | None:
        return self.privacy

    def repo_files(self, repo_id: str) -> list[str]:
        return self.files

    def create_private_repo(self, repo_id: str) -> None:
        self.calls.append("create_private")

    def upload_folder(self, repo_id: str, folder: Path, message: str) -> None:
        self.calls.append("upload")


def build(base: str, dataset_id: str, version: str = "v0.1") -> tuple[int, dict[str, Any]]:
    return post(
        base,
        "/api/release-build",
        {
            "dataset_id": dataset_id,
            "dataset_version": 1,
            "release_version": version,
            "notes": "First sample.",
        },
    )


# ---- approvals and readiness ----------------------------------------------------------------


def test_the_policy_view_shows_who_approved_what_and_nothing_is_approved_by_default(
    tmp_path: Path,
) -> None:
    frozen_dataset(tmp_path)

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        empty = get_json(f"{base}/api/release-policy")
        assert empty == {"annotation_license": None, "sources": {}, "sites": {}}
        status, _ = post(
            base,
            "/api/release-approve-source",
            {
                "source_system": "usgs_nims",
                "license_name": "PD",
                "approved_by": "Lead",
                "credit": "Images courtesy of the U.S. Geological Survey.",
                "reuse_note": "public",
            },
        )
        assert status == 200
        policy = get_json(f"{base}/api/release-policy")
        assert policy["sources"]["usgs_nims"]["approved_by"] == "Lead"


def test_invalid_approvals_are_refused_and_save_nothing(tmp_path: Path) -> None:
    frozen_dataset(tmp_path)

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        status, result = post(
            base,
            "/api/release-approve-source",
            {
                "source_system": "usgs_nims",
                "license_name": "PD",
                "credit": "Some site",
                "reuse_note": "r",
                "approved_by": "Lead",
            },
        )
        assert status == 400 and "Geological Survey" in result["message"]
        status, result = post(
            base,
            "/api/release-approve-site",
            {"site_id": "s", "reviewed_by": "R", "checks": {"faces_reviewed": True}},
        )
        assert status == 400 and "license_plates_reviewed" in result["message"]
        status, result = post(
            base, "/api/release-approve-license", {"spdx_id": "CC-BY-4.0", "holder": "H"}
        )
        assert status == 400
        assert get_json(f"{base}/api/release-policy")["sources"] == {}


def test_readiness_lists_exactly_what_still_needs_approval(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        before = get_json(f"{base}/api/release-readiness?dataset_id={dataset_id}&version=1")
        assert before["can_build"] is False and before["examples"] == 6
        assert any("annotation license" in m for m in before["missing"])
        assert sum("privacy review" in m for m in before["missing"]) == 3
        approvals(data_dir(tmp_path))
        after = get_json(f"{base}/api/release-readiness?dataset_id={dataset_id}&version=1")
        assert after["can_build"] is True and after["missing"] == []


# ---- build, verify, checklist ---------------------------------------------------------------


def test_building_lists_verifies_and_checklists_a_release(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        status, built = build(base, dataset_id)
        assert status == 200 and built["manifest"]["counts"]["released"] == 6
        releases = get_json(f"{base}/api/dataset-releases?dataset_id={dataset_id}")["releases"]
        assert [r["release_version"] for r in releases] == ["v0.1"]
        assert releases[0]["channel"] == "draft" and len(releases[0]["checklist"]) == 8
        verify = f"/api/release-verify?dataset_id={dataset_id}&release_version=v0.1"
        assert get_json(base + verify) == {"ok": True, "problems": []}
        assert get_json(base + verify + "&require_checklist=1")["ok"] is False

        for index in range(8):
            status, ticked = post(
                base,
                "/api/release-checklist",
                {
                    "dataset_id": dataset_id,
                    "release_version": "v0.1",
                    "index": index,
                    "checked": True,
                },
            )
            assert status == 200
        assert all(item["checked"] for item in ticked["checklist"])
        # Ticking edits the one file that is not checksummed, so the release still verifies.
        assert get_json(base + verify + "&require_checklist=1") == {"ok": True, "problems": []}


def test_a_build_that_is_not_allowed_explains_why(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        status, refused = build(base, dataset_id)
        assert status == 400 and "annotation license" in refused["message"]
        approvals(data_dir(tmp_path))
        assert build(base, dataset_id)[0] == 200
        status, again = build(base, dataset_id)
        assert status == 400 and "never replaced" in again["message"]


def test_release_paths_cannot_escape_the_releases_folder(tmp_path: Path) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        assert get(base, "/api/dataset-releases?dataset_id=../x")[0] == 400
        assert (
            get(base, f"/api/release-verify?dataset_id={dataset_id}&release_version=v0.1/../../x")[
                0
            ]
            == 400
        )
        assert (
            post(
                base,
                "/api/release-checklist",
                {"dataset_id": "../x", "release_version": "v0.1", "index": 0, "checked": True},
            )[0]
            == 400
        )
        assert build(base, "../x")[0] == 400


def test_a_cross_origin_post_is_refused(tmp_path: Path) -> None:
    frozen_dataset(tmp_path)

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        status, _ = post(
            base,
            "/api/release-approve-license",
            {"spdx_id": "CC-BY-4.0", "holder": "H", "approved_by": "A"},
            headers={"Origin": "http://evil.example"},
        )

    assert status == 403
    assert not (data_dir(tmp_path) / "release-policy.json").exists()


# ---- upload ---------------------------------------------------------------------------------


def uploaded_release(tmp_path: Path, base: str) -> str:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))
    assert build(base, dataset_id)[0] == 200
    return dataset_id


def test_the_upload_status_reports_presence_never_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen_dataset(tmp_path)
    monkeypatch.setenv("HF_TOKEN", "super-secret-token-value")

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        status, body = get(base, "/api/release-upload-status")

    assert status == 200 and body["token_set"] is True and body["private_only"] is True
    assert "super-secret-token-value" not in json.dumps(body)


def test_an_upload_needs_the_repository_name_typed_again_and_a_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = FakeHub()
    monkeypatch.setattr(release_routes, "HUB_CLIENT_FACTORY", lambda token: hub)
    monkeypatch.setenv("HF_TOKEN", "t")

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        dataset_id = uploaded_release(tmp_path, base)
        body = {
            "dataset_id": dataset_id,
            "release_version": "v0.1",
            "repo_id": "me/openfloodai-v0-1",
        }
        assert post(base, "/api/release-upload-hf", body)[0] == 400
        assert (
            post(
                base,
                "/api/release-upload-hf",
                {**body, "confirmed": True, "confirm_repo_id": "me/other"},
            )[0]
            == 400
        )
        assert (
            post(
                base,
                "/api/release-upload-hf",
                {**body, "confirmed": False, "confirm_repo_id": body["repo_id"]},
            )[0]
            == 400
        )
        assert hub.calls == []


def test_a_confirmed_upload_goes_to_a_private_repository_and_never_returns_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = FakeHub()
    monkeypatch.setattr(release_routes, "HUB_CLIENT_FACTORY", lambda token: hub)
    monkeypatch.setenv("HF_TOKEN", "super-secret-token-value")

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        dataset_id = uploaded_release(tmp_path, base)
        status, result = post(
            base,
            "/api/release-upload-hf",
            {
                "dataset_id": dataset_id,
                "release_version": "v0.1",
                "repo_id": "me/openfloodai-v0-1",
                "confirm_repo_id": "me/openfloodai-v0-1",
                "confirmed": True,
            },
        )

    assert status == 200 and result["upload"]["private"] is True
    assert hub.calls == ["create_private", "upload"]
    assert "super-secret-token-value" not in json.dumps(result)


def test_an_upload_to_a_public_or_used_repository_or_without_a_token_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public = FakeHub(privacy=False)
    monkeypatch.setattr(release_routes, "HUB_CLIENT_FACTORY", lambda token: public)

    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        dataset_id = uploaded_release(tmp_path, base)
        body = {
            "dataset_id": dataset_id,
            "release_version": "v0.1",
            "repo_id": "me/x",
            "confirm_repo_id": "me/x",
            "confirmed": True,
        }
        monkeypatch.delenv("HF_TOKEN", raising=False)
        status, result = post(base, "/api/release-upload-hf", body)
        assert status == 400 and "HF_TOKEN" in result["message"]
        monkeypatch.setenv("HF_TOKEN", "t")
        status, result = post(base, "/api/release-upload-hf", body)
        assert status == 400 and "already public" in result["message"]
        monkeypatch.setattr(
            release_routes,
            "HUB_CLIENT_FACTORY",
            lambda token: FakeHub(True, ["release-manifest.json"]),
        )
        status, result = post(base, "/api/release-upload-hf", body)
        assert status == 400 and "never replaced" in result["message"]
    assert public.calls == []


def test_kaggle_metadata_is_returned_for_a_verified_release(tmp_path: Path) -> None:
    with serve_home_ui(data_dir(tmp_path) / "sites") as base:
        dataset_id = uploaded_release(tmp_path, base)
        status, result = post(
            base,
            "/api/release-kaggle-metadata",
            {"dataset_id": dataset_id, "release_version": "v0.1", "owner": "someone"},
        )

    assert status == 200 and result["metadata"]["id"] == "someone/openfloodai-dataset-v0-1"

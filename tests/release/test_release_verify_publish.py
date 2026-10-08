"""Release verification, the approval policy, opt-in publishing helpers and the command line."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from release_helpers import approvals, data_dir, frozen_dataset
from test_release_build import build, release_dir

from openfloodai.curation.common import CurationError
from openfloodai.release import (
    approve_annotation_license,
    approve_site,
    approve_source,
    load_policy,
    verify_release,
)
from openfloodai.release.publish import PublishError, kaggle_metadata, upload_to_huggingface
from openfloodai.release.verify import checklist_complete, privacy_findings


def built(tmp_path: Path) -> Path:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    approvals(data_dir(tmp_path))
    build(tmp_path, dataset_id)
    return release_dir(tmp_path)


# ---- verification ---------------------------------------------------------------------------


def test_a_changed_image_or_file_is_detected(tmp_path: Path) -> None:
    root = built(tmp_path)
    image = next((root / "images").rglob("*.jpg"))
    image.write_bytes(b"tampered")

    result = verify_release(root)

    assert result["ok"] is False
    assert any(image.name in p and "changed" in p for p in result["problems"])


def test_an_extra_unlisted_file_is_detected(tmp_path: Path) -> None:
    root = built(tmp_path)
    (root / "images" / "stray.jpg").write_bytes(b"x")

    assert any("not in the checksum list" in p for p in verify_release(root)["problems"])


def test_a_local_path_or_secret_in_any_text_file_fails_verification(tmp_path: Path) -> None:
    root = built(tmp_path)
    (root / "CHANGELOG.md").write_text(
        (root / "CHANGELOG.md").read_text() + "\nsaved at /Users/someone/data\n"
    )
    (root / "README.md").write_text(
        (root / "README.md").read_text() + "\ntoken hf_abcdefghijklmnopqrstuvwx\n"
    )

    findings = privacy_findings(root)

    assert any("CHANGELOG.md" in f and "local_path" in f for f in findings)
    assert any("README.md" in f and "secret" in f for f in findings)
    assert verify_release(root)["ok"] is False


def test_a_camera_in_two_splits_fails_verification(tmp_path: Path) -> None:
    root = built(tmp_path)
    lines = (root / "metadata.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    other = next(
        json.loads(line) for line in lines if json.loads(line)["camera_id"] != first["camera_id"]
    )
    changed = {**first, "split": other["split"]}
    (root / "metadata.jsonl").write_text("\n".join([json.dumps(changed), *lines[1:]]) + "\n")

    problems = verify_release(root)["problems"]

    assert any("more than one split" in p for p in problems)


def test_required_fields_and_forbidden_internal_fields_are_checked(tmp_path: Path) -> None:
    root = built(tmp_path)
    lines = [json.loads(line) for line in (root / "metadata.jsonl").read_text().splitlines()]
    lines[0]["source_url"] = None
    lines[0]["run_id"] = "20261001T100000Z-aaaaaaaa"
    (root / "metadata.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lines))

    problems = verify_release(root)["problems"]

    assert any("missing required fields source_url" in p for p in problems)
    assert any("internal field run_id" in p for p in problems)


def test_the_checklist_must_be_ticked_when_it_is_required(tmp_path: Path) -> None:
    root = built(tmp_path)

    assert verify_release(root)["ok"] is True
    assert (
        "RELEASE-CHECKLIST.md is not fully ticked."
        in verify_release(root, require_checklist=True)["problems"]
    )
    path = root / "RELEASE-CHECKLIST.md"
    path.write_text(path.read_text().replace("- [ ]", "- [x]"))
    assert checklist_complete(root) is True


def test_a_missing_required_file_is_reported_first(tmp_path: Path) -> None:
    root = built(tmp_path)
    (root / "LICENSE-DATA.md").unlink()

    assert verify_release(root) == {"ok": False, "problems": ["LICENSE-DATA.md is missing."]}


# ---- the approval policy --------------------------------------------------------------------


def test_nothing_is_approved_until_a_person_records_it(tmp_path: Path) -> None:
    policy = load_policy(tmp_path / "missing.json")

    assert (
        policy["sources"] == {} and policy["sites"] == {} and policy["annotation_license"] is None
    )


def test_usgs_material_must_be_credited_to_the_usgs(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"

    with pytest.raises(CurationError, match="Geological Survey"):
        approve_source(
            path,
            source_system="usgs_nims",
            license_name="PD",
            credit="Some site",
            reuse_note="r",
            approved_by="A",
        )
    approve_source(
        path,
        source_system="usgs_nims",
        license_name="PD",
        credit="Images courtesy of the U.S. Geological Survey.",
        reuse_note="r",
        approved_by="A",
    )
    assert load_policy(path)["sources"]["usgs_nims"]["approved_by"] == "A"


def test_every_approval_needs_a_named_person(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    with pytest.raises(CurationError):
        approve_annotation_license(path, spdx_id="CC-BY-4.0", holder="H", approved_by="")
    with pytest.raises(CurationError):
        approve_source(
            path, source_system="x", license_name="L", credit="c", reuse_note="r", approved_by=" "
        )
    assert not path.exists()


def test_a_privacy_review_must_cover_faces_plates_and_private_property(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"

    with pytest.raises(CurationError, match="license_plates_reviewed"):
        approve_site(
            path,
            site_id="s",
            location_mode="generalized",
            precision_decimals=1,
            reviewed_by="R",
            checks={
                "faces_reviewed": True,
                "license_plates_reviewed": False,
                "private_property_reviewed": True,
            },
        )
    with pytest.raises(CurationError, match="named approver"):
        approve_site(
            path,
            site_id="s",
            location_mode="exact_approved",
            precision_decimals=1,
            reviewed_by="R",
            checks={
                "faces_reviewed": True,
                "license_plates_reviewed": True,
                "private_property_reviewed": True,
            },
        )
    assert not path.exists()


def test_an_exact_location_needs_its_own_approval_and_omitted_hides_it(tmp_path: Path) -> None:
    from openfloodai.release.policy import location_for

    path = tmp_path / "policy.json"
    checks = {
        "faces_reviewed": True,
        "license_plates_reviewed": True,
        "private_property_reviewed": True,
    }
    approve_site(
        path,
        site_id="a",
        location_mode="exact_approved",
        precision_decimals=1,
        reviewed_by="R",
        checks=checks,
        exact_location_approved_by="Owner",
    )
    approve_site(
        path,
        site_id="b",
        location_mode="omitted",
        precision_decimals=1,
        reviewed_by="R",
        checks=checks,
    )
    approve_site(
        path,
        site_id="c",
        location_mode="generalized",
        precision_decimals=0,
        reviewed_by="R",
        checks=checks,
    )
    policy = load_policy(path)

    assert location_for(policy, "a", 40.123456, -106.987654) == {
        "latitude": 40.123456,
        "longitude": -106.987654,
        "precision": "exact_approved",
    }
    assert location_for(policy, "b", 40.1, -106.9) is None
    assert location_for(policy, "c", 40.6, -106.4) == {
        "latitude": 41.0,
        "longitude": -106.0,
        "precision": "generalized_0_decimals",
    }
    assert location_for(policy, "unknown", 40.1, -106.9) is None


# ---- publishing helpers ---------------------------------------------------------------------


class FakeHub:
    def __init__(self, privacy: bool | None = None, files: list[str] | None = None) -> None:
        self.privacy, self.files = privacy, files or []
        self.calls: list[tuple[str, Any]] = []

    def repo_privacy(self, repo_id: str) -> bool | None:
        return self.privacy

    def repo_files(self, repo_id: str) -> list[str]:
        return self.files

    def create_private_repo(self, repo_id: str) -> None:
        self.calls.append(("create_private", repo_id))

    def upload_folder(self, repo_id: str, folder: Path, message: str) -> None:
        self.calls.append(("upload", (repo_id, folder.name, message)))


def upload(
    root: Path, hub: FakeHub, *, confirmed: bool = True, repo: str = "me/openfloodai-v0-1"
) -> dict[str, Any]:
    return upload_to_huggingface(root, repo, confirmed=confirmed, client_factory=lambda token: hub)


def test_nothing_is_uploaded_without_explicit_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = built(tmp_path)
    monkeypatch.setenv("HF_TOKEN", "t")
    hub = FakeHub()

    with pytest.raises(PublishError, match="--yes"):
        upload(root, hub, confirmed=False)
    assert hub.calls == []


def test_an_unverified_release_is_not_uploaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = built(tmp_path)
    (next((root / "images").rglob("*.jpg"))).write_bytes(b"x")
    monkeypatch.setenv("HF_TOKEN", "t")
    hub = FakeHub()

    with pytest.raises(PublishError, match="did not pass verification"):
        upload(root, hub)
    assert hub.calls == []


def test_a_token_is_required_and_comes_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = built(tmp_path)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    with pytest.raises(PublishError, match="HF_TOKEN"):
        upload(root, FakeHub())


def test_a_verified_release_uploads_to_a_private_repository_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = built(tmp_path)
    monkeypatch.setenv("HF_TOKEN", "secret-token-value")
    hub = FakeHub()

    result = upload(root, hub)

    assert result["private"] is True and result["release_version"] == "v0.1"
    assert hub.calls[0] == ("create_private", "me/openfloodai-v0-1")
    assert hub.calls[1][0] == "upload" and "v0.1" in hub.calls[1][1][2]
    assert "secret-token-value" not in json.dumps(result)


def test_a_public_repository_or_one_with_a_release_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = built(tmp_path)
    monkeypatch.setenv("HF_TOKEN", "t")

    public = FakeHub(privacy=False)
    with pytest.raises(PublishError, match="already public"):
        upload(root, public)
    holds = FakeHub(privacy=True, files=["release-manifest.json", "README.md"])
    with pytest.raises(PublishError, match="never replaced"):
        upload(root, holds)
    assert public.calls == [] and holds.calls == []


def test_a_malformed_repository_name_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = built(tmp_path)
    monkeypatch.setenv("HF_TOKEN", "t")

    for bad in ("no-owner", "a/b/c", "bad name/x"):
        with pytest.raises(PublishError, match="owner/name"):
            upload(root, FakeHub(), repo=bad)


def test_kaggle_metadata_is_generated_only_for_a_verified_release(tmp_path: Path) -> None:
    root = built(tmp_path)

    meta = kaggle_metadata(root, "someone")

    assert meta["id"] == "someone/openfloodai-dataset-v0-1"
    assert meta["licenses"] == [{"name": "other"}] and "flood detector" in meta["description"]
    (root / "images" / "x.jpg").write_bytes(b"x")
    with pytest.raises(PublishError):
        kaggle_metadata(root, "someone")


# ---- command line ---------------------------------------------------------------------------


def _cli() -> Any:
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "export_dataset_release.py"
    spec = importlib.util.spec_from_file_location("export_dataset_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(tmp_path: Path, *args: str) -> int:
    code: int = _cli().main(["--data-dir", str(data_dir(tmp_path)), *args])
    return code


def test_the_command_line_records_approvals_builds_and_verifies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)
    assert (
        run(
            tmp_path,
            "approve-source",
            "--source-system",
            "usgs_nims",
            "--license-name",
            "PD",
            "--credit",
            "Images courtesy of the U.S. Geological Survey.",
            "--reuse-note",
            "public",
            "--approved-by",
            "Lead",
        )
        == 0
    )
    assert (
        run(
            tmp_path,
            "approve-annotation-license",
            "--spdx-id",
            "CC-BY-4.0",
            "--holder",
            "OpenFloodAI",
            "--approved-by",
            "Lead",
        )
        == 0
    )
    for site in ("site-a_sid", "site-b_sid", "site-c_sid"):
        assert (
            run(
                tmp_path,
                "approve-site",
                "--site-id",
                site,
                "--reviewed-by",
                "Rev",
                "--faces-reviewed",
                "--license-plates-reviewed",
                "--private-property-reviewed",
            )
            == 0
        )
    out = tmp_path / "cli-out"

    assert (
        run(
            tmp_path,
            "build",
            "--dataset-id",
            dataset_id,
            "--dataset-version",
            "1",
            "--release-version",
            "v0.1",
            "--notes",
            "first",
            "--output-dir",
            str(out),
        )
        == 0
    )
    assert "Nothing was uploaded" in capsys.readouterr().out
    assert run(tmp_path, "verify", str(out / "openfloodai-dataset-v0.1")) == 0


def test_the_command_line_explains_a_refusal_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, dataset_id, _ = frozen_dataset(tmp_path)

    code = run(
        tmp_path,
        "build",
        "--dataset-id",
        dataset_id,
        "--dataset-version",
        "1",
        "--release-version",
        "v0.1",
        "--notes",
        "n",
        "--output-dir",
        str(tmp_path / "o"),
    )

    assert code == 1
    assert "annotation license" in capsys.readouterr().err
    assert (
        run(tmp_path, "approve-site", "--site-id", "s", "--reviewed-by", "R", "--faces-reviewed")
        == 1
    )
    assert "license_plates_reviewed" in capsys.readouterr().err


def test_the_command_line_upload_needs_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = built(tmp_path)
    monkeypatch.setenv("HF_TOKEN", "t")

    assert run(tmp_path, "upload-hf", str(root), "--repo-id", "me/x") == 1
    assert "--yes" in capsys.readouterr().err


# ---- the checklist is the one editable file -------------------------------------------------


def test_ticking_the_checklist_changes_only_that_line_and_the_release_still_verifies(
    tmp_path: Path,
) -> None:
    from openfloodai.release.checklist import read_checklist, set_checklist_item

    root = built(tmp_path)
    before = (root / "RELEASE-CHECKLIST.md").read_text().splitlines()

    items = set_checklist_item(root, 2, True)

    after = (root / "RELEASE-CHECKLIST.md").read_text().splitlines()
    assert [i["checked"] for i in items] == [False, False, True] + [False] * 5
    assert [a for a, b in zip(after, before, strict=True) if a != b] == [
        before[after.index(next(a for a, b in zip(after, before, strict=True) if a != b))].replace(
            "[ ]", "[x]"
        )
    ]
    assert verify_release(root) == {"ok": True, "problems": []}
    assert read_checklist(root)[2]["checked"] is True
    set_checklist_item(root, 2, False)
    assert read_checklist(root)[2]["checked"] is False


def test_a_checklist_item_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    from openfloodai.release.checklist import set_checklist_item

    root = built(tmp_path)

    for index in (-1, 8, 99):
        with pytest.raises(CurationError):
            set_checklist_item(root, index, True)

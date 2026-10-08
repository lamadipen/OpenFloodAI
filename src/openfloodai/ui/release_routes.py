"""Routes for the dataset release section (Issue #207): approvals, build, verify, checklist, upload.

A release is built from one FROZEN dataset version (see dataset curation) into
`<data>/releases/<dataset-id>/openfloodai-dataset-<version>/`. Building never uploads. The upload
route sends a verified release to a PRIVATE Hugging Face repository only, needs an explicit
confirmation that repeats the repository name, and reads its token from an environment variable;
no route accepts, stores, returns or logs a token.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from openfloodai.curation import CurationError
from openfloodai.curation.common import validate_dataset_id
from openfloodai.release import (
    POLICY_FILENAME,
    ReleaseError,
    approve_annotation_license,
    approve_site,
    approve_source,
    build_release,
    load_policy,
    verify_release,
)
from openfloodai.release.builder import VERSION_PATTERN
from openfloodai.release.checklist import read_checklist, set_checklist_item
from openfloodai.release.policy import site_approved, source_approved
from openfloodai.release.publish import (
    DEFAULT_TOKEN_ENV,
    HubClient,
    PublishError,
    kaggle_metadata,
    upload_to_huggingface,
)

# Tests replace this with a fake so no real upload is ever attempted.
HUB_CLIENT_FACTORY: Callable[[str], HubClient] | None = None

_GET_PATHS = {
    "/api/release-policy",
    "/api/dataset-releases",
    "/api/release-readiness",
    "/api/release-verify",
    "/api/release-upload-status",
}
_POST_PATHS = {
    "/api/release-approve-source",
    "/api/release-approve-license",
    "/api/release-approve-site",
    "/api/release-build",
    "/api/release-checklist",
    "/api/release-upload-hf",
    "/api/release-kaggle-metadata",
}
_MAX_BODY_BYTES = 32 * 1024
_RELEASE_DIR = re.compile(r"^openfloodai-dataset-(v\d+\.\d+(?:\.\d+)?)$")


def _roots(handler: Any) -> tuple[Path, Path, Path, Path]:
    datasets_dir: Path = handler._datasets_dir()
    data_root = datasets_dir.parent
    return (
        datasets_dir,
        data_root / POLICY_FILENAME,
        handler._reference_dir(),
        data_root / "releases",
    )


def _release_path(releases_dir: Path, dataset_id: str, version: str) -> Path:
    validate_dataset_id(dataset_id)
    if not VERSION_PATTERN.fullmatch(version):
        raise CurationError("Choose a valid release version, such as v0.1.")
    path = releases_dir / dataset_id / f"openfloodai-dataset-{version}"
    if not path.is_dir():
        raise CurationError("Release not found.")
    return path


def _policy_view(policy: dict[str, Any]) -> dict[str, Any]:
    """The approvals as the page shows them: who approved what and when, nothing secret."""

    return {
        "annotation_license": policy["annotation_license"],
        "sources": policy["sources"],
        "sites": {
            site: {
                "location": entry["location"],
                "privacy_review": {
                    k: entry["privacy_review"].get(k)
                    for k in ("status", "reviewed_by", "reviewed_at_utc", "notes")
                },
            }
            for site, entry in policy["sites"].items()
        },
    }


def _frozen_samples(datasets_dir: Path, dataset_id: str, version: int) -> list[dict[str, Any]]:
    validate_dataset_id(dataset_id)
    path = datasets_dir / dataset_id / "versions" / f"v{int(version):04d}" / "samples.jsonl"
    if not path.is_file():
        raise CurationError("That frozen version was not found.")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def readiness(
    datasets_dir: Path, policy_path: Path, dataset_id: str, version: int
) -> dict[str, Any]:
    """What a release of this frozen version still needs approved, before it can be built."""

    policy = load_policy(policy_path)
    samples = _frozen_samples(datasets_dir, dataset_id, version)
    sources: set[str] = set()
    sites: set[str] = set()
    for sample in samples:
        for obs in sample["observations"]:
            sources.add(str(obs["source"].get("source_system")))
            sites.add(str(obs["site"].get("site_id")))
    splits = json.loads(
        (datasets_dir / dataset_id / "versions" / f"v{int(version):04d}" / "splits.json").read_text(
            encoding="utf-8"
        )
    )
    missing: list[str] = []
    if not policy["annotation_license"]:
        missing.append("The annotation license has not been recorded.")
    missing += [
        f"The source '{s}' has no approved reuse permission."
        for s in sorted(sources)
        if not source_approved(policy, s)
    ]
    missing += [
        f"Site '{s}' has no approved privacy review."
        for s in sorted(sites)
        if not site_approved(policy, s)
    ]
    if splits["policy"]["kind"] != "site_camera":
        missing.append("This dataset uses time-block splits, which cannot be released.")
    site_splits: dict[str, set[str]] = {}
    for sample in samples:
        split = splits["assignments"].get(sample["sample_id"])
        for obs in sample["observations"]:
            if split:
                site_splits.setdefault(str(obs["site"].get("site_id")), set()).add(split)
    missing += [
        f"Site '{site}' has cameras in different splits ({', '.join(sorted(found))}). One site "
        "must stay in one split."
        for site, found in sorted(site_splits.items())
        if len(found) > 1
    ]
    return {
        "examples": len(samples),
        "sources": [{"name": s, "approved": source_approved(policy, s)} for s in sorted(sources)],
        "sites": [{"site_id": s, "approved": site_approved(policy, s)} for s in sorted(sites)],
        "annotation_license_recorded": bool(policy["annotation_license"]),
        "split_kind": splits["policy"]["kind"],
        "missing": missing,
        "can_build": not missing,
    }


def list_releases(releases_dir: Path, dataset_id: str) -> list[dict[str, Any]]:
    validate_dataset_id(dataset_id)
    folder = releases_dir / dataset_id
    rows: list[dict[str, Any]] = []
    if not folder.is_dir():
        return rows
    for path in sorted(folder.iterdir()):
        match = _RELEASE_DIR.fullmatch(path.name)
        manifest = path / "release-manifest.json"
        if not match or not manifest.is_file():
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        rows.append(
            {
                "release_version": data["release_version"],
                "channel": data["channel"],
                "counts": data["counts"],
                "publication_ready": data["publication_ready"],
                "readiness_gaps": data["readiness_gaps"],
                "source_version": data["source"]["version"],
                "content_digest": data["content_digest"],
                "checklist": read_checklist(path),
            }
        )
    return rows


def upload_status() -> dict[str, Any]:
    """Whether an upload could run here. It reports presence only, never a token value."""

    import importlib.util

    return {
        "token_env": DEFAULT_TOKEN_ENV,
        "token_set": bool(os.environ.get(DEFAULT_TOKEN_ENV)),
        "hub_installed": importlib.util.find_spec("huggingface_hub") is not None,
        "private_only": True,
    }


def handle_get(handler: Any, path: str) -> bool:
    if path not in _GET_PATHS:
        return False
    query = parse_qs(urlsplit(handler.path).query)

    def first(name: str) -> str:
        return str(query.get(name, [""])[0])

    datasets_dir, policy_path, _reference, releases_dir = _roots(handler)
    try:
        if path == "/api/release-policy":
            payload: dict[str, Any] = _policy_view(load_policy(policy_path))
        elif path == "/api/dataset-releases":
            payload = {"releases": list_releases(releases_dir, first("dataset_id"))}
        elif path == "/api/release-readiness":
            payload = readiness(
                datasets_dir, policy_path, first("dataset_id"), int(first("version") or 0)
            )
        elif path == "/api/release-upload-status":
            payload = upload_status()
        else:
            root = _release_path(releases_dir, first("dataset_id"), first("release_version"))
            payload = verify_release(root, require_checklist=first("require_checklist") == "1")
        handler._send_json(payload, status_code=200)
    except (CurationError, ValueError, OSError, KeyError) as error:
        handler._send_json({"success": False, "message": str(error)}, status_code=400)
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path not in _POST_PATHS:
        return False
    data = handler._reject_untrusted_json_post(_MAX_BODY_BYTES)
    if data is None:
        return True
    try:
        payload = _dispatch(path, data, handler)
        handler._send_json({"success": True, **payload}, status_code=200)
    except ReleaseError as error:
        handler._send_json(
            {"success": False, "message": str(error), "details": error.details}, status_code=400
        )
    except (CurationError, PublishError, ValueError, KeyError, TypeError) as error:
        handler._send_json({"success": False, "message": str(error)}, status_code=400)
    except OSError:
        handler._send_json(
            {"success": False, "message": "Could not save. Check disk space and permissions."},
            status_code=500,
        )
    return True


def _text(data: dict[str, Any], name: str) -> str:
    return str(data.get(name, "")).strip()


def _dispatch(path: str, data: dict[str, Any], handler: Any) -> dict[str, Any]:
    datasets_dir, policy_path, reference_dir, releases_dir = _roots(handler)
    if path == "/api/release-approve-source":
        approve_source(
            policy_path,
            source_system=_text(data, "source_system"),
            license_name=_text(data, "license_name"),
            credit=_text(data, "credit"),
            reuse_note=_text(data, "reuse_note"),
            approved_by=_text(data, "approved_by"),
        )
        return {"policy": _policy_view(load_policy(policy_path))}
    if path == "/api/release-approve-license":
        approve_annotation_license(
            policy_path,
            spdx_id=_text(data, "spdx_id"),
            holder=_text(data, "holder"),
            approved_by=_text(data, "approved_by"),
        )
        return {"policy": _policy_view(load_policy(policy_path))}
    if path == "/api/release-approve-site":
        checks = data.get("checks")
        approve_site(
            policy_path,
            site_id=_text(data, "site_id"),
            location_mode=_text(data, "location_mode") or "generalized",
            precision_decimals=int(data.get("precision_decimals", 1)),
            reviewed_by=_text(data, "reviewed_by"),
            checks={k: v is True for k, v in (checks if isinstance(checks, dict) else {}).items()},
            notes=_text(data, "notes"),
            exact_location_approved_by=_text(data, "exact_location_approved_by"),
        )
        return {"policy": _policy_view(load_policy(policy_path))}
    dataset_id = _text(data, "dataset_id")
    if path == "/api/release-build":
        version = _text(data, "release_version")
        manifest = build_release(
            datasets_dir=datasets_dir,
            dataset_id=dataset_id,
            dataset_version=int(data.get("dataset_version", 0)),
            output_dir=releases_dir / validate_dataset_id(dataset_id),
            release_version=version,
            notes=_text(data, "notes"),
            policy_path=policy_path,
            reference_dir=reference_dir,
            previous_release=_previous(releases_dir, dataset_id, _text(data, "previous_version")),
            write_parquet=data.get("parquet") is True,
        )
        return {"manifest": manifest}
    root = _release_path(releases_dir, dataset_id, _text(data, "release_version"))
    if path == "/api/release-checklist":
        items = set_checklist_item(root, int(data.get("index", -1)), data.get("checked") is True)
        return {"checklist": items}
    if path == "/api/release-kaggle-metadata":
        return {"metadata": kaggle_metadata(root, _text(data, "owner"))}
    repo_id = _text(data, "repo_id")
    if data.get("confirmed") is not True or _text(data, "confirm_repo_id") != repo_id:
        raise PublishError(
            "Confirm the upload: tick the box and type the repository name exactly as above."
        )
    return {
        "upload": upload_to_huggingface(
            root, repo_id, confirmed=True, client_factory=HUB_CLIENT_FACTORY
        )
    }


def _previous(releases_dir: Path, dataset_id: str, version: str) -> Path | None:
    return _release_path(releases_dir, dataset_id, version) if version else None

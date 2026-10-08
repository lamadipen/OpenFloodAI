"""Opt-in publishing helpers (Issue #207): a private Hugging Face upload and Kaggle metadata.

Building a release never uploads anything. These helpers run only when explicitly asked for, and
only after the release passes `verify_release`:

- The Hugging Face upload always targets a PRIVATE dataset repository. Making a repository
  public is a separate human step taken after the verification checklist in the release is done.
  It refuses a repository that is already public, and one that already holds a release.
- The token is read from an environment variable and is never written anywhere.
- Kaggle gets a generated `dataset-metadata.json`; the files to upload are the identical frozen
  release files. No Kaggle upload code is included.
"""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from openfloodai.release.verify import verify_release

DEFAULT_TOKEN_ENV = "HF_TOKEN"


class PublishError(ValueError):
    """The release cannot be published, with the reason."""


class HubClient(Protocol):
    """The few Hugging Face Hub calls the upload needs (a fake in tests)."""

    def repo_privacy(self, repo_id: str) -> bool | None: ...

    def repo_files(self, repo_id: str) -> list[str]: ...

    def create_private_repo(self, repo_id: str) -> None: ...

    def upload_folder(self, repo_id: str, folder: Path, message: str) -> None: ...


class _HfHubClient:
    """The real client, built from the optional huggingface_hub package."""

    def __init__(self, token: str) -> None:
        try:
            hub = importlib.import_module("huggingface_hub")
        except ImportError as error:
            raise PublishError(
                "Uploading needs the optional huggingface_hub package. Install it with "
                "pip install 'openfloodai[export]'."
            ) from error
        self._api: Any = hub.HfApi(token=token)
        self._errors: Any = importlib.import_module("huggingface_hub.utils")

    def repo_privacy(self, repo_id: str) -> bool | None:
        try:
            info = self._api.dataset_info(repo_id)
        except self._errors.RepositoryNotFoundError:
            return None
        return bool(info.private)

    def repo_files(self, repo_id: str) -> list[str]:
        return [str(name) for name in self._api.list_repo_files(repo_id, repo_type="dataset")]

    def create_private_repo(self, repo_id: str) -> None:
        self._api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)

    def upload_folder(self, repo_id: str, folder: Path, message: str) -> None:
        self._api.upload_folder(
            folder_path=str(folder), repo_id=repo_id, repo_type="dataset", commit_message=message
        )


def upload_to_huggingface(
    release_dir: Path,
    repo_id: str,
    *,
    confirmed: bool,
    token_env: str = DEFAULT_TOKEN_ENV,
    client_factory: Callable[[str], HubClient] | None = None,
) -> dict[str, Any]:
    """Upload a verified release to a private Hugging Face dataset repository."""

    if not confirmed:
        raise PublishError("Uploading sends this release to Hugging Face. Confirm with --yes.")
    if "/" not in repo_id or repo_id.count("/") != 1 or any(c.isspace() for c in repo_id):
        raise PublishError("The repository must look like owner/name.")
    check = verify_release(release_dir)
    if not check["ok"]:
        raise PublishError(
            "The release did not pass verification, so it is not uploaded: "
            + "; ".join(check["problems"][:5])
        )
    token = os.environ.get(token_env, "")
    if not token:
        raise PublishError(f"Set the {token_env} environment variable to a Hugging Face token.")
    client = (client_factory or _HfHubClient)(token)
    privacy = client.repo_privacy(repo_id)
    if privacy is False:
        raise PublishError(
            "That repository is already public. Releases are first uploaded privately."
        )
    if privacy is True and "release-manifest.json" in client.repo_files(repo_id):
        raise PublishError(
            "That repository already holds a release. A published release is never replaced; "
            "use a new repository for a new version."
        )
    manifest = json.loads((release_dir / "release-manifest.json").read_text(encoding="utf-8"))
    client.create_private_repo(repo_id)
    client.upload_folder(
        repo_id, release_dir, f"OpenFloodAI dataset release {manifest['release_version']}"
    )
    return {
        "repo_id": repo_id,
        "private": True,
        "release_version": manifest["release_version"],
        "next": "Work through RELEASE-CHECKLIST.md before making the repository public.",
    }


def kaggle_metadata(release_dir: Path, owner: str) -> dict[str, Any]:
    """`dataset-metadata.json` content for mirroring the identical release files to Kaggle."""

    check = verify_release(release_dir)
    if not check["ok"]:
        raise PublishError("Only a release that passes verification can be mirrored.")
    manifest = json.loads((release_dir / "release-manifest.json").read_text(encoding="utf-8"))
    version = str(manifest["release_version"])
    slug = release_dir.name.lower().replace(".", "-")
    return {
        "title": f"OpenFloodAI river camera dataset {version}",
        "id": f"{owner}/{slug}",
        "licenses": [{"name": "other"}],
        "subtitle": "Reviewed river camera images with gauge readings and human review.",
        "description": (
            "Research data from OpenFloodAI. See README.md and LICENSE-DATA.md in the files for "
            "sources, credit, intended use and limits. Not a flood detector or warning system."
        ),
    }

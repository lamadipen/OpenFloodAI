"""Routes for curating local training datasets from reviewed observations (Issue #215).

Everything here reads saved runs and writes only inside the datasets directory. Nothing trains a
model, uploads, or changes a run, a gauge match, a site configuration or a human review.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from openfloodai import curation
from openfloodai.curation import labels as label_defs
from openfloodai.curation import store

_GET_PATHS = {
    "/api/datasets",
    "/api/dataset",
    "/api/dataset-verify",
    "/api/dataset-label-definitions",
    "/api/dataset-memberships",
}
_POST_PATHS = {
    "/api/dataset-create",
    "/api/dataset-add",
    "/api/dataset-add-pair",
    "/api/dataset-check",
    "/api/dataset-reject",
    "/api/dataset-remove",
    "/api/dataset-split-policy",
    "/api/dataset-pin-definition",
    "/api/dataset-create-definition",
    "/api/dataset-freeze",
}
_MAX_BODY_BYTES = 32 * 1024


def _text(data: dict[str, Any], name: str) -> str:
    return str(data.get(name, "")).strip()


def _ref(data: Any) -> dict[str, str]:
    if not isinstance(data, dict):
        raise curation.CurationError("Name the run and image.")
    return {
        "folder_name": str(data.get("folder_name", "")),
        "run_id": str(data.get("run_id", "")),
        "filename": str(data.get("filename", "")),
    }


def handle_get(handler: Any, path: str) -> bool:
    if path not in _GET_PATHS:
        return False
    query = parse_qs(urlsplit(handler.path).query)

    def first(name: str) -> str:
        return str(query.get(name, [""])[0])

    datasets_dir = handler._datasets_dir()
    try:
        if path == "/api/datasets":
            handler._send_json({"datasets": curation.list_datasets(datasets_dir)}, status_code=200)
        elif path == "/api/dataset":
            handler._send_json(
                curation.dataset_view(datasets_dir, first("dataset_id"), handler.sites_dir),
                status_code=200,
            )
        elif path == "/api/dataset-memberships":
            handler._send_json(
                {"memberships": curation.memberships(datasets_dir, first("folder_name"))},
                status_code=200,
            )
        elif path == "/api/dataset-verify":
            result = curation.verify_version(
                datasets_dir, first("dataset_id"), int(first("version") or 0)
            )
            handler._send_json(result, status_code=200)
        else:
            handler._send_json(
                {
                    "definitions": label_defs.list_definition_versions(
                        datasets_dir, first("site_id")
                    )
                },
                status_code=200,
            )
    except (curation.CurationError, ValueError, OSError) as error:
        handler._send_json({"success": False, "message": str(error)}, status_code=400)
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path not in _POST_PATHS:
        return False
    data = handler._reject_untrusted_json_post(_MAX_BODY_BYTES)
    if data is None:
        return True
    datasets_dir = handler._datasets_dir()
    sites_dir = handler.sites_dir
    try:
        payload = _dispatch(path, data, datasets_dir, sites_dir)
        handler._send_json({"success": True, **payload}, status_code=200)
    except curation.CurationConflict as conflict:
        handler._send_json(
            {"success": False, "conflict": True, "message": str(conflict), **conflict.details},
            status_code=409,
        )
    except (curation.CurationError, ValueError, KeyError, TypeError) as error:
        handler._send_json({"success": False, "message": str(error)}, status_code=400)
    except OSError:
        handler._send_json(
            {"success": False, "message": "Could not save. Check disk space and permissions."},
            status_code=500,
        )
    return True


def _dispatch(path: str, data: dict[str, Any], datasets_dir: Any, sites_dir: Any) -> dict[str, Any]:
    dataset_id = _text(data, "dataset_id")
    decision = _text(data, "decision") or None
    if path == "/api/dataset-create":
        tolerance = data.get("change_tolerance")
        dataset = curation.create_dataset(
            datasets_dir,
            name=_text(data, "name"),
            task=_text(data, "task"),
            split_policy=data.get("split_policy"),
            change_tolerance=tolerance if tolerance not in (None, "") else None,
        )
        return {"dataset": dataset}
    if path == "/api/dataset-add":
        return curation.add_observation(
            datasets_dir,
            sites_dir,
            dataset_id,
            **_ref(data),
            mask_result_id=_text(data, "mask_result_id") or None,
            mask_run_id=_text(data, "mask_run_id") or None,
            decision=decision,
        )
    if path == "/api/dataset-add-pair":
        return curation.add_pair(
            datasets_dir,
            sites_dir,
            dataset_id,
            earlier=_ref(data.get("earlier")),
            later=_ref(data.get("later")),
            decision=decision,
        )
    if path == "/api/dataset-check":
        # Read-only: says whether an image or pair would be accepted, and why not. Writes nothing.
        if isinstance(data.get("earlier"), dict) or isinstance(data.get("later"), dict):
            return curation.check_pair(
                datasets_dir,
                sites_dir,
                dataset_id,
                earlier=_ref(data.get("earlier")),
                later=_ref(data.get("later")),
            )
        return curation.check_observation(
            datasets_dir,
            sites_dir,
            dataset_id,
            **_ref(data),
            mask_result_id=_text(data, "mask_result_id") or None,
            mask_run_id=_text(data, "mask_run_id") or None,
        )
    if path == "/api/dataset-reject":
        return curation.reject_observation(
            datasets_dir, sites_dir, dataset_id, **_ref(data), note=_text(data, "note")
        )
    if path == "/api/dataset-remove":
        return curation.remove_member(datasets_dir, dataset_id, _text(data, "member_id"))
    if path == "/api/dataset-split-policy":
        return {"dataset": curation.set_split_policy(datasets_dir, dataset_id, data.get("policy"))}  # type: ignore[arg-type]
    if path == "/api/dataset-pin-definition":
        return {
            "dataset": curation.pin_label_definition(
                datasets_dir, dataset_id, _text(data, "site_id"), int(data.get("version", 0))
            )
        }
    if path == "/api/dataset-create-definition":
        return {"definition": label_defs.create_definition(datasets_dir, data)}
    manifest = curation.freeze_version(
        datasets_dir,
        dataset_id,
        note=_text(data, "note"),
        approved_by=_text(data, "approved_by"),
        sites_dir=sites_dir,
    )
    return {"manifest": manifest}


__all__ = ["handle_get", "handle_post", "store"]

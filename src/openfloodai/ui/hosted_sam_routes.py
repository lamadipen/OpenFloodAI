"""Routes for the optional hosted SAM plugin (Issue #210).

Credential and upload decisions are made here, on the backend. The browser is
only ever sent a masked hint and a configured flag, never the key. Every POST
goes through the same local-only JSON guard as other actions that can reach the
network, so a cross-origin form cannot start a paid request.
"""

from __future__ import annotations

import inspect
from typing import Any
from urllib.parse import parse_qs, urlsplit

from openfloodai.config import SiteConfigError, load_site_config
from openfloodai.evidence.hosted_sam_credentials import CredentialError
from openfloodai.evidence.settings import EvidenceSettingsError, resolve_effective_adapter_settings
from openfloodai.validation import hosted_sam_runner as runner
from openfloodai.vision import hosted_sam as sam

_GET_PATHS = {
    "/api/hosted-sam/status",
    "/api/hosted-sam/runs",
    "/api/hosted-sam/run",
    "/api/hosted-sam/overlay",
}
_POST_PATHS = {
    "/api/hosted-sam/credential",
    "/api/hosted-sam/acknowledge",
    "/api/hosted-sam/preflight",
    "/api/hosted-sam/run",
    "/api/hosted-sam/review",
}


def _class_setting(handler: Any, name: str) -> Any:
    """A handler class setting, unwrapped so a plain function is not bound as a method."""

    raw = inspect.getattr_static(handler, name)
    return raw.__func__ if isinstance(raw, staticmethod) else raw


def _status_payload(handler: Any, folder_name: str) -> dict[str, Any]:
    enabled = _plugin_enabled(handler, folder_name)
    return {
        "plugin_id": runner.PLUGIN_ID,
        "enabled": enabled,
        "credential": handler.hosted_sam_credentials.status(),
        "decoder_available": _class_setting(handler, "hosted_sam_decoder") is not None,
        "provider": {
            "name": "Meta hosted SAM",
            "model": sam.MODEL_ID,
            "signup_url": sam.SIGNUP_URL,
            "terms_url": sam.TERMS_URL,
            "privacy_url": sam.PRIVACY_URL,
            "pricing_note": sam.PRICING_NOTE,
            "retention_note": (
                "The provider page does not state how long uploaded images are kept or "
                "whether they are used for training. Read the provider's terms and "
                "privacy policy before uploading."
            ),
        },
        "limits": {
            "max_images_per_batch": runner.MAX_IMAGES_PER_BATCH,
            "max_concepts_per_batch": runner.MAX_CONCEPTS_PER_BATCH,
            "request_timeout_seconds": sam.REQUEST_TIMEOUT_SECONDS,
            "automatic_retries": 0,
        },
    }


def _plugin_enabled(handler: Any, folder_name: str) -> bool:
    overrides = None
    if folder_name:
        site_dir = handler._resolve_site_dir(folder_name)
        paths = sorted((site_dir / "configs").glob("*.json"))
        if not paths:
            raise ValueError("Site not found.")
        overrides = load_site_config(paths[0]).evidence_adapter_overrides
    return resolve_effective_adapter_settings(handler._reference_dir(), overrides)[runner.PLUGIN_ID]


def handle_get(handler: Any, path: str) -> bool:
    if path not in _GET_PATHS:
        return False
    query = parse_qs(urlsplit(handler.path).query)

    def first(name: str) -> str:
        return str(query.get(name, [""])[0])

    try:
        if path == "/api/hosted-sam/status":
            handler._send_json(_status_payload(handler, first("folder_name")), status_code=200)
            return True
        site_dir = handler._resolve_site_dir(first("folder_name"))
        if path == "/api/hosted-sam/runs":
            rows = runner.list_sam_runs(site_dir, first("sequence_id") or None)
            handler._send_json({"runs": rows}, status_code=200)
        elif path == "/api/hosted-sam/run":
            handler._send_json(runner.read_sam_run(site_dir, first("run_id")), status_code=200)
        else:
            body = runner.render_overlay(site_dir, first("run_id"), first("result_id"))
            handler.send_response(200)
            handler.send_header("Content-Type", "image/png")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
    except (ValueError, OSError, KeyError, SiteConfigError, EvidenceSettingsError):
        handler._send_json({"message": "Not found."}, status_code=404)
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path not in _POST_PATHS:
        return False
    data = handler._reject_untrusted_json_post()
    if data is None:
        return True
    credentials = handler.hosted_sam_credentials
    try:
        if path == "/api/hosted-sam/credential":
            if data.get("remove") is True:
                credentials.remove_session_key()
            else:
                credentials.set_session_key(data.get("api_key"))
            handler._send_json(
                {"success": True, "credential": credentials.status()}, status_code=200
            )
        elif path == "/api/hosted-sam/acknowledge":
            if data.get("acknowledged") is not True:
                raise ValueError("Confirm the upload and billing notice to continue.")
            credentials.acknowledge_upload()
            handler._send_json(
                {"success": True, "credential": credentials.status()}, status_code=200
            )
        else:
            _handle_site_post(handler, path, data)
    except CredentialError as error:
        handler._send_json({"success": False, "message": str(error)}, status_code=400)
    except runner.HostedSamRefused as refusal:
        handler._send_json(
            {"success": False, "code": refusal.code, "message": refusal.message}, status_code=409
        )
    except (ValueError, OSError, SiteConfigError, EvidenceSettingsError) as error:
        handler._send_json({"success": False, "message": str(error)}, status_code=400)
    return True


def _handle_site_post(handler: Any, path: str, data: dict[str, Any]) -> None:
    folder_name = str(data.get("folder_name", "")).strip()
    site_dir = handler._resolve_site_dir(folder_name)
    if path == "/api/hosted-sam/review":
        entry = runner.record_sam_review(
            site_dir,
            str(data.get("run_id", "")),
            str(data.get("result_id", "")),
            str(data.get("decision", "")),
        )
        handler._send_json({"success": True, "review": entry}, status_code=200)
        return
    sequence_id = str(data.get("sequence_id", "")).strip()
    filenames = data.get("filenames")
    concepts = data.get("concepts")
    if not isinstance(filenames, list) or not isinstance(concepts, list):
        raise ValueError("filenames and concepts must be lists.")
    names = [str(name) for name in filenames]
    concept_list = [str(concept) for concept in concepts]
    if path == "/api/hosted-sam/preflight":
        plan = runner.plan_segmentation(site_dir, sequence_id, names, concept_list)
        handler._send_json({"success": True, "plan": plan.to_dict()}, status_code=200)
        return
    summary = runner.run_segmentation(
        site_dir,
        sequence_id,
        names,
        concept_list,
        plugin_enabled=_plugin_enabled(handler, folder_name),
        credentials=handler.hosted_sam_credentials,
        confirmed_request_count=data.get("confirmed_request_count"),
        decoder=_class_setting(handler, "hosted_sam_decoder"),
        transport=_class_setting(handler, "hosted_sam_transport"),
    )
    handler._send_json({"success": True, "run": summary}, status_code=200)

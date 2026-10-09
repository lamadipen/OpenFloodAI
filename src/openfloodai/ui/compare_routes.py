"""Routes for comparing any two saved images of one camera in Review (Issue #223).

Everything here only READS saved runs, images and masks. `measure` never writes; `save` writes
one new, content-addressed record and only when the person asks for it. No route starts a
segmentation, uploads an image or changes a label, a baseline, a dataset or a saved run.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from openfloodai.curation.common import CurationError
from openfloodai.ingestion.river_images import RiverImageError
from openfloodai.water_change import compare
from openfloodai.water_change.pair import EndpointRef

_GET_PATHS = {"/api/compare/candidates", "/api/compare/thumbnail", "/api/compare/overlay"}
_POST_PATHS = {"/api/compare/measure", "/api/compare/save"}
_MAX_BODY_BYTES = 8 * 1024


def _ref(data: Any, what: str) -> EndpointRef:
    if not isinstance(data, dict) or not data.get("run_id") or not data.get("filename"):
        raise ValueError(f"Name the run and image for {what}.")
    return EndpointRef(str(data["run_id"]), str(data["filename"]))


def _send_bytes(handler: Any, body: bytes, content_type: str) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "private, max-age=300")
    handler.end_headers()
    handler.wfile.write(body)


def handle_get(handler: Any, path: str) -> bool:
    if path not in _GET_PATHS:
        return False
    query = parse_qs(urlsplit(handler.path).query)

    def first(name: str) -> str:
        return str(query.get(name, [""])[0])

    try:
        if path == "/api/compare/candidates":
            handler._send_json(
                compare.candidates(handler.sites_dir, first("folder_name"), first("run_id")),
                status_code=200,
            )
        elif path == "/api/compare/thumbnail":
            site_dir = handler._resolve_site_dir(first("folder_name"))
            _send_bytes(
                handler,
                compare.thumbnail(site_dir, first("sequence_id"), first("filename")),
                "image/jpeg",
            )
        else:
            body = compare.overlay_png(
                handler.sites_dir,
                first("folder_name"),
                EndpointRef(first("a_run"), first("a_file")),
                EndpointRef(first("b_run"), first("b_file")),
            )
            _send_bytes(handler, body, "image/png")
    except compare.CompareUnavailable as error:
        handler._send_json({"message": str(error)}, status_code=409)
    except (CurationError, RiverImageError, ValueError, OSError):
        handler._send_json({"message": "Not found."}, status_code=404)
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path not in _POST_PATHS:
        return False
    data = handler._reject_untrusted_json_post(_MAX_BODY_BYTES)
    if data is None:
        return True
    try:
        result = compare.compare_pair(
            handler.sites_dir,
            str(data.get("folder_name", "")),
            _ref(data.get("a"), "the first image"),
            _ref(data.get("b"), "the second image"),
            framing_confirmed=data.get("framing_confirmed") is True,
            save=path == "/api/compare/save",
        )
        handler._send_json({"success": True, **result}, status_code=200)
    except (CurationError, ValueError) as error:
        handler._send_json({"success": False, "message": str(error)}, status_code=400)
    except OSError:
        handler._send_json(
            {"success": False, "message": "Could not save. Check disk space and permissions."},
            status_code=500,
        )
    return True

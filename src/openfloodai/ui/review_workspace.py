"""Routes for the standalone review workspace; existing pages keep their routes."""

from __future__ import annotations

from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlsplit

from openfloodai.review.workspace import (
    catalogue,
    evidence,
    media_path,
    save_group,
    save_observation,
)
from openfloodai.validation.site_runner import run_site_validation


def handle_get(handler: Any, path: str) -> bool:
    if path == "/review-workspace.html":
        source = handler.ui_path.parent / "openfloodai-review-workspace.html"
        page = (
            source
            if source.is_file()
            else resources.files("openfloodai.ui") / "static" / source.name
        )
        body = page.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    if path not in {"/api/workspace-runs", "/api/workspace-evidence", "/api/workspace-media"}:
        return False
    query = parse_qs(urlsplit(handler.path).query)
    try:
        site = handler._resolve_site_dir(query.get("folder_name", [""])[0])
        if path == "/api/workspace-runs":
            handler._send_json({"runs": catalogue(site)}, status_code=200)
        else:
            kind, run_id, media_id = (query.get(k, [""])[0] for k in ("kind", "run_id", "media_id"))
            if path == "/api/workspace-evidence":
                handler._send_json(evidence(site, kind, run_id, media_id), status_code=200)
            else:
                filename = query.get("filename", [""])[0]
                source = media_path(site, kind, run_id, media_id, filename)
                # Stream ranges rather than reading an entire large video into memory.
                size = source.stat().st_size
                start, end = 0, size - 1
                raw_range = handler.headers.get("Range")
                if raw_range:
                    if not raw_range.startswith("bytes=") or "," in raw_range:
                        raise ValueError("Unsupported byte range.")
                    left, right = raw_range[6:].split("-", 1)
                    if left:
                        start = int(left)
                        end = min(int(right), end) if right else end
                    else:
                        start = max(0, size - int(right))
                    if not 0 <= start <= end < size:
                        handler.send_response(416)
                        handler.send_header("Content-Range", f"bytes */{size}")
                        handler.end_headers()
                        return True
                handler.send_response(206 if raw_range else 200)
                media_types = {
                    ".mp4": "video/mp4",
                    ".mov": "video/quicktime",
                    ".avi": "video/x-msvideo",
                    ".mkv": "video/x-matroska",
                }
                handler.send_header(
                    "Content-Type",
                    "image/jpeg"
                    if kind == "image"
                    else media_types.get(source.suffix.lower(), "application/octet-stream"),
                )
                handler.send_header("Content-Length", str(end - start + 1))
                handler.send_header("Accept-Ranges", "bytes")
                handler.send_header("Cache-Control", "no-store")
                if raw_range:
                    handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                handler.end_headers()
                with source.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = stream.read(min(remaining, 65536))
                        if not chunk:
                            break
                        handler.wfile.write(chunk)
                        remaining -= len(chunk)
    except (OSError, ValueError, KeyError) as error:
        handler._send_json({"success": False, "message": str(error)}, status_code=400)
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path not in {"/api/workspace-label", "/api/workspace-group", "/api/workspace-analyse"}:
        return False
    data = handler._reject_untrusted_json_post()
    if data is None:
        return True
    try:
        site = handler._resolve_site_dir(str(data.get("folder_name", "")))
        if path == "/api/workspace-label":
            result = save_observation(site, data)
        elif path == "/api/workspace-group":
            save_group(site, data)
            result = {"success": True, "message": "Dataset group saved."}
        else:
            report = run_site_validation(site, analyse_full_video=True)
            result = {
                "success": True,
                "message": "Video analysis complete.",
                "run_id": report.run_id,
            }
        handler._send_json(result, status_code=200)
    except (OSError, ValueError, KeyError) as error:
        handler._send_json({"success": False, "message": str(error)}, status_code=400)
    return True

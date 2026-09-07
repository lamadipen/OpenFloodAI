"""Reusable HTTP handler and helpers for the local OpenFloodAI home UI."""

from __future__ import annotations

import json
import tempfile
from email.parser import BytesParser
from email.policy import HTTP
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from openfloodai.config import SiteConfigError, write_reference_region
from openfloodai.review import (
    ALLOWED_CONFIDENCE_LEVELS,
    ALLOWED_HUMAN_LABELS,
    create_human_label_record,
    repair_manifest_from_local_videos,
)
from openfloodai.review.dataset_manifest import HARD_CASE_TYPE_OPTIONS, MANIFEST_PURPOSE_OPTIONS
from openfloodai.validation import (
    discover_validation_site_statuses,
    intake_validation_video,
    run_site_validation,
    setup_validation_site,
)
from openfloodai.validation.site_status import VIDEO_SUFFIXES


class OpenFloodAIHomeHandler(SimpleHTTPRequestHandler):
    """Serve the local UI and site-status JSON."""

    sites_dir: Path
    ui_path: Path

    def do_GET(self) -> None:
        """Serve site-status JSON or the static local UI."""

        path = urlsplit(self.path).path
        if path == "/api/sites":
            self._send_sites_json()
            return
        if path in {"/", "/openfloodai-home-ui.html", "/site-details.html"}:
            self._send_file(self.ui_path, content_type="text/html; charset=utf-8")
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        """Handle site setup and video intake requests."""

        if self.path == "/api/setup-site-with-video":
            self._handle_setup_site_with_video()
            return
        if self.path == "/api/setup-site":
            self._handle_setup_site()
            return
        if self.path == "/api/intake-video":
            self._handle_intake_video()
            return
        if self.path == "/api/add-label":
            self._handle_add_label()
            return
        if self.path == "/api/run-validation":
            self._handle_run_validation()
            return
        if self.path == "/api/repair-manifest":
            self._handle_repair_manifest()
            return
        self.send_error(404, "Not found")

    def log_message(self, format: str, *args: Any) -> None:
        """Keep local UI output quiet."""

    def _handle_setup_site(self) -> None:
        data = self._read_json_body()
        if data is None:
            return

        result = setup_validation_site(
            sites_base_dir=self.sites_dir,
            folder_name=str(data.get("folder_name", "")),
            site_id=str(data.get("site_id", "")),
            camera_id=str(data.get("camera_id", "")),
            site_name=str(data.get("site_name", "")),
            public_location=str(data.get("public_location", "")),
            privacy_notes=str(data.get("privacy_notes", "")),
            overwrite=_as_bool(data.get("overwrite"), default=False),
        )

        self._send_json(
            {
                "success": result.created,
                "message": result.message,
                "site_dir": str(result.site_dir) if result.created else None,
                "config_path": str(result.config_path) if result.created else None,
            },
            status_code=200 if result.created else 400,
        )

    def _handle_setup_site_with_video(self) -> None:
        parsed = self._read_multipart_intake()
        if parsed is None:
            return
        data, temp_video = parsed
        if temp_video is None:
            self._send_json(
                {
                    "success": False,
                    "message": "Choose a local video file before creating the site.",
                },
                status_code=400,
            )
            return
        try:
            reference_region = _parse_reference_region(data.get("reference_region"))
            if reference_region is None:
                self._send_json(
                    {
                        "success": False,
                        "message": "Select a watched area before creating the site.",
                    },
                    status_code=400,
                )
                return
            setup_result = setup_validation_site(
                sites_base_dir=self.sites_dir,
                folder_name=str(data.get("folder_name", "")),
                site_id=str(data.get("site_id", "")),
                camera_id=str(data.get("camera_id", "")),
                site_name=str(data.get("site_name", "")),
                public_location=str(data.get("public_location", "")),
                privacy_notes=str(data.get("privacy_notes", "")),
                overwrite=False,
            )
            if not setup_result.created:
                self._send_json(
                    {"success": False, "message": setup_result.message}, status_code=400
                )
                return
            intake_result = intake_validation_video(
                site_dir=setup_result.site_dir,
                video_path=temp_video,
                video_id=str(data.get("video_id", "")),
                purpose=str(data.get("purpose", "")),
                split=str(data.get("split", "")),
                notes=str(data.get("notes", "")),
                approved_for_repo=_as_bool(data.get("approved_for_repo"), default=False),
                hard_case_type=str(data.get("hard_case_type", "")),
                overwrite=False,
            )
            if not intake_result.created:
                self._send_json(
                    {"success": False, "message": intake_result.message}, status_code=400
                )
                return
            write_reference_region(setup_result.config_path, reference_region)
            self._send_json(
                {
                    "success": True,
                    "message": "Created the site and added its first local video.",
                    "site_dir": str(setup_result.site_dir),
                    "config_path": str(setup_result.config_path),
                    "video_path": str(intake_result.video_path),
                },
                status_code=200,
            )
        except SiteConfigError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
        finally:
            if temp_video is not None and temp_video.exists():
                temp_video.unlink()

    def _handle_intake_video(self) -> None:
        parsed = self._read_intake_request()
        if parsed is None:
            return
        data, temp_video = parsed

        try:
            folder_name = str(data.get("folder_name", "")).strip()
            if not folder_name:
                self._send_json(
                    {"success": False, "message": "Missing required fields: folder_name."},
                    status_code=400,
                )
                return

            site_dir = (self.sites_dir / folder_name).resolve()
            try:
                site_dir.relative_to(self.sites_dir.resolve())
            except ValueError:
                self._send_json(
                    {
                        "success": False,
                        "message": (
                            "Invalid folder_name: site folder must stay inside the sites directory."
                        ),
                    },
                    status_code=400,
                )
                return

            video_path = temp_video or Path(str(data.get("video_path", "")))
            reference_region = _parse_reference_region(data.get("reference_region"))
            config_path = _find_site_config(site_dir) if reference_region is not None else None
            result = intake_validation_video(
                site_dir=site_dir,
                video_path=video_path,
                video_id=str(data.get("video_id", "")),
                purpose=str(data.get("purpose", "")),
                split=str(data.get("split", "")),
                notes=str(data.get("notes", "")),
                approved_for_repo=_as_bool(data.get("approved_for_repo"), default=False),
                hard_case_type=str(data.get("hard_case_type", "")),
                overwrite=_as_bool(data.get("overwrite"), default=False),
            )

            if result.created and reference_region is not None:
                assert config_path is not None
                write_reference_region(config_path, reference_region)

            self._send_json(
                {
                    "success": result.created,
                    "message": result.message,
                    "site_dir": str(result.site_dir) if result.created else None,
                    "video_path": str(result.video_path) if result.created else None,
                    "manifest_path": str(result.manifest_path) if result.created else None,
                    "config_path": str(config_path) if config_path is not None else None,
                },
                status_code=200 if result.created else 400,
            )
        except SiteConfigError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
        finally:
            if temp_video is not None and temp_video.exists():
                temp_video.unlink()

    def _handle_add_label(self) -> None:
        data = self._read_json_body()
        if data is None:
            return

        folder_name = str(data.get("folder_name", "")).strip()
        if not folder_name:
            self._send_json(
                {"success": False, "message": "Missing required field: folder_name."},
                status_code=400,
            )
            return

        site_dir = (self.sites_dir / folder_name).resolve()
        try:
            site_dir.relative_to(self.sites_dir.resolve())
        except ValueError:
            self._send_json(
                {
                    "success": False,
                    "message": (
                        "Invalid folder_name: site folder must stay inside the sites directory."
                    ),
                },
                status_code=400,
            )
            return

        result = create_human_label_record(
            site_dir=site_dir,
            video_id=str(data.get("video_id", "")),
            start_second=data.get("start_second", 0),
            end_second=data.get("end_second", 0),
            human_label=str(data.get("human_label", "")),
            confidence=str(data.get("confidence", "")).strip() or None,
            note=str(data.get("note", "")),
            reviewer_id=str(data.get("reviewer_id", "")),
            site_id=str(data.get("site_id", "")),
            camera_id=str(data.get("camera_id", "")),
            labels_filename=str(data.get("labels_filename", "")).strip() or None,
            overwrite=_as_bool(data.get("overwrite"), default=False),
        )

        self._send_json(
            {
                "success": result.created,
                "message": result.message,
                "site_dir": str(result.site_dir) if result.created else None,
                "labels_path": str(result.labels_path) if result.created else None,
                "record": result.record,
            },
            status_code=200 if result.created else 400,
        )

    def _handle_run_validation(self) -> None:
        data = self._read_json_body()
        if data is None:
            return

        folder_name = str(data.get("folder_name", "")).strip()
        if not folder_name:
            self._send_json(
                {"success": False, "message": "Missing required field: folder_name."},
                status_code=400,
            )
            return

        site_dir = (self.sites_dir / folder_name).resolve()
        try:
            site_dir.relative_to(self.sites_dir.resolve())
        except ValueError:
            self._send_json(
                {
                    "success": False,
                    "message": (
                        "Invalid folder_name: site folder must stay inside the sites directory."
                    ),
                },
                status_code=400,
            )
            return

        try:
            report = run_site_validation(site_dir)
        except (OSError, ValueError) as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
            return

        self._send_json(
            {
                "success": True,
                "message": "Local validation completed.",
                "site_name": report.site_name,
                "report_path": report.output_path,
                "counts": {
                    "agree": report.agree_count,
                    "disagree": report.disagree_count,
                    "cannot_compare": report.cannot_compare_count,
                },
            },
            status_code=200,
        )

    def _handle_repair_manifest(self) -> None:
        data = self._read_json_body()
        if data is None:
            return
        folder_name = str(data.get("folder_name", "")).strip()
        if not folder_name:
            self._send_json(
                {"success": False, "message": "Missing required field: folder_name."},
                status_code=400,
            )
            return
        site_dir = (self.sites_dir / folder_name).resolve()
        try:
            site_dir.relative_to(self.sites_dir.resolve())
        except ValueError:
            self._send_json(
                {
                    "success": False,
                    "message": (
                        "Invalid folder_name: site folder must stay inside the sites directory."
                    ),
                },
                status_code=400,
            )
            return
        result = repair_manifest_from_local_videos(site_dir)
        self._send_json(
            {
                "success": not result.issues,
                "message": result.message,
                "manifest_path": str(result.manifest_path),
                "created_count": result.created_count,
                "preserved_count": result.preserved_count,
                "issues": result.issues,
            },
            status_code=200 if not result.issues else 400,
        )

    def _read_intake_request(self) -> tuple[dict[str, Any], Path | None] | None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" in content_type:
            return self._read_multipart_intake()
        data = self._read_json_body()
        if data is None:
            return None
        return data, None

    def _read_multipart_intake(self) -> tuple[dict[str, Any], Path | None] | None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error(400, "Missing request body")
            return None

        content_type = self.headers.get("Content-Type", "")
        preamble = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        message = BytesParser(policy=HTTP).parsebytes(preamble + self.rfile.read(content_length))
        fields: dict[str, Any] = {}
        temp_video: Path | None = None

        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            filename = part.get_filename()
            payload = part.get_payload(decode=True)
            if filename:
                suffix = Path(filename).suffix.lower()
                if suffix not in VIDEO_SUFFIXES:
                    self._send_json(
                        {
                            "success": False,
                            "message": (
                                f"Unsupported video type {suffix or '(none)'}. "
                                f"Use one of: {', '.join(sorted(VIDEO_SUFFIXES))}."
                            ),
                        },
                        status_code=400,
                    )
                    return None
                if not isinstance(payload, bytes) or not payload:
                    self._send_json(
                        {"success": False, "message": "Selected video file is empty."},
                        status_code=400,
                    )
                    return None
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                    handle.write(payload)
                    temp_video = Path(handle.name)
                if not str(fields.get("video_id", "")).strip():
                    fields["video_id"] = Path(filename).stem
                continue
            if isinstance(payload, bytes):
                fields[str(name)] = payload.decode("utf-8")
            elif payload is not None:
                fields[str(name)] = str(payload)

        if temp_video is None:
            self._send_json(
                {"success": False, "message": "Choose a local video file to copy into the site."},
                status_code=400,
            )
            return None
        return fields, temp_video

    def _read_json_body(self) -> dict[str, Any] | None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error(400, "Missing request body")
            return None

        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return None
        if not isinstance(data, dict):
            self.send_error(400, "Invalid JSON")
            return None
        return data

    def _send_json(self, payload: dict[str, Any], *, status_code: int) -> None:
        response_body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def _send_sites_json(self) -> None:
        statuses = discover_validation_site_statuses(self.sites_dir)
        payload = {
            "sites_dir": str(self.sites_dir),
            "sites": [status.to_dict() for status in statuses],
            "purpose_options": list(MANIFEST_PURPOSE_OPTIONS),
            "hard_case_type_options": list(HARD_CASE_TYPE_OPTIONS),
            "human_label_options": sorted(ALLOWED_HUMAN_LABELS),
            "confidence_options": sorted(ALLOWED_CONFIDENCE_LEVELS),
            "safety_note": (
                "This local UI stays on this computer. It does not upload videos, "
                "connect to cameras, send alerts, train ML, or publish warnings."
            ),
        }
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, *, content_type: str) -> None:
        safe_path = Path(unquote(str(path)))
        if not safe_path.is_file():
            self.send_error(404, "UI file not found")
            return
        body = safe_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _as_bool(value: object, *, default: bool = False) -> bool:
    """Parse a cautious boolean, defaulting to false for missing or unknown values."""

    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _find_site_config(site_dir: Path) -> Path:
    config_paths = sorted((site_dir / "configs").glob("*.json"))
    if not config_paths:
        raise SiteConfigError(f"Site config was not found under {site_dir / 'configs'}")
    return config_paths[0]


def _parse_reference_region(value: object) -> dict[str, object] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise SiteConfigError("reference_region must be valid JSON") from error
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise SiteConfigError("reference_region must be a JSON object")
    return {str(key): item for key, item in parsed.items()}

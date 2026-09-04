"""Run the local OpenFloodAI home UI."""

from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from openfloodai.validation import discover_validation_site_statuses, setup_validation_site


class OpenFloodAIHomeHandler(SimpleHTTPRequestHandler):
    """Serve the local UI and site-status JSON."""

    sites_dir: Path
    ui_path: Path

    def do_GET(self) -> None:
        """Serve site-status JSON or the static local UI."""

        if self.path == "/api/sites":
            self._send_sites_json()
            return
        if self.path in {"/", "/openfloodai-home-ui.html"}:
            self._send_file(self.ui_path, content_type="text/html; charset=utf-8")
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        """Handle site setup requests."""

        if self.path == "/api/setup-site":
            self._handle_setup_site()
            return
        self.send_error(404, "Not found")

    def log_message(self, format: str, *args: Any) -> None:
        """Keep local UI output quiet."""

    def _handle_setup_site(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error(400, "Missing request body")
            return

        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        result = setup_validation_site(
            sites_base_dir=self.sites_dir,
            folder_name=data.get("folder_name", ""),
            site_id=data.get("site_id", ""),
            camera_id=data.get("camera_id", ""),
            site_name=data.get("site_name", ""),
            public_location=data.get("public_location", ""),
            privacy_notes=data.get("privacy_notes", ""),
            overwrite=data.get("overwrite", False),
        )

        response_payload = {
            "success": result.created,
            "message": result.message,
            "site_dir": str(result.site_dir) if result.created else None,
            "config_path": str(result.config_path) if result.created else None,
        }
        
        status_code = 200 if result.created else 400
        response_body = json.dumps(response_payload).encode("utf-8")
        
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
            "safety_note": (
                "This local UI reads folder status only. It does not upload files, "
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


def main() -> None:
    """Start a local-only OpenFloodAI home UI server."""

    parser = argparse.ArgumentParser(description="Run the local OpenFloodAI home UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--sites-dir", default=Path("data/sites"), type=Path)
    parser.add_argument("--ui-path", default=Path("tools/openfloodai-home-ui.html"), type=Path)
    args = parser.parse_args()

    handler = OpenFloodAIHomeHandler
    handler.sites_dir = args.sites_dir
    handler.ui_path = args.ui_path

    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/openfloodai-home-ui.html"

    print("OpenFloodAI local home UI is running.")
    print(f"Open: {url}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Reusable HTTP handler and helpers for the local OpenFloodAI home UI."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import HTTP
from http.server import SimpleHTTPRequestHandler
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import cv2

from openfloodai.config import (
    SiteConfigError,
    delete_normal_waterline_guide,
    invalidate_normal_waterline_guide,
    load_site_config,
    write_normal_waterline_guide,
    write_normal_waterline_guides,
    write_reference_region,
)
from openfloodai.contracts import read_jsonl_records
from openfloodai.ingestion.image_video import create_image_test_video
from openfloodai.ingestion.live_camera import LiveCameraError, capture_live_clip
from openfloodai.ingestion.live_camera_schedule import read_schedule, write_schedule
from openfloodai.ingestion.river_bootstrap import preview_bootstrap_run, run_bootstrap
from openfloodai.ingestion.river_images import (
    RiverImageError,
    download_latest_timelapse,
    download_river_image_sequence,
    download_river_images,
    list_site_image_sequences,
    preview_river_image_sequence,
    resolve_downloaded_image,
    resolve_downloaded_video,
    resolve_sequence_image,
)
from openfloodai.ingestion.river_registry import RiverRegistryError, find_camera
from openfloodai.ingestion.usgs_gage_data import GageDataError, write_gauge_readings_summary
from openfloodai.review import (
    ALLOWED_CONFIDENCE_LEVELS,
    ALLOWED_HUMAN_LABELS,
    ALLOWED_TRISTATE_VALUES,
    ALLOWED_VISIBILITY_CONDITIONS,
    ReviewImageError,
    compute_failure_reason,
    create_human_label_record,
    encode_png,
    friendly_failure_reason,
    is_baseline_ready,
    is_normal_baseline_confirmed,
    render_pair_comparison_overlay,
    repair_manifest_from_local_videos,
)
from openfloodai.review.dataset_manifest import HARD_CASE_TYPE_OPTIONS, MANIFEST_PURPOSE_OPTIONS
from openfloodai.review.event_reviews import (
    EventReviewError,
    compute_evidence_key,
    list_event_reviews,
    set_event_review,
)
from openfloodai.review.river_tracker import build_river_tracker
from openfloodai.ui import review_workspace
from openfloodai.validation import (
    build_export_all,
    build_run_export,
    delete_all_sites,
    delete_site,
    discover_validation_site_statuses,
    intake_validation_video,
    run_site_validation,
    setup_validation_site,
)
from openfloodai.validation.image_sequence_runner import (
    ImageSequenceValidationError,
    list_image_sequence_runs,
    read_image_sequence_run_detail,
    resolve_image_sequence_run_image,
    resolve_run_config_snapshot,
    run_image_sequence_validation,
)
from openfloodai.validation.input_snapshot import read_input_snapshot
from openfloodai.validation.site_status import VIDEO_SUFFIXES

VIDEO_CONTENT_TYPES = {
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
}

_CONSOLE_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


class OpenFloodAIHomeHandler(SimpleHTTPRequestHandler):
    """Serve the local UI and site-status JSON."""

    sites_dir: Path
    ui_path: Path

    def do_GET(self) -> None:
        """Serve site-status JSON or the static local UI."""

        path = urlsplit(self.path).path
        if path.startswith("/console/"):
            self._send_console_file(path[len("/console/") :])
            return
        if review_workspace.handle_get(self, path):
            return
        if path == "/river-images.html":
            self._send_river_images_page()
            return
        if path == "/api/river-image":
            self._send_river_image()
            return
        if path == "/api/river-video":
            self._send_river_video()
            return
        if path == "/api/live-camera-schedule":
            self._send_live_camera_schedule()
            return
        if path in {"/api/review-images", "/api/review-image"}:
            self._send_review_images(single_image=path == "/api/review-image")
            return
        if path == "/api/validation-report":
            self._send_validation_report()
            return
        if path == "/api/video-duration":
            self._send_video_duration()
            return
        if path == "/api/site-video":
            self._send_site_video()
            return
        if path == "/api/sites":
            self._send_sites_json()
            return
        if path == "/api/export-run":
            self._send_export_run()
            return
        if path == "/api/export-all":
            self._send_export_all()
            return
        if path == "/api/site-config":
            self._send_site_config()
            return
        if path == "/api/site-manifest":
            self._send_site_manifest()
            return
        if path == "/api/run-detail":
            self._send_run_detail()
            return
        if path == "/api/site-image-sequences":
            self._send_site_image_sequences()
            return
        if path == "/api/image-sequence-image":
            self._send_image_sequence_image()
            return
        if path == "/api/image-sequence-comparison":
            self._send_image_sequence_comparison()
            return
        if path == "/api/image-sequence-runs":
            self._send_image_sequence_runs()
            return
        if path == "/api/image-sequence-run-detail":
            self._send_image_sequence_run_detail()
            return
        if path == "/api/image-sequence-run-image":
            self._send_image_sequence_run_image()
            return
        if path == "/site-details.html":
            self._send_site_details_page()
            return
        if path == "/river-tracker.html":
            self._send_river_tracker_page()
            return
        if path == "/api/river-tracker":
            self._send_river_tracker_json()
            return
        if path in {"/", "/openfloodai-home-ui.html"}:
            self._send_file(self.ui_path, content_type="text/html; charset=utf-8")
            return
        self.send_error(404, "Not found")

    def _send_video_duration(self) -> None:
        """Read duration metadata for a selected local video without serving its bytes."""

        query = parse_qs(urlsplit(self.path).query)
        folder = query.get("folder_name", [""])[0]
        video_id = query.get("video_id", [""])[0]
        try:
            capture = cv2.VideoCapture(str(self._resolve_site_video(folder, video_id)))
            try:
                fps = capture.get(cv2.CAP_PROP_FPS)
                frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
                duration = frames / fps if fps > 0 else 0
                if not capture.isOpened() or not math.isfinite(duration) or duration <= 0:
                    raise ValueError("Duration unavailable")
            finally:
                capture.release()
            self._send_json({"duration_seconds": duration}, status_code=200)
        except (OSError, ValueError, cv2.error):
            self._send_json(
                {"message": "Could not read the video duration. Enter the end time yourself."},
                status_code=400,
            )

    def _send_site_video(self) -> None:
        """Send one local site video to the browser so a user can draw the watched area.

        The bytes stay on this computer. Nothing is uploaded or published.
        """

        query = parse_qs(urlsplit(self.path).query)
        folder = query.get("folder_name", [""])[0]
        video_id = query.get("video_id", [""])[0]
        try:
            video_path = self._resolve_site_video(folder, video_id)
            size = video_path.stat().st_size
        except (OSError, ValueError):
            self.send_error(404, "Video not found")
            return

        start, end = _parse_byte_range(self.headers.get("Range"), size)
        with video_path.open("rb") as video_file:
            video_file.seek(start)
            body = video_file.read(end - start + 1)
        partial = (start, end) != (0, size - 1)
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", VIDEO_CONTENT_TYPES[video_path.suffix.lower()])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _resolve_site_video(self, folder: str, video_id: str) -> Path:
        """Find one video inside a site folder, refusing anything outside it."""

        site = (self.sites_dir / folder).resolve()
        if not folder or site.parent != self.sites_dir.resolve():
            raise ValueError("Invalid site")
        videos = site / "inputs" / "videos"
        matches = [
            path
            for path in videos.iterdir()
            if path.stem == video_id
            and path.suffix.lower() in VIDEO_SUFFIXES
            and path.is_file()
            and path.resolve().is_relative_to(site)
        ]
        if len(matches) != 1:
            raise ValueError("Video missing or ambiguous")
        return matches[0]

    def _send_validation_report(self) -> None:
        """Read a generated validation report inside the local sites directory."""

        query = parse_qs(urlsplit(self.path).query)
        try:
            candidate = Path(query.get("path", [""])[0]).resolve()
            relative = candidate.relative_to(self.sites_dir.resolve())
            if (
                len(relative.parts) < 3
                or relative.parts[1] != "outputs"
                or not candidate.match("validation-report*.md")
                or not candidate.is_file()
            ):
                raise ValueError("Not a validation report")
            self._send_json({"report": candidate.read_text(encoding="utf-8")}, status_code=200)
        except (OSError, ValueError):
            self._send_json({"message": "Validation report not found."}, status_code=404)

    def _resolve_site_dir(self, folder_name: str) -> Path:
        """Return a site folder inside the configured sites directory, or raise ValueError."""

        site_dir = (self.sites_dir / folder_name).resolve()
        if not folder_name or site_dir.parent != self.sites_dir.resolve():
            raise ValueError("Invalid folder_name")
        return site_dir

    def _send_site_config(self) -> None:
        """Read the current site config file for the details page's Config tab."""

        query = parse_qs(urlsplit(self.path).query)
        try:
            site_dir = self._resolve_site_dir(query.get("folder_name", [""])[0])
            config_path = _find_site_config(site_dir)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self._send_json({"config": config, "config_path": str(config_path)}, status_code=200)
        except (SiteConfigError, OSError, ValueError, json.JSONDecodeError):
            self._send_json({"message": "Site config not found."}, status_code=404)

    def _send_site_manifest(self) -> None:
        """Read manifest rows for the details page's Videos tab."""

        query = parse_qs(urlsplit(self.path).query)
        try:
            site_dir = self._resolve_site_dir(query.get("folder_name", [""])[0])
            manifest_path = site_dir / "manifest.jsonl"
            records = read_jsonl_records(manifest_path) if manifest_path.is_file() else []
            self._send_json({"records": records}, status_code=200)
        except (OSError, ValueError):
            self._send_json({"message": "Manifest not found."}, status_code=404)

    def _send_site_image_sequences(self) -> None:
        """List saved USGS image sequences for the details page's Image sequences tab."""

        query = parse_qs(urlsplit(self.path).query)
        try:
            site_dir = self._resolve_site_dir(query.get("folder_name", [""])[0])
            self._send_json({"sequences": list_site_image_sequences(site_dir)}, status_code=200)
        except (OSError, ValueError):
            self._send_json({"message": "Site not found."}, status_code=404)

    def _send_image_sequence_image(self) -> None:
        query = parse_qs(urlsplit(self.path).query)
        try:
            site_dir = self._resolve_site_dir(query.get("folder_name", [""])[0])
            path = resolve_sequence_image(
                site_dir,
                query.get("sequence_id", [""])[0],
                query.get("filename", [""])[0],
            )
            self._send_file(path, content_type="image/jpeg")
        except (OSError, ValueError, RiverImageError):
            self.send_error(404, "Image not found")

    def _send_image_sequence_comparison(self) -> None:
        """Render an on-demand baseline-vs-selected comparison, watched area boxed.

        Unlike a run's saved review images (fixed to that run's single
        biggest-change day), this builds the comparison for whichever two
        images the caller names, so a reviewer stepping through days or
        events sees the right pair every time, not just one fixed pair.

        Always renders using the CONFIG SNAPSHOT SAVED WITH `run_id`, never
        the site's current live config — otherwise editing the watched area
        after a run would silently change what an old run's comparison
        shows, disagreeing with the score that run actually computed.
        """

        query = parse_qs(urlsplit(self.path).query)
        try:
            site_dir = self._resolve_site_dir(query.get("folder_name", [""])[0])
            sequence_id = query.get("sequence_id", [""])[0]
            baseline_path = resolve_sequence_image(
                site_dir, sequence_id, query.get("baseline_filename", [""])[0]
            )
            selected_path = resolve_sequence_image(
                site_dir, sequence_id, query.get("filename", [""])[0]
            )
            config_snapshot = resolve_run_config_snapshot(
                site_dir, query.get("run_id", [""])[0], expected_sequence_id=sequence_id
            )
            baseline_frame = cv2.imread(str(baseline_path))
            selected_frame = cv2.imread(str(selected_path))
            if baseline_frame is None or selected_frame is None:
                raise RiverImageError("Could not read one of the images to compare.")
            overlay = render_pair_comparison_overlay(
                baseline_frame,
                selected_frame,
                reference_region=config_snapshot.get("reference_region"),
                normal_waterline_guides=config_snapshot.get("normal_waterline_guides"),
            )
            body = encode_png(overlay)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (
            OSError,
            ValueError,
            RiverImageError,
            SiteConfigError,
            ReviewImageError,
            ImageSequenceValidationError,
        ):
            self.send_error(404, "Comparison image not found")

    def _send_image_sequence_runs(self) -> None:
        """List saved image-sequence validation runs for one sequence."""

        query = parse_qs(urlsplit(self.path).query)
        try:
            site_dir = self._resolve_site_dir(query.get("folder_name", [""])[0])
            runs = list_image_sequence_runs(site_dir, query.get("sequence_id", [""])[0])
            self._send_json({"runs": runs}, status_code=200)
        except (OSError, ValueError):
            self._send_json({"message": "Site not found."}, status_code=404)

    def _send_image_sequence_run_detail(self) -> None:
        """Read one saved image-sequence validation run's summary, records, and report."""

        query = parse_qs(urlsplit(self.path).query)
        try:
            site_dir = self._resolve_site_dir(query.get("folder_name", [""])[0])
            detail = read_image_sequence_run_detail(site_dir, query.get("run_id", [""])[0])
            self._send_json(detail, status_code=200)
        except (OSError, ValueError, ImageSequenceValidationError):
            self._send_json({"message": "Run not found."}, status_code=404)

    def _send_image_sequence_run_image(self) -> None:
        query = parse_qs(urlsplit(self.path).query)
        try:
            site_dir = self._resolve_site_dir(query.get("folder_name", [""])[0])
            path = resolve_image_sequence_run_image(
                site_dir,
                query.get("run_id", [""])[0],
                query.get("filename", [""])[0],
            )
            self._send_file(path, content_type="image/png")
        except (OSError, ValueError, ImageSequenceValidationError):
            self.send_error(404, "Image not found")

    def _send_run_detail(self) -> None:
        """Read one run's saved report, scorecard, metadata, and input snapshot."""

        query = parse_qs(urlsplit(self.path).query)
        try:
            run_dir = Path(query.get("run_dir", [""])[0]).resolve()
            relative = run_dir.relative_to(self.sites_dir.resolve())
            if len(relative.parts) != 4 or relative.parts[1:3] != ("outputs", "runs"):
                raise ValueError("Not a run folder")
            if not run_dir.is_dir():
                raise ValueError("Run folder not found")
            payload: dict[str, Any] = {
                "run_metadata": _read_json_if_present(run_dir / "run-metadata.json"),
                "scorecard": _read_json_if_present(run_dir / "scorecard.json"),
                "report": _read_text_if_present(run_dir / "validation-report.md"),
            }
            try:
                payload["inputs"] = read_input_snapshot(run_dir)
            except (OSError, ValueError, json.JSONDecodeError):
                payload["inputs"] = None
            self._send_json(payload, status_code=200)
        except (OSError, ValueError):
            self._send_json({"message": "Run not found."}, status_code=404)

    def _send_site_details_page(self) -> None:
        source = self.ui_path.parent / "openfloodai-site-details.html"
        if source.is_file():
            self._send_file(source, content_type="text/html; charset=utf-8")
            return
        # Wheel and desktop builds carry the page as a package resource.
        page = resources.files("openfloodai.ui") / "static" / "openfloodai-site-details.html"
        if not page.is_file():
            self.send_error(404, "Site details page not found")
            return
        body = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_river_tracker_page(self) -> None:
        source = self.ui_path.parent / "openfloodai-river-tracker.html"
        if source.is_file():
            self._send_file(source, content_type="text/html; charset=utf-8")
            return
        # Wheel and desktop builds carry the page as a package resource.
        page = resources.files("openfloodai.ui") / "static" / "openfloodai-river-tracker.html"
        if not page.is_file():
            self.send_error(404, "River tracker page not found")
            return
        body = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reference_dir(self) -> Path:
        return self.sites_dir.resolve().parent / "reference"

    def _send_river_tracker_json(self) -> None:
        query = parse_qs(urlsplit(self.path).query)
        river_id = (query.get("river") or [""])[0].strip()
        if not river_id:
            self._send_json({"message": "Missing required query parameter: river"}, status_code=400)
            return
        try:
            registry, rows = build_river_tracker(
                river_id, reference_dir=self._reference_dir(), sites_base_dir=self.sites_dir
            )
        except RiverRegistryError as error:
            self._send_json({"message": str(error)}, status_code=404)
            return
        self._send_json(
            {
                "river_id": registry.river_id,
                "river_display_name": registry.display_name,
                "sites": [row.to_dict() for row in rows],
            },
            status_code=200,
        )

    def _send_review_images(self, *, single_image: bool) -> None:
        """Expose only generated review images inside the configured local sites."""

        query = parse_qs(urlsplit(self.path).query)
        requested = query.get("path", [""])[0]
        try:
            candidate = Path(requested).resolve()
            relative = candidate.relative_to(self.sites_dir.resolve())
            parts = relative.parts
            # Support legacy evidence and per-run evidence, never source media.
            if len(parts) >= 3 and parts[1:3] == ("outputs", "review-images"):
                root_length = 3
            elif len(parts) >= 4 and parts[1:4] == ("outputs", "smoke-test", "review-images"):
                root_length = 4
            elif (
                len(parts) >= 5
                and parts[1:3] == ("outputs", "runs")
                and parts[4] == "review-images"
            ):
                root_length = 5
            else:
                raise ValueError("Not a review image path")
            evidence_root = self.sites_dir.resolve().joinpath(*parts[:root_length])
            content_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
            if single_image:
                if not candidate.is_file() or candidate.suffix.lower() not in content_types:
                    raise ValueError("Not a supported image")
                body = candidate.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_types[candidate.suffix.lower()])
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            if candidate != evidence_root or not candidate.is_dir():
                raise ValueError("Review image folder not found")
            images = []
            for image in sorted(candidate.rglob("*")):
                if (
                    image.is_file()
                    and image.suffix.lower() in content_types
                    and image.resolve().is_relative_to(evidence_root)
                ):
                    images.append(
                        {
                            "name": str(image.relative_to(candidate)),
                            "url": "/api/review-image?" + urlencode({"path": str(image.resolve())}),
                        }
                    )
            self._send_json({"images": images}, status_code=200)
        except (OSError, ValueError):
            self.send_error(404, "Review images not found")

    def do_POST(self) -> None:
        """Handle site setup and video intake requests."""

        if review_workspace.handle_post(self, self.path):
            return
        if self.path == "/api/download-river-images":
            self._handle_download_river_images()
            return
        if self.path == "/api/download-river-timelapse":
            self._handle_download_river_images(timelapse=True)
            return
        if self.path == "/api/create-river-test-video":
            self._handle_download_river_images(create_video=True)
            return
        if self.path == "/api/download-live-camera-clip":
            self._handle_download_live_camera_clip()
            return
        if self.path == "/api/set-live-camera-schedule":
            self._handle_set_live_camera_schedule()
            return
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
        if self.path == "/api/set-watched-area":
            self._handle_set_watched_area()
            return
        if self.path == "/api/set-normal-waterline-guide":
            self._handle_set_normal_waterline_guide()
            return
        if self.path == "/api/invalidate-normal-waterline-guide":
            self._handle_invalidate_normal_waterline_guide()
            return
        if self.path == "/api/set-normal-waterline-guides":
            self._handle_set_normal_waterline_guides()
            return
        if self.path == "/api/delete-normal-waterline-guide":
            self._handle_delete_normal_waterline_guide()
            return
        if self.path == "/api/delete-site":
            self._handle_delete_site()
            return
        if self.path == "/api/delete-all-sites":
            self._handle_delete_all_sites()
            return
        if self.path == "/api/preview-image-sequence":
            self._handle_preview_image_sequence()
            return
        if self.path == "/api/download-image-sequence":
            self._handle_download_image_sequence()
            return
        if self.path == "/api/run-image-sequence-validation":
            self._handle_run_image_sequence_validation()
            return
        if self.path == "/api/set-image-sequence-event-review":
            self._handle_set_image_sequence_event_review()
            return
        if self.path == "/api/bootstrap-river-sites":
            self._handle_bootstrap_river_sites()
            return
        self.send_error(404, "Not found")

    def log_message(self, format: str, *args: Any) -> None:
        """Keep local UI output quiet."""

    def _send_river_images_page(self) -> None:
        source = self.ui_path.parent / "openfloodai-river-images.html"
        if source.is_file():
            self._send_file(source, content_type="text/html; charset=utf-8")
            return
        # Wheel and desktop builds carry the page as a package resource.
        page = resources.files("openfloodai.ui") / "static" / "openfloodai-river-images.html"
        if not page.is_file():
            self.send_error(404, "River image page not found")
            return
        body = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject_untrusted_json_post(self) -> dict[str, Any] | None:
        """Guard a small local-only JSON POST; send an error response and return None if rejected.

        Shared by every handler that may trigger outbound network requests or
        background-job changes, so only the explicit JSON form action (never a
        plain cross-origin form submission, which cannot set this content type)
        can initiate them.
        """

        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            self._send_json({"message": "Open this form from the local Home UI."}, status_code=403)
            return None
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= 4096 or self.headers.get_content_type() != "application/json":
            self._send_json({"message": "Send a small JSON request."}, status_code=400)
            return None
        return self._read_json_body()

    def _handle_download_river_images(
        self, *, timelapse: bool = False, create_video: bool = False
    ) -> None:
        data = self._reject_untrusted_json_post()
        if data is None:
            return
        try:
            if create_video:
                payload = create_image_test_video(
                    root=self._live_camera_root(),
                    source_batch_id=str(data.get("batch_id", "")),
                )
                self._send_json(payload, status_code=200)
                return
            if timelapse:
                payload = download_latest_timelapse(
                    camera_url=str(data.get("camera_url", "")),
                    output_root=self._live_camera_root(),
                )
                self._send_json(payload, status_code=200)
                return
            result = download_river_images(
                camera_url=str(data.get("camera_url", "")),
                local_hour=str(data.get("local_hour", "")),
                timezone_name=str(data.get("timezone", "")),
                output_root=self._live_camera_root(),
            )
            # A completed batch may include missing/failed slots. Return all four outcomes.
            self._send_json(result.to_dict(), status_code=200)
        except ValueError as error:
            self._send_json({"message": str(error)}, status_code=400)
        except OSError:
            self._send_json(
                {"message": "Could not save the download. Check local disk space and permissions."},
                status_code=500,
            )

    def _handle_preview_image_sequence(self) -> None:
        """Report how many images a USGS image-sequence request would fetch, before downloading."""

        data = self._reject_untrusted_json_post()
        if data is None:
            return
        try:
            preview = preview_river_image_sequence(
                camera_url=str(data.get("camera_url", "")),
                start_date=str(data.get("start_date", "")),
                end_date=str(data.get("end_date", "")),
                timezone_name=str(data.get("timezone", "")),
                sampling_mode=str(data.get("sampling_mode", "")),
            )
            self._send_json({"success": True} | preview.to_dict(), status_code=200)
        except RiverImageError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)

    def _write_gage_data_if_camera_registered(
        self, sequence_dir: Path, camera_id: str, start_date: str, end_date: str
    ) -> bool | None:
        """Best-effort gage-data enrichment for a freshly downloaded image sequence.

        A site's camera_id only maps to a USGS gage when that camera is
        registered in a river registry (River Camera Tracker's bootstrap
        source of truth) -- a site created by hand through the console has
        no gage id anywhere in its own config. Returns None (not found or
        the fetch failed) rather than raising: gage enrichment must never
        block or fail the image download itself.
        """

        camera = find_camera(camera_id, self._reference_dir())
        if camera is None:
            return None
        try:
            manifest_records = read_jsonl_records(sequence_dir / "sequence-manifest.jsonl")
        except ValueError:
            return None
        try:
            summary = write_gauge_readings_summary(
                sequence_dir,
                nwis_site_id=camera.nwis_id,
                start_date=start_date,
                end_date=end_date,
                gage_relationship=camera.gage_relationship,
                gage_relationship_note=camera.gage_relationship_note,
                manifest_records=manifest_records,
            )
            return summary.available
        except GageDataError:
            return None

    def _handle_download_image_sequence(self) -> None:
        """Download a sampled, date-ranged USGS image sequence into a site folder."""

        data = self._reject_untrusted_json_post()
        if data is None:
            return
        try:
            site_dir = self._resolve_site_dir(str(data.get("folder_name", "")).strip())
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
            site_config = load_site_config(_find_site_config(site_dir))
        except SiteConfigError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
            return
        try:
            result = download_river_image_sequence(
                camera_url=str(data.get("camera_url", "")),
                start_date=str(data.get("start_date", "")),
                end_date=str(data.get("end_date", "")),
                timezone_name=str(data.get("timezone", "")),
                sampling_mode=str(data.get("sampling_mode", "")),
                site_id=site_config.site_id,
                site_dir=site_dir,
                overwrite=bool(data.get("overwrite", False)),
            )
            payload = result.to_dict()
            payload["gage_available"] = (
                self._write_gage_data_if_camera_registered(
                    result.directory,
                    site_config.camera_id,
                    str(data.get("start_date", "")),
                    str(data.get("end_date", "")),
                )
                if _as_bool(data.get("fetch_gage_data"), default=True)
                else None
            )
            self._send_json(payload, status_code=200)
        except RiverImageError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
        except OSError:
            self._send_json(
                {"message": "Could not save the download. Check local disk space and permissions."},
                status_code=500,
            )

    def _handle_run_image_sequence_validation(self) -> None:
        """Run local validation against one saved image sequence in a site folder.

        Separate from `_handle_run_validation` (the video flow): its own
        request shape, its own output folder
        (`outputs/image-sequence-runs/`), and it never touches anything the
        video flow reads.
        """

        data = self._read_json_body()
        if data is None:
            return
        try:
            site_dir = self._resolve_site_dir(str(data.get("folder_name", "")).strip())
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
        sequence_id = str(data.get("sequence_id", "")).strip()
        baseline_filename = str(data.get("baseline_filename", "")).strip() or None
        try:
            report = run_image_sequence_validation(
                site_dir, sequence_id, baseline_filename=baseline_filename
            )
        except (ImageSequenceValidationError, SiteConfigError) as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
            return
        self._send_json(
            {
                "success": True,
                "message": "Image-sequence validation completed.",
                "run_id": report.run_id,
                "sequence_id": report.sequence_id,
                "baseline_filename": report.baseline_filename,
                "counts": {
                    "possible_water_level_change": report.possible_change_count,
                    "no_water_level_change": report.no_change_count,
                    "cannot_judge_water_level": report.cannot_judge_count,
                    "camera_or_image_problem": report.camera_or_image_problem_count,
                },
            },
            status_code=200,
        )

    def _handle_set_image_sequence_event_review(self) -> None:
        """Mark (or clear) a review status for one machine-detected event.

        Stored per sequence, not per run, so a mark survives re-running
        validation on the same downloaded images. Every review is stamped
        with an evidence fingerprint (baseline image + watched area) taken
        from the run's OWN saved summary — never from the request body —
        so a stale or forged client value can't make a review outlive the
        evidence it was actually made against.
        """

        data = self._read_json_body()
        if data is None:
            return
        try:
            site_dir = self._resolve_site_dir(str(data.get("folder_name", "")).strip())
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
        sequences_root = (site_dir / "inputs" / "image-sequences").resolve()
        sequence_dir = (sequences_root / str(data.get("sequence_id", "")).strip()).resolve()
        try:
            sequence_dir.relative_to(sequences_root)
        except ValueError:
            self._send_json({"success": False, "message": "Invalid sequence_id."}, status_code=400)
            return
        requested_sequence_id = str(data.get("sequence_id", "")).strip()
        try:
            detail = read_image_sequence_run_detail(site_dir, str(data.get("run_id", "")).strip())
        except (OSError, ValueError, ImageSequenceValidationError):
            self._send_json({"success": False, "message": "Run not found."}, status_code=404)
            return
        summary = detail["summary"] if isinstance(detail["summary"], dict) else {}
        if summary.get("sequence_id") != requested_sequence_id:
            # The run_id and sequence_id are two independent client-supplied
            # values; without this check a request could store a review
            # under one sequence while stamping it with a different run's
            # (wrong) evidence fingerprint.
            self._send_json(
                {"success": False, "message": "run_id does not belong to sequence_id."},
                status_code=400,
            )
            return
        evidence_key = compute_evidence_key(
            summary.get("baseline_filename"), summary.get("watched_area_used")
        )
        event_key = str(data.get("event_key", "")).strip()
        raw_status = data.get("status")
        status = str(raw_status).strip() if isinstance(raw_status, str) and raw_status else None
        try:
            set_event_review(
                sequence_dir, event_key=event_key, status=status, evidence_key=evidence_key
            )
        except EventReviewError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
            return
        self._send_json(
            {
                "success": True,
                "event_reviews": list_event_reviews(sequence_dir, evidence_key=evidence_key),
            },
            status_code=200,
        )

    def _handle_bootstrap_river_sites(self) -> None:
        """Run (or preview) a registry-driven camera bootstrap, from the tracker page's form.

        Mirrors scripts/bootstrap_river_sites.py exactly, so the form is a
        thin front-end for the same CLI behavior, not a separate code path.
        A real (non-preview) run can take a while, since it downloads
        images and gage data; there is no request timeout here for that
        reason.
        """

        data = self._reject_untrusted_json_post()
        if data is None:
            return
        river_id = str(data.get("river", "")).strip()
        start_date = str(data.get("start_date", "")).strip()
        end_date = str(data.get("end_date", "")).strip()
        sampling_mode = str(data.get("sampling_mode") or "one_daylight_image_per_day").strip()
        raw_cameras = data.get("cameras")
        camera_ids = (
            [str(camera).strip() for camera in raw_cameras if str(camera).strip()]
            if isinstance(raw_cameras, list)
            else []
        )
        preview = bool(data.get("preview"))
        replace_sequence = bool(data.get("replace_sequence"))

        try:
            if preview:
                result = preview_bootstrap_run(
                    reference_dir=self._reference_dir(),
                    sites_base_dir=self.sites_dir,
                    river_id=river_id,
                    camera_ids=camera_ids,
                    start_date=start_date,
                    end_date=end_date,
                    sampling_mode=sampling_mode,
                )
                self._send_json({"success": True, "preview": result.to_dict()}, status_code=200)
                return
            outcomes = run_bootstrap(
                reference_dir=self._reference_dir(),
                sites_base_dir=self.sites_dir,
                river_id=river_id,
                camera_ids=camera_ids,
                start_date=start_date,
                end_date=end_date,
                sampling_mode=sampling_mode,
                replace_sequence=replace_sequence,
            )
            self._send_json(
                {"success": True, "outcomes": [outcome.to_dict() for outcome in outcomes]},
                status_code=200,
            )
        except (RiverRegistryError, RiverImageError, ValueError) as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)

    def _send_river_image(self) -> None:
        query = parse_qs(urlsplit(self.path).query)
        try:
            path = resolve_downloaded_image(
                self._live_camera_root(),
                query.get("batch_id", [""])[0],
                query.get("filename", [""])[0],
            )
            self._send_file(path, content_type="image/jpeg")
        except (OSError, ValueError, KeyError, TypeError):
            self.send_error(404, "Downloaded image not found")

    def _send_river_video(self) -> None:
        query = parse_qs(urlsplit(self.path).query)
        try:
            path = resolve_downloaded_video(
                self._live_camera_root(),
                query.get("batch_id", [""])[0],
                query.get("filename", [""])[0],
            )
            size = path.stat().st_size
            video = path.open("rb")
        except (OSError, ValueError, KeyError, TypeError):
            self.send_error(404, "Downloaded video not found")
            return
        with video:
            start, end = _parse_byte_range(self.headers.get("Range"), size)
            partial = (start, end) != (0, size - 1)
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if query.get("download") == ["1"]:
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.end_headers()
            video.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                block = video.read(min(64 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def _live_camera_root(self) -> Path:
        return self.sites_dir.resolve().parent / "river-images"

    def _handle_download_live_camera_clip(self) -> None:
        data = self._reject_untrusted_json_post()
        if data is None:
            return
        try:
            payload = capture_live_clip(
                stream_url=str(data.get("stream_url", "")),
                output_root=self._live_camera_root(),
                duration_seconds=data.get("duration_seconds", ""),
            )
            self._send_json(payload, status_code=200)
        except LiveCameraError as error:
            self._send_json({"message": str(error)}, status_code=400)
        except OSError:
            self._send_json(
                {"message": "Could not save the clip. Check local disk space and permissions."},
                status_code=500,
            )

    def _handle_set_live_camera_schedule(self) -> None:
        data = self._reject_untrusted_json_post()
        if data is None:
            return
        try:
            schedule = write_schedule(self._live_camera_root(), data)
            self._send_json(schedule, status_code=200)
        except LiveCameraError as error:
            self._send_json({"message": str(error)}, status_code=400)
        except OSError:
            self._send_json(
                {"message": "Could not save the schedule. Check local disk space and permissions."},
                status_code=500,
            )

    def _send_live_camera_schedule(self) -> None:
        self._send_json(read_schedule(self._live_camera_root()), status_code=200)

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

    def _handle_set_watched_area(self) -> None:
        """Save only the watched area for a video that is already in the site folder."""

        data = self._read_json_body()
        if data is None:
            return

        folder_name = str(data.get("folder_name", "")).strip()
        site_dir = (self.sites_dir / folder_name).resolve()
        if not folder_name or site_dir.parent != self.sites_dir.resolve():
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

        video_id = str(data.get("video_id", "")).strip()
        sequence_id = str(data.get("sequence_id", "")).strip()
        image_filename = str(data.get("image_filename", "")).strip()
        if sequence_id or image_filename:
            try:
                resolve_sequence_image(site_dir, sequence_id, image_filename)
            except (OSError, RiverImageError):
                self._send_json(
                    {
                        "success": False,
                        "message": (
                            "Choose an existing saved image in this site before saving "
                            "the watched area."
                        ),
                    },
                    status_code=400,
                )
                return
        else:
            try:
                self._resolve_site_video(folder_name, video_id)
            except ValueError:
                self._send_json(
                    {
                        "success": False,
                        "message": (
                            "Choose an existing video in this site before saving the watched area."
                        ),
                    },
                    status_code=400,
                )
                return

        try:
            reference_region = _parse_reference_region(data.get("reference_region"))
            if reference_region is None:
                raise SiteConfigError("Draw the watched area on the video first.")
            config_path = _find_site_config(site_dir)
            write_reference_region(config_path, reference_region)
        except SiteConfigError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
            return

        self._send_json(
            {
                "success": True,
                "message": "Watched area saved. This site can run validation now.",
                "config_path": str(config_path),
            },
            status_code=200,
        )

    def _resolve_normal_waterline_guide_source(
        self, folder_name: str, site_dir: Path, data: dict[str, Any]
    ) -> dict[str, object] | None:
        """Validate a guide's video-or-image source, sending an error response if invalid.

        Returns the source fields to merge into the guide payload, or ``None``
        after already sending an error response (the caller should just return).
        """

        sequence_id = str(data.get("sequence_id", "")).strip()
        image_filename = str(data.get("image_filename", "")).strip()
        if sequence_id or image_filename:
            try:
                resolve_sequence_image(site_dir, sequence_id, image_filename)
            except (OSError, RiverImageError):
                self._send_json(
                    {
                        "success": False,
                        "message": (
                            "Choose an existing saved image in this site before "
                            "saving a waterline guide."
                        ),
                    },
                    status_code=400,
                )
                return None
            return {
                "video_id": "",
                "video_time_seconds": 0,
                "image_sequence_id": sequence_id,
                "image_filename": image_filename,
            }

        video_id = str(data.get("video_id", "")).strip()
        try:
            self._resolve_site_video(folder_name, video_id)
        except ValueError:
            self._send_json(
                {
                    "success": False,
                    "message": (
                        "Choose an existing video in this site before saving a waterline guide."
                    ),
                },
                status_code=400,
            )
            return None
        return {
            "video_id": video_id,
            "video_time_seconds": data.get("video_time_seconds"),
            "image_sequence_id": "",
            "image_filename": "",
        }

    def _handle_set_normal_waterline_guide(self) -> None:
        """Save a draft or confirmed normal-waterline guide inside a site's watched area."""

        data = self._read_json_body()
        if data is None:
            return

        folder_name = str(data.get("folder_name", "")).strip()
        site_dir = (self.sites_dir / folder_name).resolve()
        if not folder_name or site_dir.parent != self.sites_dir.resolve():
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

        source = self._resolve_normal_waterline_guide_source(folder_name, site_dir, data)
        if source is None:
            return

        try:
            config_path = _find_site_config(site_dir)
            site_config = load_site_config(config_path)
            payload = {
                "id": str(data.get("id", "")).strip(),
                "label": str(data.get("label", "")).strip(),
                "points": _parse_waterline_points(data.get("points")),
                "status": str(data.get("status", "")).strip(),
                **source,
                "site_id": site_config.site_id,
                "camera_id": site_config.camera_id,
                "normal_condition": _as_bool(data.get("normal_condition"), default=False),
                "notes": str(data.get("notes", "")).strip(),
            }
            guide = write_normal_waterline_guide(config_path, payload)
        except SiteConfigError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
            return

        self._send_json(
            {
                "success": True,
                "message": (
                    "Normal waterline guide confirmed."
                    if guide.status == "confirmed"
                    else "Normal waterline guide saved as a draft."
                ),
                "config_path": str(config_path),
            },
            status_code=200,
        )

    def _handle_set_normal_waterline_guides(self) -> None:
        """Save every normal-waterline guide for one video in a single request."""

        data = self._read_json_body()
        if data is None:
            return

        folder_name = str(data.get("folder_name", "")).strip()
        site_dir = (self.sites_dir / folder_name).resolve()
        if not folder_name or site_dir.parent != self.sites_dir.resolve():
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

        source = self._resolve_normal_waterline_guide_source(folder_name, site_dir, data)
        if source is None:
            return

        raw_guides = data.get("guides")
        if not isinstance(raw_guides, list) or not raw_guides:
            self._send_json(
                {"success": False, "message": "At least one guide is required."},
                status_code=400,
            )
            return
        if not all(isinstance(entry, dict) for entry in raw_guides):
            self._send_json(
                {"success": False, "message": "Each guide must be a JSON object."},
                status_code=400,
            )
            return

        try:
            config_path = _find_site_config(site_dir)
            site_config = load_site_config(config_path)
            payloads = [
                {
                    "id": str(entry.get("id", "")).strip(),
                    "label": str(entry.get("label", "")).strip(),
                    "points": _parse_waterline_points(entry.get("points")),
                    "status": str(entry.get("status", "")).strip(),
                    "video_id": source["video_id"],
                    "video_time_seconds": (
                        0 if source["image_filename"] else entry.get("video_time_seconds")
                    ),
                    "image_sequence_id": source["image_sequence_id"],
                    "image_filename": source["image_filename"],
                    "site_id": site_config.site_id,
                    "camera_id": site_config.camera_id,
                    "normal_condition": _as_bool(entry.get("normal_condition"), default=False),
                    "notes": str(entry.get("notes", "")).strip(),
                    "invalidation_reason": (
                        str(entry.get("invalidation_reason", "")).strip() or None
                    ),
                }
                for entry in raw_guides
            ]
            guides = write_normal_waterline_guides(config_path, payloads)
        except SiteConfigError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
            return

        self._send_json(
            {
                "success": True,
                "message": f"Saved {len(guides)} normal waterline guide(s).",
                "config_path": str(config_path),
            },
            status_code=200,
        )

    def _handle_delete_normal_waterline_guide(self) -> None:
        """Permanently remove one normal-waterline guide from a site's config."""

        data = self._read_json_body()
        if data is None:
            return

        folder_name = str(data.get("folder_name", "")).strip()
        site_dir = (self.sites_dir / folder_name).resolve()
        if not folder_name or site_dir.parent != self.sites_dir.resolve():
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
            config_path = _find_site_config(site_dir)
            delete_normal_waterline_guide(config_path, str(data.get("guide_id", "")).strip())
        except SiteConfigError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
            return

        self._send_json(
            {
                "success": True,
                "message": "Normal waterline guide deleted.",
                "config_path": str(config_path),
            },
            status_code=200,
        )

    def _handle_invalidate_normal_waterline_guide(self) -> None:
        """Mark one of a site's normal-waterline guides as invalid."""

        data = self._read_json_body()
        if data is None:
            return

        folder_name = str(data.get("folder_name", "")).strip()
        site_dir = (self.sites_dir / folder_name).resolve()
        if not folder_name or site_dir.parent != self.sites_dir.resolve():
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
            config_path = _find_site_config(site_dir)
            invalidated = invalidate_normal_waterline_guide(
                config_path,
                str(data.get("guide_id", "")).strip(),
                str(data.get("invalidation_reason", "")).strip(),
                str(data.get("notes", "")).strip() or None,
            )
        except SiteConfigError as error:
            self._send_json({"success": False, "message": str(error)}, status_code=400)
            return

        self._send_json(
            {
                "success": True,
                "message": f"Guide marked invalid: {invalidated.invalidation_reason}.",
                "config_path": str(config_path),
            },
            status_code=200,
        )

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
            riverbank_visible=str(data.get("riverbank_visible", "")).strip() or None,
            stable_marker_visible=str(data.get("stable_marker_visible", "")).strip() or None,
            water_boundary_visible=str(data.get("water_boundary_visible", "")).strip() or None,
            camera_stable=str(data.get("camera_stable", "")).strip() or None,
            visibility_condition=str(data.get("visibility_condition", "")).strip() or None,
            labels_filename=str(data.get("labels_filename", "")).strip() or None,
            overwrite=_as_bool(data.get("overwrite"), default=False),
        )

        quality = None
        if result.created and result.record is not None:
            normal_waterline_guides = _read_normal_waterline_guides_list(site_dir)
            reason = compute_failure_reason(result.record, normal_waterline_guides)
            quality = {
                "normal_baseline_confirmed": is_normal_baseline_confirmed(normal_waterline_guides),
                "baseline_ready": is_baseline_ready(result.record, normal_waterline_guides),
                "failure_reason": reason,
                "failure_reason_text": friendly_failure_reason(reason),
            }

        self._send_json(
            {
                "success": result.created,
                "message": result.message,
                "site_dir": str(result.site_dir) if result.created else None,
                "labels_path": str(result.labels_path) if result.created else None,
                "record": result.record,
                "quality": quality,
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

    def _send_export_run(self) -> None:
        query = parse_qs(urlsplit(self.path).query)
        folder_name = query.get("folder_name", [""])[0].strip()
        run_id = query.get("run_id", [""])[0].strip()
        include_raw_video = _as_bool(query.get("include_raw_video", [""])[0], default=False)
        if not folder_name or not run_id:
            self._send_json(
                {"success": False, "message": "Missing required field: folder_name and run_id."},
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

        with tempfile.TemporaryDirectory(prefix="openfloodai-export-run-") as staging:
            result = build_run_export(
                site_dir, run_id, Path(staging), include_raw_video=include_raw_video
            )
            if not result.created:
                self._send_json({"success": False, "message": result.message}, status_code=400)
                return
            self._send_zip_download(result.export_dir, download_name=f"{run_id}.zip")

    def _send_export_all(self) -> None:
        query = parse_qs(urlsplit(self.path).query)
        include_raw_video = _as_bool(query.get("include_raw_video", [""])[0], default=False)

        with tempfile.TemporaryDirectory(prefix="openfloodai-export-all-") as staging:
            bundle_dir = Path(staging) / "openfloodai-export-all"
            result = build_export_all(
                self.sites_dir, bundle_dir, include_raw_video=include_raw_video
            )
            if not result.created:
                self._send_json({"success": False, "message": result.message}, status_code=400)
                return
            timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
            self._send_zip_download(
                result.export_dir, download_name=f"openfloodai-export-all_{timestamp}.zip"
            )

    def _send_zip_download(self, source_dir: Path, *, download_name: str) -> None:
        with tempfile.TemporaryDirectory(prefix="openfloodai-zip-") as archive_scratch:
            archive_base = Path(archive_scratch) / "download"
            shutil.make_archive(
                str(archive_base), "zip", root_dir=source_dir.parent, base_dir=source_dir.name
            )
            body = Path(f"{archive_base}.zip").read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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

    def _handle_delete_site(self) -> None:
        data = self._read_json_body()
        if data is None:
            return
        folder_name = str(data.get("folder_name", "")).strip()
        result = delete_site(self.sites_dir.resolve(), folder_name)
        self._send_json(
            {"success": result.deleted, "message": result.message},
            status_code=200 if result.deleted else 400,
        )

    def _handle_delete_all_sites(self) -> None:
        result = delete_all_sites(self.sites_dir.resolve())
        self._send_json(
            {
                "success": result.deleted,
                "message": result.message,
                "deleted_site_names": result.deleted_site_names,
            },
            status_code=200 if result.deleted else 400,
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
            "tristate_options": sorted(ALLOWED_TRISTATE_VALUES),
            "visibility_condition_options": sorted(ALLOWED_VISIBILITY_CONDITIONS),
            "safety_note": (
                "This local UI stays on this computer. It does not upload videos, "
                "send alerts, train ML, or publish warnings. The River Images and Video page can "
                "download public USGS archive images and latest time-lapse videos on request, "
                "and can save clips from a live camera stream you provide, either on request or "
                "on a background schedule you turn on there."
            ),
        }
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_console_file(self, relative: str) -> None:
        """Serve only console HTML/CSS/JS from source or packaged resources."""
        name = unquote(relative) or "dashboard.html"
        if (
            "/" in name
            or "\\" in name
            or "%" in name
            or Path(name).suffix.lower() not in _CONSOLE_CONTENT_TYPES
        ):
            self.send_error(404, "Not found")
            return
        console_root = (self.ui_path.parent / "console").resolve()
        candidate = console_root / name
        try:
            if console_root.is_dir():
                if candidate.is_symlink() or not candidate.is_file():
                    self.send_error(404, "Not found")
                    return
                body = candidate.read_bytes()
            else:
                body = (
                    resources.files("openfloodai.ui") / "static" / "console" / name
                ).read_bytes()
        except (OSError, ValueError):
            self.send_error(404, "Not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", _CONSOLE_CONTENT_TYPES[Path(name).suffix.lower()])
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


def _parse_byte_range(header: str | None, size: int) -> tuple[int, int]:
    """Read a simple single byte range, falling back to the whole file."""

    whole_file = (0, max(0, size - 1))
    if not header or not header.startswith("bytes=") or "," in header:
        return whole_file
    first, _, last = header[len("bytes=") :].partition("-")
    try:
        if not first:
            length = int(last)
            return (max(0, size - length), size - 1) if length > 0 else whole_file
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return whole_file
    end = min(end, size - 1)
    if start > end or start < 0:
        return whole_file
    return start, end


def _find_site_config(site_dir: Path) -> Path:
    config_paths = sorted((site_dir / "configs").glob("*.json"))
    if not config_paths:
        raise SiteConfigError(f"Site config was not found under {site_dir / 'configs'}")
    return config_paths[0]


def _read_json_if_present(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _read_text_if_present(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _read_normal_waterline_guides_list(site_dir: Path) -> list[dict[str, Any]]:
    """Return the site's normal_waterline_guides list, if any, for quality checks."""

    try:
        config_path = _find_site_config(site_dir)
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (SiteConfigError, OSError, json.JSONDecodeError):
        return []
    if not isinstance(config, dict):
        return []
    guides = config.get("normal_waterline_guides")
    if not isinstance(guides, list):
        return []
    return [guide for guide in guides if isinstance(guide, dict)]


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


def _parse_waterline_points(value: object) -> list[dict[str, object]]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise SiteConfigError("points must be valid JSON") from error
    else:
        parsed = value
    if not isinstance(parsed, list):
        raise SiteConfigError("points must be a JSON list")
    points: list[dict[str, object]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            raise SiteConfigError("Each waterline point must be a JSON object")
        points.append({str(key): item for key, item in entry.items()})
    return points

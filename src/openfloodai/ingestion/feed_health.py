"""Camera/feed health records for local video inputs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import cv2

CameraHealthRecord = dict[str, object]


class FeedHealthError(ValueError):
    """Raised when a feed health check cannot be requested safely."""


def check_video_file_health(
    video_path: Path,
    site_id: str,
    camera_id: str,
    *,
    timestamp: datetime | None = None,
) -> CameraHealthRecord:
    """Return a camera/feed health record for a local video file."""

    if not site_id:
        raise FeedHealthError("site_id must be non-empty")
    if not camera_id:
        raise FeedHealthError("camera_id must be non-empty")

    record_timestamp = _normalize_timestamp(timestamp)
    resolved_path = Path(video_path)

    if not resolved_path.is_file():
        return _build_health_record(
            site_id=site_id,
            camera_id=camera_id,
            timestamp=record_timestamp,
            input_quality_state="UNKNOWN",
            is_usable=False,
            reason_codes=["INPUT_UNKNOWN", "STREAM_DISCONNECTED"],
            human_summary="Video file is missing, so camera/feed health is unknown.",
            failure_detail="video_file_missing",
        )

    capture = cv2.VideoCapture(str(resolved_path))
    if not capture.isOpened():
        capture.release()
        return _build_health_record(
            site_id=site_id,
            camera_id=camera_id,
            timestamp=record_timestamp,
            input_quality_state="UNKNOWN",
            is_usable=False,
            reason_codes=["INPUT_UNKNOWN", "STREAM_DISCONNECTED"],
            human_summary="Video file could not be opened, so input health is unknown.",
            failure_detail="video_file_unreadable",
        )

    try:
        is_readable, _frame = capture.read()
    finally:
        capture.release()

    if not is_readable:
        return _build_health_record(
            site_id=site_id,
            camera_id=camera_id,
            timestamp=record_timestamp,
            input_quality_state="DEGRADED",
            is_usable=False,
            reason_codes=["MISSING_FRAME"],
            human_summary="Video file opened but no readable frame was found.",
            failure_detail="no_readable_frames",
        )

    return _build_health_record(
        site_id=site_id,
        camera_id=camera_id,
        timestamp=record_timestamp,
        input_quality_state="OK",
        is_usable=True,
        reason_codes=["INPUT_USABLE"],
        human_summary="Video file exists, opens, and has at least one readable frame.",
    )


def _build_health_record(
    *,
    site_id: str,
    camera_id: str,
    timestamp: datetime,
    input_quality_state: str,
    is_usable: bool,
    reason_codes: list[str],
    human_summary: str,
    failure_detail: str | None = None,
) -> CameraHealthRecord:
    record: CameraHealthRecord = {
        "contract_version": "v1",
        "record_id": f"camera-health-{uuid4()}",
        "record_type": "camera_health_output",
        "site_id": site_id,
        "camera_id": camera_id,
        "timestamp": timestamp.isoformat(),
        "input_quality_state": input_quality_state,
        "is_usable": is_usable,
        "reason_codes": reason_codes,
        "human_summary": human_summary,
    }
    if failure_detail is not None:
        record["failure_detail"] = failure_detail

    return record


def _normalize_timestamp(timestamp: datetime | None) -> datetime:
    if timestamp is None:
        return datetime.now(tz=UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise FeedHealthError("timestamp must include timezone information")
    return timestamp

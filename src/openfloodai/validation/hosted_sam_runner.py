"""Run hosted SAM segmentation over saved sampled images and keep the evidence (Issue #210).

Each run is its own immutable folder under
`outputs/hosted-sam-runs/<run_id>/`, separate from image-sequence runs, gauge
evidence, and human labels:

    run-summary.json      what was requested, confirmed, and how each item ended
    results/<id>.json     one result per image and concept (provenance + detections)
    masks/<id>-<n>.png    raw full-size binary masks (0/255) in original-image pixels
    reviews.jsonl         append-only human review decisions about those results

Nothing here changes a human guide, a label, or a flood decision. A finished
result is never edited: a rerun is a new run, and a human decision is a new
line in `reviews.jsonl`. Overlays are drawn on request and never saved over
the raw masks.

The key is never part of any record. Every gate that can refuse a run
(plugin disabled, no key, no acknowledgement, no decoder, wrong confirmed
request count) is checked before the first byte is uploaded.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import numpy as np

from openfloodai.config import load_site_config
from openfloodai.contracts import read_jsonl_records
from openfloodai.evidence.hosted_sam_credentials import HostedSamCredentials
from openfloodai.ingestion.river_images import resolve_sequence_image
from openfloodai.vision import hosted_sam as sam

PLUGIN_ID = "hosted_sam_v1"
RUNS_DIRNAME = "hosted-sam-runs"
MAX_IMAGES_PER_BATCH = 10
MAX_CONCEPTS_PER_BATCH = 2
JPEG_QUALITY = 92
REVIEW_DECISIONS = frozenset({"accepted", "rejected", "needs_correction"})
_RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
_RESULT_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")

STATUS_COMPLETED = "completed"
STATUS_NO_MATCH = "no_match"
STATUS_FAILED = "failed"
STATUS_NOT_ATTEMPTED = "not_attempted"
_REUSABLE = {STATUS_COMPLETED, STATUS_NO_MATCH}
# After one of these, sending more paid requests would only repeat the problem.
_STOP_BATCH_ON = {
    sam.ERROR_INVALID_KEY,
    sam.ERROR_INSUFFICIENT_QUOTA,
    sam.ERROR_RATE_LIMITED,
    sam.ERROR_TIMEOUT,
    sam.ERROR_NETWORK,
}


class HostedSamRefused(Exception):
    """A gate refused the run before anything was uploaded."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PlannedItem:
    filename: str
    concept: str
    image_sha256: str
    captured_at_utc: str
    cache_key: str
    transform: sam.CropTransform
    reused_from: tuple[str, str] | None  # (run_id, result_id)


@dataclass(frozen=True)
class Plan:
    items: tuple[PlannedItem, ...]

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def reused_count(self) -> int:
        return sum(1 for item in self.items if item.reused_from is not None)

    @property
    def request_count(self) -> int:
        """Paid requests this run would send."""

        return self.total - self.reused_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_count": len({item.filename for item in self.items}),
            "concepts": sorted({item.concept for item in self.items}),
            "total_items": self.total,
            "reused_from_earlier_runs": self.reused_count,
            "request_count": self.request_count,
        }


def _runs_root(site_dir: Path) -> Path:
    return site_dir / "outputs" / RUNS_DIRNAME


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def cache_key_for(image_sha256: str, concept: str, transform: sam.CropTransform) -> str:
    """Identity of one request: the image's bytes, model, prompt, and preprocessing."""

    payload = json.dumps(
        {
            "image_sha256": image_sha256,
            "model": sam.MODEL_ID,
            "prompt": concept,
            "mask_encoding": sam.MASK_ENCODING,
            "transform": transform.to_dict(),
        },
        sort_keys=True,
    )
    return _sha256_bytes(payload.encode("utf-8"))


def plan_segmentation(
    site_dir: Path, sequence_id: str, filenames: Sequence[str], concepts: Sequence[str]
) -> Plan:
    """Validate the selection and say exactly how many paid requests it needs."""

    names = list(dict.fromkeys(filenames))
    cleaned = list(dict.fromkeys(sam.validate_concept(concept) for concept in concepts))
    if not names:
        raise ValueError("Select at least one image.")
    if len(names) > MAX_IMAGES_PER_BATCH:
        raise ValueError(f"Select at most {MAX_IMAGES_PER_BATCH} images per batch.")
    if not cleaned:
        raise ValueError("Choose a concept.")
    if len(cleaned) > MAX_CONCEPTS_PER_BATCH:
        raise ValueError(f"Choose at most {MAX_CONCEPTS_PER_BATCH} concepts per batch.")

    config = load_site_config(_site_config_path(site_dir))
    region = config.reference_region
    if region is None:
        raise ValueError("Draw this site's watched area first; segmentation uses it as the crop.")
    region_percent = {
        "x": region.x,
        "y": region.y,
        "width": region.width,
        "height": region.height,
    }
    manifest = {
        str(record.get("filename")): record
        for record in read_jsonl_records(
            site_dir / "inputs" / "image-sequences" / sequence_id / "sequence-manifest.jsonl"
        )
    }
    cache = _cache_index(site_dir)
    items: list[PlannedItem] = []
    for name in names:
        path = resolve_sequence_image(site_dir, sequence_id, name)
        raw = path.read_bytes()
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"{name} is not a readable image.")
        height, width = image.shape[:2]
        transform = sam.crop_transform(width, height, region_percent, jpeg_quality=JPEG_QUALITY)
        digest = _sha256_bytes(raw)
        captured = str(manifest.get(name, {}).get("captured_at_utc", ""))
        for concept in cleaned:
            key = cache_key_for(digest, concept, transform)
            items.append(
                PlannedItem(
                    filename=name,
                    concept=concept,
                    image_sha256=digest,
                    captured_at_utc=captured,
                    cache_key=key,
                    transform=transform,
                    reused_from=cache.get(key),
                )
            )
    return Plan(items=tuple(items))


def run_segmentation(
    site_dir: Path,
    sequence_id: str,
    filenames: Sequence[str],
    concepts: Sequence[str],
    *,
    plugin_enabled: bool,
    credentials: HostedSamCredentials,
    confirmed_request_count: object,
    decoder: sam.MaskDecoder | None,
    transport: sam.Transport = sam.urllib_transport,
) -> dict[str, Any]:
    """Run one explicit batch. Raises HostedSamRefused before any upload if a gate fails."""

    if not plugin_enabled:
        raise HostedSamRefused(
            "plugin_disabled", "Hosted SAM segmentation is turned off for this site."
        )
    api_key = credentials.api_key()
    if api_key is None:
        raise HostedSamRefused("not_configured", "Add your own API key before segmenting.")
    if credentials.acknowledged_at() is None:
        raise HostedSamRefused(
            "acknowledgement_required",
            "Confirm that selected images will be uploaded and may be billed to your account.",
        )
    if decoder is None:
        raise HostedSamRefused(sam.ERROR_DECODER_UNAVAILABLE, sam.unavailable_decoder_message())

    plan = plan_segmentation(site_dir, sequence_id, filenames, concepts)
    if confirmed_request_count != plan.request_count or isinstance(confirmed_request_count, bool):
        raise HostedSamRefused(
            "confirm_count_mismatch",
            f"This batch needs {plan.request_count} paid request(s); confirm that number to start.",
        )

    run_id = f"{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    run_dir = _runs_root(site_dir) / run_id
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "masks").mkdir()

    results: list[dict[str, Any]] = []
    halted: str | None = None
    for number, item in enumerate(plan.items, start=1):
        result_id = f"{number:03d}-{_slug(item.filename)}-{_slug(item.concept)}"
        if item.reused_from is not None:
            record = _reuse_result(site_dir, run_dir, result_id, item)
        elif halted is not None:
            record = _result_base(result_id, item)
            record.update(
                status=STATUS_NOT_ATTEMPTED,
                error_code=halted,
                message="Not sent: an earlier request in this batch stopped it.",
                detections=[],
            )
        else:
            record = _segment_item(
                site_dir, sequence_id, run_dir, result_id, item, api_key, decoder, transport
            )
            if record["status"] == STATUS_FAILED and record["error_code"] in _STOP_BATCH_ON:
                halted = str(record["error_code"])
        _write_new_json(run_dir / "results" / f"{result_id}.json", record)
        results.append(record)

    counts: dict[str, int] = {}
    for record in results:
        counts[str(record["status"])] = counts.get(str(record["status"]), 0) + 1
    summary = {
        "run_id": run_id,
        "plugin_id": PLUGIN_ID,
        "provider": sam.PROVIDER,
        "model_requested": sam.MODEL_ID,
        "sequence_id": sequence_id,
        "created_at_utc": datetime.now(tz=UTC).isoformat(),
        "filenames": list(dict.fromkeys(filenames)),
        "concepts": sorted({item.concept for item in plan.items}),
        "plan": plan.to_dict(),
        "confirmed_request_count": confirmed_request_count,
        "upload_acknowledged_at": credentials.acknowledged_at(),
        "credential_source": credentials.source(),
        "status_counts": counts,
        "result_ids": [str(record["result_id"]) for record in results],
        "evidence_notes": (
            "Predictions are unreviewed machine output. They are not human labels, "
            "not calibrated accuracy, and not a flood decision."
        ),
    }
    _write_new_json(run_dir / "run-summary.json", summary)
    return {**summary, "results": results}


def _segment_item(
    site_dir: Path,
    sequence_id: str,
    run_dir: Path,
    result_id: str,
    item: PlannedItem,
    api_key: str,
    decoder: sam.MaskDecoder,
    transport: sam.Transport,
) -> dict[str, Any]:
    record = _result_base(result_id, item)
    record["detections"] = []
    try:
        path = resolve_sequence_image(site_dir, sequence_id, item.filename)
        raw = path.read_bytes()
        if _sha256_bytes(raw) != item.image_sha256:
            raise sam.SamError(
                sam.ERROR_MALFORMED, "The image changed after the batch was planned."
            )
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise sam.SamError(sam.ERROR_MALFORMED, "The image could not be read.")
        transform = item.transform
        crop = image[transform.y0 : transform.y1, transform.x0 : transform.x1]
        ok, encoded = cv2.imencode(
            ".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), transform.jpeg_quality]
        )
        if not ok:
            raise sam.SamError(sam.ERROR_MALFORMED, "The cropped image could not be encoded.")
        data_url = "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")
        detections, _ = sam.segment(
            api_key=api_key,
            concept=item.concept,
            image_data_url=data_url,
            transport=transport,
        )
        placed = []
        for index, detection in enumerate(detections):
            mask = sam.place_mask_in_source(detection, decoder, transform)
            mask_name = f"{result_id}-{index}.png"
            if not cv2.imwrite(str(run_dir / "masks" / mask_name), mask * 255):
                raise sam.SamError(sam.ERROR_MALFORMED, "A mask could not be saved.")
            placed.append((detection, mask_name))
        record["detections"] = [
            {
                "ordinal": detection.ordinal,
                "box_source_px": sam.box_in_source(detection, transform),
                "box_crop_px": list(detection.box_xyxy),
                "mask_png": f"masks/{mask_name}",
                "mask_offset_in_crop": [detection.mask_x, detection.mask_y],
                "mask_size": [detection.mask_width, detection.mask_height],
                "mask_encoding": detection.mask_encoding,
                "mask_payload": detection.mask_payload,
            }
            for detection, mask_name in placed
        ]
        record["status"] = STATUS_COMPLETED if placed else STATUS_NO_MATCH
        record["message"] = (
            None if placed else "The provider found nothing for this concept in the watched area."
        )
    except sam.SamError as error:
        record.update(status=STATUS_FAILED, error_code=error.code, message=error.message)
    except (OSError, ValueError) as error:
        record.update(
            status=STATUS_FAILED,
            error_code=sam.ERROR_MALFORMED,
            message=sam.redact(str(error), api_key)[:200],
        )
    return record


def _result_base(result_id: str, item: PlannedItem) -> dict[str, Any]:
    return {
        "result_id": result_id,
        "filename": item.filename,
        "captured_at_utc": item.captured_at_utc,
        "image_sha256": item.image_sha256,
        "provider": sam.PROVIDER,
        "model_requested": sam.MODEL_ID,
        "model_returned": None,
        "prompt": item.concept,
        "transform": item.transform.to_dict(),
        "cache_key": item.cache_key,
        "processed_at_utc": datetime.now(tz=UTC).isoformat(),
        "status": STATUS_FAILED,
        "error_code": None,
        "message": None,
        "scores_provided": False,
        "review_status": "unreviewed",
        "reused_from": None,
        "detections": [],
    }


def _reuse_result(
    site_dir: Path, run_dir: Path, result_id: str, item: PlannedItem
) -> dict[str, Any]:
    assert item.reused_from is not None
    source_run, source_result = item.reused_from
    source_dir = _runs_root(site_dir) / source_run
    original = json.loads((source_dir / "results" / f"{source_result}.json").read_text("utf-8"))
    record = _result_base(result_id, item)
    record["status"] = original["status"]
    record["message"] = original.get("message")
    record["model_returned"] = original.get("model_returned")
    record["reused_from"] = {"run_id": source_run, "result_id": source_result}
    detections = []
    for index, detection in enumerate(original.get("detections", [])):
        mask_name = f"{result_id}-{index}.png"
        shutil.copyfile(source_dir / detection["mask_png"], run_dir / "masks" / mask_name)
        detections.append({**detection, "mask_png": f"masks/{mask_name}"})
    record["detections"] = detections
    return record


def _cache_index(site_dir: Path) -> dict[str, tuple[str, str]]:
    """Earlier successful results by their request identity (oldest wins)."""

    index: dict[str, tuple[str, str]] = {}
    root = _runs_root(site_dir)
    if not root.is_dir():
        return index
    for run_dir in sorted(root.iterdir()):
        if not _RUN_ID.fullmatch(run_dir.name):
            continue
        for path in sorted((run_dir / "results").glob("*.json")):
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            key = loaded.get("cache_key") if isinstance(loaded, dict) else None
            if isinstance(key, str) and loaded.get("status") in _REUSABLE:
                index.setdefault(key, (run_dir.name, str(loaded["result_id"])))
    return index


def list_sam_runs(site_dir: Path, sequence_id: str | None = None) -> list[dict[str, Any]]:
    """Run summaries, newest first. Summaries never contain credentials."""

    root = _runs_root(site_dir)
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for run_dir in sorted(root.iterdir(), reverse=True):
        if not _RUN_ID.fullmatch(run_dir.name):
            continue
        try:
            summary = json.loads((run_dir / "run-summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if sequence_id is None or summary.get("sequence_id") == sequence_id:
            rows.append(summary)
    return rows


def read_sam_run(site_dir: Path, run_id: str) -> dict[str, Any]:
    """A run with each result's latest human review status merged in at read time."""

    run_dir = _run_dir(site_dir, run_id)
    summary = json.loads((run_dir / "run-summary.json").read_text(encoding="utf-8"))
    reviews = _latest_reviews(run_dir)
    results = []
    for result_id in summary.get("result_ids", []):
        record = json.loads((run_dir / "results" / f"{result_id}.json").read_text("utf-8"))
        review = reviews.get(result_id)
        record["review_status"] = review["decision"] if review else "unreviewed"
        record["reviewed_at_utc"] = review["reviewed_at_utc"] if review else None
        results.append(record)
    return {**summary, "results": results}


def record_sam_review(site_dir: Path, run_id: str, result_id: str, decision: str) -> dict[str, Any]:
    """Append one human decision about a result; the result itself is never edited."""

    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"decision must be one of {sorted(REVIEW_DECISIONS)}.")
    run_dir = _run_dir(site_dir, run_id)
    if (
        not _RESULT_ID.fullmatch(result_id)
        or not (run_dir / "results" / f"{result_id}.json").is_file()
    ):
        raise ValueError("Unknown result for this run.")
    entry = {
        "result_id": result_id,
        "decision": decision,
        "reviewed_at_utc": datetime.now(tz=UTC).isoformat(),
    }
    with (run_dir / "reviews.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


def _latest_reviews(run_dir: Path) -> dict[str, dict[str, Any]]:
    path = run_dir / "reviews.jsonl"
    latest: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("decision") in REVIEW_DECISIONS:
            latest[str(entry.get("result_id"))] = entry
    return latest


def render_overlay(site_dir: Path, run_id: str, result_id: str) -> bytes:
    """The original image with the predicted masks tinted and the human guide drawn on top.

    Drawn fresh each time from the saved raw masks. The crop outline shows the
    area that was actually sent. The guide is the site's current human guide,
    drawn as a thin line; it is never altered by or merged with a mask.
    """

    run_dir = _run_dir(site_dir, run_id)
    if not _RESULT_ID.fullmatch(result_id):
        raise ValueError("Unknown result for this run.")
    record = json.loads((run_dir / "results" / f"{result_id}.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "run-summary.json").read_text(encoding="utf-8"))
    path = resolve_sequence_image(site_dir, str(summary["sequence_id"]), str(record["filename"]))
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The source image could not be read.")
    tint = image.copy()
    for detection in record.get("detections", []):
        mask = cv2.imread(str(run_dir / detection["mask_png"]), cv2.IMREAD_GRAYSCALE)
        if mask is not None and mask.shape == image.shape[:2]:
            tint[mask > 0] = (255, 160, 40)
    output = cv2.addWeighted(tint, 0.45, image, 0.55, 0)
    x0, y0, x1, y1 = record["transform"]["crop_px"]
    cv2.rectangle(output, (x0, y0), (x1 - 1, y1 - 1), (255, 255, 255), 1)
    try:
        guides = load_site_config(_site_config_path(site_dir)).normal_waterline_guides
    except Exception:  # noqa: BLE001 -- an unreadable config must not hide the mask
        guides = ()
    height, width = image.shape[:2]
    for guide in guides:
        if guide.status == "invalid" or len(guide.points) < 2:
            continue
        points = np.array(
            [[round(p.x * width / 100.0), round(p.y * height / 100.0)] for p in guide.points],
            dtype=np.int32,
        )
        cv2.polylines(output, [points], False, (40, 220, 40), 2)
    ok, encoded = cv2.imencode(".png", output)
    if not ok:
        raise ValueError("The overlay could not be drawn.")
    return bytes(encoded.tobytes())


def _run_dir(site_dir: Path, run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("Unknown hosted SAM run.")
    run_dir = _runs_root(site_dir) / run_id
    if run_dir.is_symlink() or not (run_dir / "run-summary.json").is_file():
        raise ValueError("Unknown hosted SAM run.")
    return run_dir


def _site_config_path(site_dir: Path) -> Path:
    paths = sorted((site_dir / "configs").glob("*.json"))
    if not paths:
        raise ValueError("This site has no saved configuration.")
    return paths[0]


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:60] or "item"


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    """Create a file exactly once; refuse to overwrite saved evidence."""

    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")

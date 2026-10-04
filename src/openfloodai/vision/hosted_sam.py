"""Client for Meta's hosted SAM 3.1 segmentation API (Issue #210 / OF-091).

One provider, one model, one concept per request. Everything here is pure or
takes its collaborators (HTTP transport, mask decoder) as arguments, so the
normal test suite never needs a paid API call or a real key.

The streamed reply is read with Meta's own `meta_sam_parser` package, which
defines the Responses event wrapper, the `<|box|>`/`<|mask|>` tokens, the
inclusive box coordinates, the optional confidence field, and the mask codec.
This module does not re-implement any of that. Without the package installed,
nothing can be sent (see `official_mask_decoder`).

Verified against Meta's public documentation and that package: the endpoint,
the bearer-token header, the request body, and the reply format. NOT verified
against the live service, because that needs a paid key: the HTTP status codes
for quota and rate limiting. Unrecognized replies become `malformed_response`
rather than a guess.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

PROVIDER = "meta_sam_hosted"
MODEL_ID = "sam-3.1"
ENDPOINT = "https://api.meta.ai/v1/responses"
MASK_ENCODING = "one_bit"
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

# Links shown to the user. Signup is the page the issue names; the terms and
# privacy links are the ones that page itself lists. The page does not state
# image retention or training use, so the UI says that rather than guessing.
SIGNUP_URL = "https://dev.meta.ai/models/sam-3-1"
TERMS_URL = "https://www.facebook.com/policies_center/"
PRIVACY_URL = "https://www.facebook.com/privacy/policy/"
PRICING_NOTE = (
    'The provider page listed "$2.50/1k images" when this was written. '
    "Check the current price with Meta before running."
)

# Error states. Each is distinct and none means safe, normal, or no change.
ERROR_NOT_CONFIGURED = "not_configured"
ERROR_INVALID_KEY = "invalid_key"
ERROR_INSUFFICIENT_QUOTA = "insufficient_quota"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_TIMEOUT = "timeout"
ERROR_NETWORK = "network_error"
ERROR_PROVIDER = "provider_error"
ERROR_MALFORMED = "malformed_response"
ERROR_DECODER_UNAVAILABLE = "decoder_unavailable"

_CONCEPT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z -]{0,39}$")


class SamError(Exception):
    """A provider-side or local failure, with a stable code and a safe message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MaskDecoder(Protocol):
    """Turns one mask payload into an H x W array of 0/1."""

    def __call__(
        self, height: int, width: int, encoding: str, payload: str
    ) -> npt.NDArray[Any]: ...


@dataclass(frozen=True)
class RawDetection:
    """One returned object, in the pixels of the cropped image that was sent.

    The box is `[left, right) x [top, bottom)` (the provider sends inclusive
    corners; the parser converts them). The mask is box-local: its raster is the
    size of the box and is anchored at the box's top-left corner. The payload is
    kept exactly as emitted, marker character included.
    """

    object_id: str
    left: int
    top: int
    right: int
    bottom: int
    mask_encoding: str  # "one_bit" | "lossless"
    mask_payload: str
    mask_width: int
    mask_height: int
    confidence: float | None  # as reported by the provider; not calibrated accuracy


@dataclass(frozen=True)
class CropTransform:
    """How a crop of the original image maps back to it. Saved with every result."""

    source_width: int
    source_height: int
    x0: int
    y0: int
    x1: int
    y1: int
    region_percent: dict[str, float]
    jpeg_quality: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_size": [self.source_width, self.source_height],
            "crop_px": [self.x0, self.y0, self.x1, self.y1],
            "crop_size": [self.width, self.height],
            "region_percent": dict(self.region_percent),
            "jpeg_quality": self.jpeg_quality,
            "rounding": "floor of top-left, ceil of bottom-right, at least 1 pixel",
        }


def validate_concept(concept: str) -> str:
    """One short noun phrase. Commands, questions and combined prompts are refused."""

    cleaned = " ".join(str(concept).split())
    if not _CONCEPT_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "A concept is one short noun phrase of letters, such as 'water' or 'riverbank'."
        )
    if re.search(r"\b(and|or|then)\b", cleaned, re.IGNORECASE):
        raise ValueError("Use one concept per request; run 'water' and 'riverbank' separately.")
    return cleaned.lower()


def crop_transform(
    source_width: int,
    source_height: int,
    region_percent: Mapping[str, float],
    *,
    jpeg_quality: int,
) -> CropTransform:
    """Pixel crop for a percentage watch region; always inside the image, at least 1 px."""

    x = float(region_percent["x"])
    y = float(region_percent["y"])
    width = float(region_percent["width"])
    height = float(region_percent["height"])
    x0 = min(max(math.floor(source_width * x / 100.0), 0), source_width - 1)
    y0 = min(max(math.floor(source_height * y / 100.0), 0), source_height - 1)
    x1 = min(max(math.ceil(source_width * (x + width) / 100.0), x0 + 1), source_width)
    y1 = min(max(math.ceil(source_height * (y + height) / 100.0), y0 + 1), source_height)
    return CropTransform(
        source_width=source_width,
        source_height=source_height,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        region_percent={"x": x, "y": y, "width": width, "height": height},
        jpeg_quality=jpeg_quality,
    )


def build_request_body(concept: str, image_data_url: str) -> dict[str, Any]:
    """The documented request: one concept as text plus one image."""

    return {
        "model": MODEL_ID,
        "stream": True,
        "metadata": {"mask_encoding": MASK_ENCODING},
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": validate_concept(concept)},
                    {"type": "input_image", "image_url": image_data_url},
                ],
            }
        ],
    }


def extract_events(body: str) -> list[dict[str, Any]]:
    """The JSON events of a server-sent-event reply, in order."""

    events: list[dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except ValueError as error:
            raise SamError(ERROR_MALFORMED, "The provider stream was not valid.") from error
        if isinstance(event, dict):
            events.append(event)
    if not events:
        raise SamError(ERROR_MALFORMED, "The provider reply contained no events.")
    return events


def parse_events(
    events: list[dict[str, Any]], secret: str | None = None
) -> tuple[list[RawDetection], list[str]]:
    """Parse reply events with Meta's parser into detections and warnings.

    A completed reply with no objects is a real "no match". A failed, refused,
    unfinished, or partly unreadable reply is an error state instead, so a
    missing mask is never mistaken for "nothing there".
    """

    try:
        from meta_sam_parser import (
            CompletedOutcome,
            ResponsesStreamError,
            ResponsesStreamFailedError,
            ResponsesStreamRefusalError,
            image_segmentation_format,
            parse_responses_stream,
        )
    except ImportError as error:
        raise SamError(ERROR_DECODER_UNAVAILABLE, unavailable_decoder_message()) from error

    async def source() -> Any:
        for event in events:
            yield event

    async def run() -> Any:
        stream = parse_responses_stream(source(), image_segmentation_format())
        return await stream.final_result()

    try:
        result = asyncio.run(run())
    except (ResponsesStreamFailedError, ResponsesStreamRefusalError) as error:
        raise SamError(
            ERROR_PROVIDER, f"The provider could not finish: {redact(str(error), secret)[:200]}"
        ) from error
    except ResponsesStreamError as error:
        raise SamError(ERROR_MALFORMED, "The provider reply could not be parsed.") from error

    if not isinstance(result.outcome, CompletedOutcome):
        raise SamError(ERROR_MALFORMED, "The provider reply ended before it finished.")
    problems = [d for d in result.diagnostics if d.severity == "error"]
    if problems:
        raise SamError(ERROR_MALFORMED, "Part of the provider reply could not be read.")
    boxes = {r.object_id: r for r in result.records if r.kind == "box"}
    detections: list[RawDetection] = []
    for record in result.records:
        if record.kind != "mask":
            continue
        box = boxes.get(record.object_id)
        confidence = record.confidence
        if confidence is None and box is not None:
            confidence = box.confidence
        detections.append(
            RawDetection(
                object_id=record.object_id,
                left=int(record.bounds.left),
                top=int(record.bounds.top),
                right=int(record.bounds.right),
                bottom=int(record.bounds.bottom),
                mask_encoding=record.mask.encoding,
                mask_payload=record.mask.payload,
                mask_width=record.mask.width,
                mask_height=record.mask.height,
                confidence=confidence,
            )
        )
    warnings = [redact(d.message, secret) for d in result.diagnostics if d.severity == "warning"]
    return detections, warnings[:5]


def place_mask_in_source(
    detection: RawDetection,
    decoder: MaskDecoder,
    transform: CropTransform,
) -> npt.NDArray[np.uint8]:
    """Decode one mask and place it on a full-size canvas in ORIGINAL image pixels.

    The provider's box and mask are in the cropped image it was sent, and the
    mask is anchored at the box's top-left corner, so it is shifted by the crop
    origin. A box that falls outside the crop, or a mask whose size is not the
    box's size, is rejected rather than clipped: a mask can never land outside
    the watch region or on the wrong image.
    """

    if (
        detection.left < 0
        or detection.top < 0
        or detection.right > transform.width
        or detection.bottom > transform.height
        or detection.right <= detection.left
        or detection.bottom <= detection.top
    ):
        raise SamError(ERROR_MALFORMED, "A returned box falls outside the cropped image.")
    if (detection.mask_width, detection.mask_height) != (
        detection.right - detection.left,
        detection.bottom - detection.top,
    ):
        raise SamError(ERROR_MALFORMED, "A returned mask does not match its box size.")
    raster = np.asarray(
        decoder(
            detection.mask_height,
            detection.mask_width,
            detection.mask_encoding,
            detection.mask_payload,
        )
    )
    if raster.shape != (detection.mask_height, detection.mask_width):
        raise SamError(ERROR_MALFORMED, "The decoded mask does not match its declared size.")
    canvas = np.zeros((transform.source_height, transform.source_width), dtype=np.uint8)
    top = transform.y0 + detection.top
    left = transform.x0 + detection.left
    canvas[top : top + detection.mask_height, left : left + detection.mask_width] = (
        raster > 0
    ).astype(np.uint8)
    return canvas


def box_in_source(detection: RawDetection, transform: CropTransform) -> list[int]:
    """`[left, top, right, bottom]` in original pixels; right and bottom are exclusive."""

    return [
        detection.left + transform.x0,
        detection.top + transform.y0,
        detection.right + transform.x0,
        detection.bottom + transform.y0,
    ]


def unavailable_decoder_message() -> str:
    return (
        "Meta's official SAM parser is not installed (pip install meta_sam_parser), "
        "so masks cannot be read and no paid request is sent."
    )


def official_mask_decoder() -> MaskDecoder | None:
    """Meta's own mask decoder, or None when `meta_sam_parser` is not installed."""

    try:
        from meta_sam_parser import (
            InvalidSegmentationMaskError,
            SegmentationMask,
            decode_mask_to_raster,
        )
    except ImportError:
        return None

    def decode(height: int, width: int, encoding: str, payload: str) -> npt.NDArray[Any]:
        if encoding not in ("one_bit", "lossless"):
            raise SamError(ERROR_MALFORMED, "A returned mask used an unknown encoding.")
        mask = SegmentationMask(
            encoding=encoding,  # type: ignore[arg-type]
            payload=payload,
            width=width,
            height=height,
        )
        try:
            raw = decode_mask_to_raster(mask)
        except InvalidSegmentationMaskError as error:
            raise SamError(ERROR_MALFORMED, "A returned mask could not be decoded.") from error
        return np.frombuffer(raw, dtype=np.uint8).reshape(height, width)

    return decode


def unavailable_mask_decoder(height: int, width: int, encoding: str, payload: str) -> Any:
    raise SamError(ERROR_DECODER_UNAVAILABLE, unavailable_decoder_message())


# --- transport -------------------------------------------------------------

Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, str]]


def redact(text: str, secret: str | None) -> str:
    """Remove a credential from any text before it is stored, logged or shown."""

    if secret and len(secret) >= 4:
        text = text.replace(secret, "[redacted]")
    return re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer [redacted]", text)


def urllib_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> tuple[int, str]:
    """POST once. Never retries: a request that may have reached the provider can be billed."""

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code), error.read(65536).decode("utf-8", errors="replace")
    except TimeoutError as error:
        raise SamError(
            ERROR_TIMEOUT, "The request timed out. It may still have been billed."
        ) from error
    except (urllib.error.URLError, OSError) as error:
        if isinstance(getattr(error, "reason", None), TimeoutError):
            raise SamError(
                ERROR_TIMEOUT, "The request timed out. It may still have been billed."
            ) from error
        raise SamError(ERROR_NETWORK, "The provider could not be reached.") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise SamError(ERROR_MALFORMED, "The provider reply was too large.")
    return status, raw.decode("utf-8", errors="replace")


def classify_http_error(status: int, body: str, secret: str | None) -> SamError:
    """Map an HTTP failure to a stable state with a short, redacted provider message."""

    detail = ""
    try:
        parsed = json.loads(body)
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, dict):
            detail = f"{error.get('code', '')}: {error.get('message', '')}".strip(": ")
    except ValueError:
        pass
    detail = redact(detail, secret)[:200]
    suffix = f" ({detail})" if detail else ""
    if status in (401, 403):
        return SamError(ERROR_INVALID_KEY, f"The API key was rejected or revoked{suffix}.")
    if status == 402:
        return SamError(
            ERROR_INSUFFICIENT_QUOTA, f"The provider account has no quota left{suffix}."
        )
    if status == 429:
        return SamError(ERROR_RATE_LIMITED, f"The provider is rate limiting requests{suffix}.")
    return SamError(ERROR_PROVIDER, f"The provider returned HTTP {status}{suffix}.")


def segment(
    *,
    api_key: str,
    concept: str,
    image_data_url: str,
    transport: Transport = urllib_transport,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> tuple[list[RawDetection], list[str]]:
    """Send ONE paid request for ONE concept; return detections and parser warnings.

    The key is only ever placed in the Authorization header, and any provider
    text that is kept is redacted first. There is no automatic retry.
    """

    if not api_key:
        raise SamError(ERROR_NOT_CONFIGURED, "No API key is configured.")
    body = json.dumps(build_request_body(concept, image_data_url)).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    status, text = transport(ENDPOINT, headers, body, timeout)
    if status != 200:
        raise classify_http_error(status, text, api_key)
    try:
        detections, warnings = parse_events(extract_events(text), api_key)
    except SamError as error:
        # Whatever the provider streamed back, a stored or shown message never carries the key.
        raise SamError(error.code, redact(error.message, api_key)) from error
    return detections, [redact(warning, api_key) for warning in warnings]

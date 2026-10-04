"""Client for Meta's hosted SAM 3.1 segmentation API (Issue #210 / OF-091).

One provider, one model, one concept per request. Everything here is pure or
takes its collaborators (HTTP transport, mask decoder) as arguments, so the
normal test suite never needs a paid API call or a real key.

What was verified against Meta's public documentation (dev.meta.ai/docs/sam,
read while building this): the endpoint, the bearer-token header, the request
body, the streamed special-token text output, the `<H>,<W>,<codec>payload`
mask header, and that boxes and masks are in source pixels. NOT verified
against the live service, because that needs a paid key: the exact SSE JSON
wrapper and the HTTP status codes for quota and rate limiting. Parsing is
therefore tolerant, and anything it cannot understand becomes a
`malformed_response` state rather than a guess.

The mask codec itself is not published as a specification, only as Meta's own
decoder library. This module does not re-implement it. Masks are decoded
through a `MaskDecoder` the caller supplies; without one, a request is still
sent only when the caller says a decoder exists (see `decoder_available`).
"""

from __future__ import annotations

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
    """One returned object: its box, and its mask still in the provider's encoding."""

    ordinal: int
    box_xyxy: tuple[int, int, int, int]
    frame_size: tuple[int, int]  # (width, height) of the frame the box refers to
    mask_x: int
    mask_y: int
    mask_height: int
    mask_width: int
    mask_encoding: str
    mask_payload: str


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


_OBJECT = re.compile(
    r"(?P<ordinal>\d+)<\|box;(?P<box>[^|]*)\|>"
    r"<\|mask;x=(?P<x>\d+);y=(?P<y>\d+);data=(?P<h>\d+),(?P<w>\d+),(?P<enc>[~!])"
    r"(?P<payload>.*?)\|>(?=\d*<\|box;|<\d+f>|\Z)",
    re.DOTALL,
)


def parse_segmentation_text(text: str) -> list[RawDetection]:
    """Parse the provider's special-token text into detections.

    An empty or object-free reply is a real, valid "no match". Text that has
    box or mask markers but cannot be parsed raises `malformed_response`.
    """

    detections: list[RawDetection] = []
    for match in _OBJECT.finditer(text):
        fields = dict(part.split("=", 1) for part in match.group("box").split(";") if "=" in part)
        try:
            box = (
                int(fields["x1"]),
                int(fields["y1"]),
                int(fields["x2"]),
                int(fields["y2"]),
            )
            frame = (int(fields["w"]), int(fields["h"]))
        except (KeyError, ValueError) as error:
            raise SamError(ERROR_MALFORMED, "The provider returned an unreadable box.") from error
        detections.append(
            RawDetection(
                ordinal=int(match.group("ordinal")),
                box_xyxy=box,
                frame_size=frame,
                mask_x=int(match.group("x")),
                mask_y=int(match.group("y")),
                mask_height=int(match.group("h")),
                mask_width=int(match.group("w")),
                mask_encoding=match.group("enc"),
                mask_payload=match.group("payload"),
            )
        )
    if not detections and ("<|box" in text or "<|mask" in text):
        raise SamError(ERROR_MALFORMED, "The provider reply could not be parsed.")
    return detections


def extract_output_text(body: str) -> str:
    """Join the streamed text deltas; also accept a plain JSON reply carrying `output_text`.

    The stream is server-sent events; each `data:` line is JSON whose text is in
    `delta` for `response.output_text.delta` events (per the provider docs).
    """

    stripped = body.strip()
    if not stripped:
        return ""
    pieces: list[str] = []
    saw_event = False
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        saw_event = True
        try:
            event = json.loads(payload)
        except ValueError as error:
            raise SamError(ERROR_MALFORMED, "The provider stream was not valid.") from error
        if isinstance(event, dict) and event.get("type") == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                pieces.append(delta)
    if saw_event:
        return "".join(pieces)
    try:
        whole = json.loads(stripped)
    except ValueError as error:
        raise SamError(ERROR_MALFORMED, "The provider reply was not valid.") from error
    text = whole.get("output_text") if isinstance(whole, dict) else None
    if isinstance(text, str):
        return text
    raise SamError(ERROR_MALFORMED, "The provider reply had no segmentation text.")


def place_mask_in_source(
    detection: RawDetection,
    decoder: MaskDecoder,
    transform: CropTransform,
) -> npt.NDArray[np.uint8]:
    """Decode one mask and place it on a full-size canvas in ORIGINAL image pixels.

    The provider's box and mask are in the cropped image it was sent, so the
    mask offset inside that crop is shifted by the crop origin. Anything that
    does not fit inside the crop is rejected, never clipped, so a mask can
    never land outside the watch region or on the wrong image.
    """

    if detection.frame_size != (transform.width, transform.height):
        raise SamError(
            ERROR_MALFORMED,
            "The provider's frame size does not match the cropped image that was sent.",
        )
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
    if (
        detection.mask_x < 0
        or detection.mask_y < 0
        or detection.mask_x + detection.mask_width > transform.width
        or detection.mask_y + detection.mask_height > transform.height
    ):
        raise SamError(ERROR_MALFORMED, "A mask falls outside the cropped image.")
    canvas = np.zeros((transform.source_height, transform.source_width), dtype=np.uint8)
    top = transform.y0 + detection.mask_y
    left = transform.x0 + detection.mask_x
    canvas[top : top + detection.mask_height, left : left + detection.mask_width] = (
        raster > 0
    ).astype(np.uint8)
    return canvas


def box_in_source(detection: RawDetection, transform: CropTransform) -> list[int]:
    x1, y1, x2, y2 = detection.box_xyxy
    return [x1 + transform.x0, y1 + transform.y0, x2 + transform.x0, y2 + transform.y0]


def unavailable_decoder_message() -> str:
    return (
        "No mask decoder is installed. Masks cannot be read until Meta's official "
        "decoder is added to this installation, so no paid request is sent."
    )


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
) -> tuple[list[RawDetection], str]:
    """Send ONE paid request for ONE concept; return detections and the reply's text.

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
    output = extract_output_text(text)
    return parse_segmentation_text(output), redact(output, api_key)

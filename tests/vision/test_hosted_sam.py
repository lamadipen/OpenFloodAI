"""Hosted SAM provider parsing, mapping, and failure states (no network, no key)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import numpy as np
import pytest

from openfloodai.vision import hosted_sam as sam

KEY = "sk-test-0123456789abcdef"


def reply(text: str, *, complete: bool = True) -> str:
    lane = {"item_id": "m1", "output_index": 0, "content_index": 0}
    events: list[dict[str, Any]] = [
        {"type": "response.output_text.delta", **lane, "delta": text},
        {"type": "response.output_text.done", **lane, "text": text},
    ]
    if complete:
        events.append({"type": "response.completed"})
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


def mask_payload(width: int, height: int) -> str:
    from meta_sam_parser._mask_codec import _encode_raster

    return str(_encode_raster([1] * (width * height), width, height))


def one_object(
    x1: int = 1, y1: int = 2, x2: int = 20, y2: int = 25, w: int = 40, h: int = 30
) -> str:
    mask_w, mask_h = x2 - x1 + 1, y2 - y1 + 1
    return (
        f"<0f>0<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={w};h={h};c=0.8|>"
        f"<|mask;x=0;y=0;data={mask_h},{mask_w},{mask_payload(mask_w, mask_h)}|>\n"
    )


def parse(text: str, **kwargs: Any) -> list[sam.RawDetection]:
    return sam.parse_events(sam.extract_events(reply(text, **kwargs)))[0]


def ones_decoder(height: int, width: int, encoding: str, payload: str) -> Any:
    return np.ones((height, width), dtype=np.uint8)


def test_concept_is_one_short_noun_phrase() -> None:
    assert sam.validate_concept("  Water ") == "water"
    assert sam.validate_concept("river bank") == "river bank"
    for bad in ("water and riverbank", "segment the water!", "", "a" * 60, "water?", "1water"):
        with pytest.raises(ValueError):
            sam.validate_concept(bad)


def test_request_body_matches_the_documented_shape_and_has_one_concept() -> None:
    body = sam.build_request_body("Water", "data:image/jpeg;base64,AAAA")

    assert body["model"] == "sam-3.1"
    assert body["metadata"] == {"mask_encoding": "one_bit"}
    content = body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "water"}
    assert content[1] == {"type": "input_image", "image_url": "data:image/jpeg;base64,AAAA"}


def test_parse_reads_inclusive_boxes_masks_and_confidence_with_the_official_parser() -> None:
    detections = parse(one_object())

    assert len(detections) == 1
    d = detections[0]
    # inclusive corners (1,2)-(20,25) become the half-open box [1,21) x [2,26)
    assert (d.left, d.top, d.right, d.bottom) == (1, 2, 21, 26)
    assert (d.mask_width, d.mask_height) == (20, 24)
    assert d.mask_encoding == "one_bit" and d.mask_payload.startswith("!")
    assert d.confidence == 0.8


def test_a_completed_reply_with_no_objects_is_a_real_no_match() -> None:
    assert parse("") == []
    assert parse("plain text, no objects\n") == []


def test_a_reply_that_never_completes_is_not_mistaken_for_no_match() -> None:
    with pytest.raises(sam.SamError) as raised:
        parse(one_object(), complete=False)
    assert raised.value.code == sam.ERROR_MALFORMED


def test_an_unreadable_object_line_is_malformed_not_silently_dropped() -> None:
    with pytest.raises(sam.SamError) as raised:
        parse("<0f>0<|box;broken|><|mask;x=0;y=0;data=1,1,!|>\n")
    assert raised.value.code == sam.ERROR_MALFORMED


def test_a_failed_or_refused_response_is_a_provider_error() -> None:
    failed = {"type": "response.failed", "response": {"error": {"message": "boom"}}}
    refused = {"type": "response.refusal.done", "refusal": "no"}
    for event in (failed, refused):
        with pytest.raises(sam.SamError) as raised:
            sam.parse_events([event])
        assert raised.value.code == sam.ERROR_PROVIDER


def test_events_are_read_from_server_sent_data_lines() -> None:
    events = sam.extract_events(reply(""))
    assert [e["type"] for e in events][-1] == "response.completed"
    for broken in ("data: {not json}\n", "not a reply", ""):
        with pytest.raises(sam.SamError) as raised:
            sam.extract_events(broken)
        assert raised.value.code == sam.ERROR_MALFORMED


def test_crop_transform_maps_percent_region_to_pixels_inside_the_image() -> None:
    region = {"x": 10.0, "y": 20.0, "width": 50.0, "height": 50.0}
    transform = sam.crop_transform(100, 60, region, jpeg_quality=90)

    assert (transform.x0, transform.y0, transform.x1, transform.y1) == (10, 12, 60, 42)
    assert transform.to_dict()["crop_size"] == [50, 30]
    # Out-of-range and tiny regions are clamped, never negative or empty.
    edge = sam.crop_transform(
        100, 60, {"x": 99.9, "y": 99.9, "width": 50, "height": 50}, jpeg_quality=90
    )
    assert edge.x1 <= 100 and edge.y1 <= 60 and edge.width >= 1 and edge.height >= 1
    assert edge.x0 >= 0 and edge.y0 >= 0


def test_mask_is_placed_in_original_pixels_using_the_crop_origin() -> None:
    transform = sam.crop_transform(
        100, 60, {"x": 10, "y": 20, "width": 40, "height": 50}, jpeg_quality=90
    )
    assert (transform.width, transform.height) == (40, 30)
    detection = parse(one_object())[0]

    canvas = sam.place_mask_in_source(detection, ones_decoder, transform)

    assert canvas.shape == (60, 100)
    ys, xs = np.nonzero(canvas)
    # box-local mask anchored at box (1,2) inside the crop whose origin is (10,12)
    assert (int(xs.min()), int(ys.min())) == (11, 14)
    assert (int(xs.max()), int(ys.max())) == (30, 37)
    assert sam.box_in_source(detection, transform) == [11, 14, 31, 38]
    outside = canvas.copy()
    outside[12:42, 10:50] = 0
    assert not outside.any()


def test_boxes_outside_the_crop_and_mismatched_masks_are_rejected() -> None:
    transform = sam.crop_transform(
        100, 60, {"x": 10, "y": 20, "width": 40, "height": 50}, jpeg_quality=90
    )
    too_far = parse(one_object(x2=60, w=100))[0]  # right edge 61 > crop width 40
    with pytest.raises(sam.SamError) as raised:
        sam.place_mask_in_source(too_far, ones_decoder, transform)
    assert raised.value.code == sam.ERROR_MALFORMED

    good = parse(one_object())[0]
    resized = sam.RawDetection(**{**good.__dict__, "mask_width": 5})
    with pytest.raises(sam.SamError) as raised:
        sam.place_mask_in_source(resized, ones_decoder, transform)
    assert raised.value.code == sam.ERROR_MALFORMED

    with pytest.raises(sam.SamError) as raised:
        sam.place_mask_in_source(good, lambda h, w, e, p: np.ones((1, 1)), transform)
    assert raised.value.code == sam.ERROR_MALFORMED


def test_the_official_decoder_reads_real_masks_and_rejects_corrupt_ones() -> None:
    decoder = sam.official_mask_decoder()
    assert decoder is not None
    good = parse(one_object())[0]

    raster = decoder(good.mask_height, good.mask_width, good.mask_encoding, good.mask_payload)
    assert raster.shape == (24, 20) and int(raster.sum()) == 24 * 20

    with pytest.raises(sam.SamError) as raised:
        decoder(24, 20, "one_bit", "!not-a-real-payload")
    assert raised.value.code == sam.ERROR_MALFORMED
    with pytest.raises(sam.SamError):
        decoder(24, 20, "mystery", good.mask_payload)


def test_the_default_decoder_is_explicitly_unavailable() -> None:
    with pytest.raises(sam.SamError) as raised:
        sam.unavailable_mask_decoder(1, 1, "!", "")
    assert raised.value.code == sam.ERROR_DECODER_UNAVAILABLE


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, sam.ERROR_INVALID_KEY),
        (403, sam.ERROR_INVALID_KEY),
        (402, sam.ERROR_INSUFFICIENT_QUOTA),
        (429, sam.ERROR_RATE_LIMITED),
        (500, sam.ERROR_PROVIDER),
    ],
)
def test_http_failures_map_to_distinct_states_and_redact_the_key(status: int, code: str) -> None:
    body = json.dumps({"error": {"code": "x", "message": f"bad key {KEY} here"}})

    error = sam.classify_http_error(status, body, KEY)

    assert error.code == code
    assert KEY not in error.message
    assert "redacted" in error.message


def test_redact_removes_keys_and_bearer_tokens() -> None:
    assert KEY not in sam.redact(f"oops {KEY}", KEY)
    assert "abcdefghijkl" not in sam.redact("Authorization: Bearer abcdefghijkl", None)


def test_segment_sends_the_key_only_in_the_header_and_once() -> None:
    calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, str]:
        calls.append((url, headers, body, timeout))
        return 200, reply(one_object())

    detections, text = sam.segment(
        api_key=KEY,
        concept="water",
        image_data_url="data:image/jpeg;base64,AAAA",
        transport=transport,
    )

    assert len(calls) == 1 and len(detections) == 1
    url, headers, body, timeout = calls[0]
    assert url == "https://api.meta.ai/v1/responses"
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert KEY.encode() not in body
    assert timeout == sam.REQUEST_TIMEOUT_SECONDS
    assert KEY not in text


def test_segment_without_a_key_never_calls_the_transport() -> None:
    def transport(*args: Any) -> tuple[int, str]:
        raise AssertionError("must not be called")

    with pytest.raises(sam.SamError) as raised:
        sam.segment(api_key="", concept="water", image_data_url="x", transport=transport)
    assert raised.value.code == sam.ERROR_NOT_CONFIGURED


def test_segment_does_not_retry_a_failed_request() -> None:
    attempts = 0

    def transport(*args: Any) -> tuple[int, str]:
        nonlocal attempts
        attempts += 1
        return 429, "{}"

    with pytest.raises(sam.SamError) as raised:
        sam.segment(api_key=KEY, concept="water", image_data_url="x", transport=transport)
    assert raised.value.code == sam.ERROR_RATE_LIMITED
    assert attempts == 1


def test_urllib_transport_maps_timeouts_and_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def raises(error: BaseException) -> Any:
        def fake(*args: Any, **kwargs: Any) -> Any:
            raise error

        return fake

    monkeypatch.setattr(urllib.request, "urlopen", raises(TimeoutError()))
    with pytest.raises(sam.SamError) as raised:
        sam.urllib_transport(sam.ENDPOINT, {}, b"{}", 1.0)
    assert raised.value.code == sam.ERROR_TIMEOUT

    monkeypatch.setattr(urllib.request, "urlopen", raises(urllib.error.URLError(TimeoutError())))
    with pytest.raises(sam.SamError) as raised:
        sam.urllib_transport(sam.ENDPOINT, {}, b"{}", 1.0)
    assert raised.value.code == sam.ERROR_TIMEOUT

    monkeypatch.setattr(urllib.request, "urlopen", raises(urllib.error.URLError("dns failure")))
    with pytest.raises(sam.SamError) as raised:
        sam.urllib_transport(sam.ENDPOINT, {}, b"{}", 1.0)
    assert raised.value.code == sam.ERROR_NETWORK


def test_streamed_failures_and_warnings_never_carry_the_key() -> None:
    failed = {
        "type": "response.failed",
        "response": {"error": {"message": f"{'x' * 190} {KEY} rejected"}},
    }
    body = f"data: {json.dumps(failed)}\n\n"

    def transport(*args: Any) -> tuple[int, str]:
        return 200, body

    with pytest.raises(sam.SamError) as raised:
        sam.segment(api_key=KEY, concept="water", image_data_url="x", transport=transport)

    assert raised.value.code == sam.ERROR_PROVIDER
    assert KEY not in raised.value.message and KEY[:10] not in raised.value.message
    detections, warnings = sam.parse_events(
        sam.extract_events(reply(one_object().replace("c=0.8", f"c=0.8;{KEY}=1"))), KEY
    )
    assert detections and warnings and all(KEY not in w for w in warnings)


def test_river_water_is_one_valid_concept_and_is_sent_as_the_prompt_text() -> None:
    assert sam.validate_concept("River water") == "river water"
    body = sam.build_request_body("river water", "data:image/jpeg;base64,AAAA")
    assert body["input"][0]["content"][0] == {"type": "input_text", "text": "river water"}

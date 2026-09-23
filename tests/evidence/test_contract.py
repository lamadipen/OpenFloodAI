from __future__ import annotations

import pytest

from openfloodai.evidence.contract import (
    EvidenceContractError,
    build_evidence_record,
    build_unavailable_evidence,
)


def test_available_record_carries_its_value() -> None:
    record = build_evidence_record(
        plugin_id="test-plugin",
        plugin_version="1.0.0",
        plugin_family="observation",
        site_id="site-1",
        camera_id="cam-1",
        timestamp="2026-06-18T00:00:00+00:00",
        evidence_type="region_pixel_change_score",
        status="available",
        value=0.42,
    )

    assert record.status == "available"
    assert record.value == 0.42
    as_dict = record.to_dict()
    assert as_dict["plugin_id"] == "test-plugin"
    assert as_dict["value"] == 0.42
    assert as_dict["contract_version"] == "v1"


def test_available_status_without_a_value_is_rejected() -> None:
    with pytest.raises(EvidenceContractError):
        build_evidence_record(
            plugin_id="test-plugin",
            plugin_version="1.0.0",
            plugin_family="observation",
            site_id="site-1",
            camera_id="cam-1",
            timestamp="2026-06-18T00:00:00+00:00",
            evidence_type="region_pixel_change_score",
            status="available",
            value=None,
        )


@pytest.mark.parametrize("status", ["disabled", "unavailable", "failed", "stale", "invalid"])
def test_non_available_status_cannot_carry_a_value(status: str) -> None:
    with pytest.raises(EvidenceContractError):
        build_evidence_record(
            plugin_id="test-plugin",
            plugin_version="1.0.0",
            plugin_family="observation",
            site_id="site-1",
            camera_id="cam-1",
            timestamp="2026-06-18T00:00:00+00:00",
            evidence_type="region_pixel_change_score",
            status=status,
            value=0.0,
        )


def test_unknown_plugin_family_is_rejected() -> None:
    with pytest.raises(EvidenceContractError):
        build_evidence_record(
            plugin_id="test-plugin",
            plugin_version="1.0.0",
            plugin_family="not-a-real-family",
            site_id="site-1",
            camera_id="cam-1",
            timestamp="2026-06-18T00:00:00+00:00",
            evidence_type="region_pixel_change_score",
            status="available",
            value=0.1,
        )


def test_build_unavailable_evidence_never_carries_a_value_or_confidence() -> None:
    record = build_unavailable_evidence(
        plugin_id="test-plugin",
        plugin_version="1.0.0",
        plugin_family="quality",
        site_id="site-1",
        camera_id="cam-1",
        evidence_type="camera_health_check",
        status="unavailable",
        reason_codes=("CAMERA_OFFLINE",),
    )

    assert record.value is None
    assert record.confidence is None
    assert record.status == "unavailable"
    assert record.reason_codes == ("CAMERA_OFFLINE",)


def test_build_unavailable_evidence_requires_a_reason_code() -> None:
    with pytest.raises(EvidenceContractError):
        build_unavailable_evidence(
            plugin_id="test-plugin",
            plugin_version="1.0.0",
            plugin_family="quality",
            site_id="site-1",
            camera_id="cam-1",
            evidence_type="camera_health_check",
            status="unavailable",
            reason_codes=(),
        )


def test_build_unavailable_evidence_rejects_available_status() -> None:
    with pytest.raises(EvidenceContractError):
        build_unavailable_evidence(
            plugin_id="test-plugin",
            plugin_version="1.0.0",
            plugin_family="quality",
            site_id="site-1",
            camera_id="cam-1",
            evidence_type="camera_health_check",
            status="available",
            reason_codes=("SOME_REASON",),
        )

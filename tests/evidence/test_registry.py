from __future__ import annotations

from openfloodai.evidence.contract import EvidenceRecord, build_evidence_record
from openfloodai.evidence.registry import check_capabilities, collect_evidence


class _WorkingAdapter:
    plugin_id = "working-adapter"
    plugin_version = "1.0.0"
    plugin_family = "observation"
    site_id = "site-1"
    camera_id = "cam-1"

    def check_ready(self) -> tuple[bool, str]:
        return True, "always ready"

    def collect(self) -> EvidenceRecord:
        return build_evidence_record(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            plugin_family=self.plugin_family,
            site_id=self.site_id,
            camera_id=self.camera_id,
            timestamp="2026-06-18T00:00:00+00:00",
            evidence_type="test_signal",
            status="available",
            value=1.0,
        )


class _NeverReadyAdapter:
    plugin_id = "never-ready-adapter"
    plugin_version = "1.0.0"
    plugin_family = "quality"
    site_id = "site-1"
    camera_id = "cam-1"

    def check_ready(self) -> tuple[bool, str]:
        return False, "dependency not configured"

    def collect(self) -> EvidenceRecord:
        raise AssertionError("collect() should not be called when unused in these tests")


class _RaisingCheckReadyAdapter:
    plugin_id = "raising-check-ready-adapter"
    plugin_version = "1.0.0"
    plugin_family = "context"
    site_id = "site-1"
    camera_id = "cam-1"

    def check_ready(self) -> tuple[bool, str]:
        raise RuntimeError("boom")

    def collect(self) -> EvidenceRecord:
        raise AssertionError("collect() should not be called in this test")


class _RaisingCollectAdapter:
    plugin_id = "raising-collect-adapter"
    plugin_version = "1.0.0"
    plugin_family = "observation"
    site_id = "site-2"
    camera_id = "cam-2"

    def check_ready(self) -> tuple[bool, str]:
        return True, "ready but will fail on collect"

    def collect(self) -> EvidenceRecord:
        raise RuntimeError("collection blew up")


class _BadMetadataRaisingAdapter:
    """An adapter whose declared plugin_family isn't a real one, and whose collect() fails.

    Exercises the case the review flagged: the fallback that builds a
    status="failed" record for a raising adapter must survive metadata
    that would itself fail the contract's validation, without raising
    into the caller's loop and blocking adapters after it.
    """

    plugin_id = "bad-metadata-adapter"
    plugin_version = "1.0.0"
    plugin_family = "not-a-real-family"
    site_id = "site-3"
    camera_id = "cam-3"

    def check_ready(self) -> tuple[bool, str]:
        return True, "ready"

    def collect(self) -> EvidenceRecord:
        raise RuntimeError("collect blew up with bad metadata")


class _AttributeAccessRaisesAdapter:
    """An adapter whose plugin_id property itself raises when read."""

    plugin_version = "1.0.0"
    plugin_family = "observation"

    @property
    def plugin_id(self) -> str:
        raise RuntimeError("boom-on-attribute-access")

    def check_ready(self) -> tuple[bool, str]:
        return True, "ready"

    def collect(self) -> EvidenceRecord:
        raise RuntimeError("never reached in these tests")


def test_check_capabilities_reports_each_adapter_independently() -> None:
    statuses = check_capabilities([_WorkingAdapter(), _NeverReadyAdapter()])

    assert [status.plugin_id for status in statuses] == [
        "working-adapter",
        "never-ready-adapter",
    ]
    assert statuses[0].ready is True
    assert statuses[1].ready is False
    assert statuses[1].reason == "dependency not configured"


def test_check_capabilities_isolates_a_raising_check_ready() -> None:
    statuses = check_capabilities([_WorkingAdapter(), _RaisingCheckReadyAdapter()])

    assert statuses[0].ready is True
    assert statuses[1].ready is False
    assert "RuntimeError" in statuses[1].reason
    assert "boom" in statuses[1].reason


def test_collect_evidence_returns_one_record_per_adapter_in_order() -> None:
    records = collect_evidence([_WorkingAdapter()])

    assert len(records) == 1
    assert records[0].plugin_id == "working-adapter"
    assert records[0].status == "available"
    assert records[0].value == 1.0


def test_collect_evidence_isolates_a_failing_adapter_from_a_working_one() -> None:
    records = collect_evidence([_WorkingAdapter(), _RaisingCollectAdapter()])

    assert len(records) == 2
    assert records[0].status == "available"
    assert records[0].value == 1.0

    failed = records[1]
    assert failed.plugin_id == "raising-collect-adapter"
    assert failed.status == "failed"
    assert failed.value is None
    assert failed.confidence is None
    assert failed.site_id == "site-2"
    assert failed.camera_id == "cam-2"
    assert any("RuntimeError" in code for code in failed.reason_codes)


def test_check_capabilities_survives_an_attribute_that_raises_on_access() -> None:
    # _AttributeAccessRaisesAdapter deliberately exposes plugin_id as a read-only
    # property (to simulate an attribute that raises on access), which doesn't
    # structurally satisfy the Protocol's settable-attribute shape -- the
    # mismatch is the point of this test, not a real typing bug.
    statuses = check_capabilities([_AttributeAccessRaisesAdapter(), _WorkingAdapter()])  # type: ignore[list-item]

    assert len(statuses) == 2
    assert statuses[0].plugin_id == "unknown"
    assert statuses[0].ready is True
    assert statuses[1].plugin_id == "working-adapter"
    assert statuses[1].ready is True


def test_collect_evidence_survives_an_adapter_with_an_invalid_plugin_family() -> None:
    """A raising adapter whose OWN metadata is invalid must not block later adapters."""

    records = collect_evidence([_WorkingAdapter(), _BadMetadataRaisingAdapter(), _WorkingAdapter()])

    assert len(records) == 3
    assert records[0].status == "available"

    failed = records[1]
    assert failed.status == "failed"
    assert failed.plugin_family == "observation"  # safe fallback, not the invalid value
    assert failed.value is None
    assert any("RuntimeError" in code for code in failed.reason_codes)

    # The adapter after the malformed one still ran and produced real evidence.
    assert records[2].status == "available"
    assert records[2].value == 1.0


def test_collect_evidence_survives_an_adapter_whose_metadata_access_itself_raises() -> None:
    records = collect_evidence([_AttributeAccessRaisesAdapter(), _WorkingAdapter()])  # type: ignore[list-item]

    assert len(records) == 2
    assert records[0].status == "failed"
    assert records[0].plugin_id == "unknown"
    assert records[1].status == "available"

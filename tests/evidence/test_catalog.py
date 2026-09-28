from __future__ import annotations

from openfloodai.evidence.catalog import KNOWN_ADAPTERS, default_enabled_by_id, known_adapter_ids


def test_known_adapters_have_unique_ids() -> None:
    ids = [adapter.plugin_id for adapter in KNOWN_ADAPTERS]
    assert len(ids) == len(set(ids))


def test_pixel_change_is_a_known_default_adapter() -> None:
    ids = known_adapter_ids()
    assert "pixel_change_region_v1" in ids

    defaults = default_enabled_by_id()
    assert defaults["pixel_change_region_v1"] is True

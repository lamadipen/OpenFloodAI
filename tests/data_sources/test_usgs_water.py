from __future__ import annotations

import pytest

from openfloodai.data_sources.usgs_water import USGSDataError, compute_flood_proximity


def test_normal_proximity() -> None:
    result = compute_flood_proximity(gage_height_ft=7.0, flood_stage_ft=10.0)
    assert result["flood_proximity_ratio"] == 0.7
    assert result["flood_proximity_state"] == "WATCH"


def test_above_flood() -> None:
    result = compute_flood_proximity(gage_height_ft=12.0, flood_stage_ft=10.0)
    assert result["flood_proximity_ratio"] == 1.2
    assert result["flood_proximity_state"] == "ABOVE_FLOOD"


def test_at_flood() -> None:
    result = compute_flood_proximity(gage_height_ft=9.6, flood_stage_ft=10.0)
    assert result["flood_proximity_state"] == "AT_FLOOD"


def test_near_flood() -> None:
    result = compute_flood_proximity(gage_height_ft=8.8, flood_stage_ft=10.0)
    assert result["flood_proximity_state"] == "NEAR_FLOOD"


def test_low_normal() -> None:
    result = compute_flood_proximity(gage_height_ft=3.0, flood_stage_ft=10.0)
    assert result["flood_proximity_state"] == "NORMAL"


def test_zero_flood_stage_raises() -> None:
    with pytest.raises(USGSDataError, match="positive"):
        compute_flood_proximity(gage_height_ft=5.0, flood_stage_ft=0.0)


def test_negative_flood_stage_raises() -> None:
    with pytest.raises(USGSDataError, match="positive"):
        compute_flood_proximity(gage_height_ft=5.0, flood_stage_ft=-1.0)


def test_record_has_contract_fields() -> None:
    result = compute_flood_proximity(gage_height_ft=5.0, flood_stage_ft=10.0)
    assert result["contract_version"] == "v1"
    assert result["record_type"] == "flood_proximity"
    assert "record_id" in result

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.config import (
    NormalWaterlineGuide,
    ReferenceRegion,
    SiteConfigError,
    WaterlinePoint,
    delete_normal_waterline_guide,
    invalidate_normal_waterline_guide,
    load_site_config,
    write_normal_waterline_guide,
    write_normal_waterline_guides,
    write_reference_region,
)


def write_config(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def valid_config_payload() -> dict[str, object]:
    return {
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "site_name": "Demo River Bridge",
        "public_location": "Demo River near Example Town",
        "input_type": "local_video",
        "reference_region": {
            "x": 0,
            "y": 50,
            "width": 100,
            "height": 50,
        },
        "privacy_notes": "Broad public location only.",
    }


def test_example_site_config_loads_successfully() -> None:
    config = load_site_config(Path("data/sites/example-site/configs/example-site.json"))

    assert config.site_id == "site-demo-01"
    assert config.camera_id == "camera-demo-01"
    assert config.site_name == "Demo River Bridge"
    assert config.public_location == "Demo River near Example Town"
    assert config.input_type == "local_video"
    assert config.reference_region == ReferenceRegion(x=0, y=50, width=100, height=50)


def test_public_location_is_optional(tmp_path: Path) -> None:
    payload = valid_config_payload()
    del payload["public_location"]

    config = load_site_config(write_config(tmp_path / "no-location.json", payload))

    assert config.public_location is None


def test_required_fields_are_enforced(tmp_path: Path) -> None:
    payload = valid_config_payload()
    del payload["site_name"]

    config_path = write_config(tmp_path / "missing-site-name.json", payload)

    with pytest.raises(SiteConfigError, match="site_name"):
        load_site_config(config_path)


@pytest.mark.parametrize("field_name", ["site_id", "camera_id"])
def test_empty_identifiers_fail_clearly(tmp_path: Path, field_name: str) -> None:
    payload = valid_config_payload()
    payload[field_name] = " "

    config_path = write_config(tmp_path / f"empty-{field_name}.json", payload)

    with pytest.raises(SiteConfigError, match=field_name):
        load_site_config(config_path)


def test_reference_region_must_fit_inside_image_area(tmp_path: Path) -> None:
    payload = valid_config_payload()
    payload["reference_region"] = {
        "x": 80,
        "y": 50,
        "width": 30,
        "height": 50,
    }

    config_path = write_config(tmp_path / "bad-region.json", payload)

    with pytest.raises(SiteConfigError, match="0-100 image area"):
        load_site_config(config_path)


def test_reference_region_is_optional(tmp_path: Path) -> None:
    payload = valid_config_payload()
    del payload["reference_region"]

    config_path = write_config(tmp_path / "no-region.json", payload)

    assert load_site_config(config_path).reference_region is None


def test_write_reference_region_updates_only_watched_area(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "site.json", valid_config_payload())

    write_reference_region(
        config_path,
        {"x": 12.5, "y": 35, "width": 60, "height": 40},
    )

    config = load_site_config(config_path)
    assert config.site_id == "site-demo-01"
    assert config.reference_region == ReferenceRegion(x=12.5, y=35, width=60, height=40)


def test_write_reference_region_rejects_area_outside_frame(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "site.json", valid_config_payload())

    with pytest.raises(SiteConfigError, match="0-100 image area"):
        write_reference_region(
            config_path,
            {"x": 80, "y": 50, "width": 30, "height": 50},
        )


def normal_waterline_guide_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "left_bank_normal_waterline",
        "label": "left bank normal waterline",
        "status": "draft",
        "points": [{"x": 10, "y": 55}, {"x": 20, "y": 60}, {"x": 30, "y": 62}],
        "video_id": "practice-01",
        "video_time_seconds": 4.5,
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "normal_condition": True,
        "notes": "Clear view of the bridge pillar.",
    }
    payload.update(overrides)
    return payload


def site_with_watched_area(tmp_path: Path, name: str = "site.json") -> Path:
    return write_config(tmp_path / name, valid_config_payload())


def test_write_normal_waterline_guide_saves_draft(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_normal_waterline_guide(config_path, normal_waterline_guide_payload())

    assert saved.status == "draft"
    assert saved.confirmed_at is None
    config = load_site_config(config_path)
    assert config.normal_waterline_guides == (saved,)
    assert config.reference_region == ReferenceRegion(x=0, y=50, width=100, height=50)


def test_write_normal_waterline_guide_confirmed_sets_confirmed_at(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_normal_waterline_guide(
        config_path, normal_waterline_guide_payload(status="confirmed")
    )

    assert saved.status == "confirmed"
    assert saved.confirmed_at is not None


def test_write_normal_waterline_guide_stores_points(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_normal_waterline_guide(config_path, normal_waterline_guide_payload())

    assert saved.points == (
        WaterlinePoint(x=10, y=55),
        WaterlinePoint(x=20, y=60),
        WaterlinePoint(x=30, y=62),
    )


def test_write_normal_waterline_guide_accepts_an_image_sequence_source(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_normal_waterline_guide(
        config_path,
        normal_waterline_guide_payload(
            video_id="",
            video_time_seconds=0,
            image_sequence_id="usgs-camera-demo-01-2026-09-01-2026-09-01",
            image_filename="camera-demo-01___2026-09-01T09-00-00Z.jpg",
        ),
    )

    assert saved.video_id == ""
    assert saved.image_sequence_id == "usgs-camera-demo-01-2026-09-01-2026-09-01"
    assert saved.image_filename == "camera-demo-01___2026-09-01T09-00-00Z.jpg"
    config = load_site_config(config_path)
    assert config.normal_waterline_guides == (saved,)


def test_write_normal_waterline_guide_rejects_both_video_and_image_source(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="exactly one source"):
        write_normal_waterline_guide(
            config_path,
            normal_waterline_guide_payload(
                image_sequence_id="usgs-camera-demo-01-2026-09-01-2026-09-01",
                image_filename="camera-demo-01___2026-09-01T09-00-00Z.jpg",
            ),
        )


def test_write_normal_waterline_guide_rejects_neither_video_nor_image_source(
    tmp_path: Path,
) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="exactly one source"):
        write_normal_waterline_guide(
            config_path, normal_waterline_guide_payload(video_id="", video_time_seconds=0)
        )


def test_write_normal_waterline_guide_rejects_only_one_image_field(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="must both be set or both be empty"):
        write_normal_waterline_guide(
            config_path,
            normal_waterline_guide_payload(
                video_id="",
                video_time_seconds=0,
                image_sequence_id="usgs-camera-demo-01-2026-09-01-2026-09-01",
            ),
        )


def test_write_normal_waterline_guide_requires_existing_watched_area(tmp_path: Path) -> None:
    payload = valid_config_payload()
    del payload["reference_region"]
    config_path = write_config(tmp_path / "no-watched-area.json", payload)

    with pytest.raises(SiteConfigError, match="watched area"):
        write_normal_waterline_guide(config_path, normal_waterline_guide_payload())


def test_write_normal_waterline_guide_rejects_point_outside_watched_area(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="fit inside the watched area"):
        write_normal_waterline_guide(
            config_path,
            normal_waterline_guide_payload(points=[{"x": 0, "y": 0}, {"x": 10, "y": 10}]),
        )


def test_write_normal_waterline_guide_rejects_fewer_than_two_points(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="at least 2 points"):
        write_normal_waterline_guide(
            config_path,
            normal_waterline_guide_payload(points=[{"x": 10, "y": 55}]),
        )


def test_write_normal_waterline_guide_rejects_empty_label(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="label"):
        write_normal_waterline_guide(config_path, normal_waterline_guide_payload(label=" "))


def test_write_normal_waterline_guide_rejects_invalid_status_value(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="'draft' or 'confirmed'"):
        write_normal_waterline_guide(config_path, normal_waterline_guide_payload(status="invalid"))


def test_write_normal_waterline_guide_upserts_by_id(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_normal_waterline_guide(config_path, normal_waterline_guide_payload())

    updated = write_normal_waterline_guide(
        config_path,
        normal_waterline_guide_payload(points=[{"x": 15, "y": 56}, {"x": 25, "y": 61}]),
    )

    config = load_site_config(config_path)
    assert config.normal_waterline_guides == (updated,)


def test_write_normal_waterline_guide_appends_a_second_guide(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    first = write_normal_waterline_guide(config_path, normal_waterline_guide_payload())

    second = write_normal_waterline_guide(
        config_path,
        normal_waterline_guide_payload(
            id="right_bank_normal_waterline", label="right bank normal waterline"
        ),
    )

    config = load_site_config(config_path)
    assert config.normal_waterline_guides == (first, second)


def test_load_rejects_duplicate_guide_ids(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    guide = normal_waterline_guide_payload()
    guide.update({"confirmed_at": None, "invalidated_at": None, "invalidation_reason": None})
    raw_config["normal_waterline_guides"] = [guide, guide]
    config_path.write_text(json.dumps(raw_config), encoding="utf-8")

    with pytest.raises(SiteConfigError, match="Duplicate"):
        load_site_config(config_path)


def test_invalidate_normal_waterline_guide_sets_status_and_reason(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_normal_waterline_guide(config_path, normal_waterline_guide_payload(status="confirmed"))

    invalidated = invalidate_normal_waterline_guide(
        config_path, "left_bank_normal_waterline", "camera_moved", "Tilted after storm."
    )

    assert invalidated.status == "invalid"
    assert invalidated.invalidation_reason == "camera_moved"
    assert invalidated.invalidated_at is not None
    assert invalidated.notes == "Tilted after storm."
    config = load_site_config(config_path)
    assert config.normal_waterline_guides == (invalidated,)


def test_invalidate_normal_waterline_guide_requires_existing_record(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="no normal waterline guide"):
        invalidate_normal_waterline_guide(config_path, "left_bank_normal_waterline", "camera_moved")


def test_invalidate_normal_waterline_guide_rejects_unknown_id(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_normal_waterline_guide(config_path, normal_waterline_guide_payload(status="confirmed"))

    with pytest.raises(SiteConfigError, match="no normal waterline guide"):
        invalidate_normal_waterline_guide(
            config_path, "right_bank_normal_waterline", "camera_moved"
        )


def test_invalidate_normal_waterline_guide_rejects_bad_reason(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_normal_waterline_guide(config_path, normal_waterline_guide_payload(status="confirmed"))

    with pytest.raises(SiteConfigError, match="Invalidation reason"):
        invalidate_normal_waterline_guide(
            config_path, "left_bank_normal_waterline", "not_a_real_reason"
        )


def test_invalidate_normal_waterline_guide_preserves_other_guides(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_normal_waterline_guide(config_path, normal_waterline_guide_payload(status="confirmed"))
    other = write_normal_waterline_guide(
        config_path,
        normal_waterline_guide_payload(
            id="right_bank_normal_waterline",
            label="right bank normal waterline",
            status="confirmed",
        ),
    )

    invalidate_normal_waterline_guide(config_path, "left_bank_normal_waterline", "camera_moved")

    config = load_site_config(config_path)
    assert len(config.normal_waterline_guides) == 2
    assert other in config.normal_waterline_guides


def test_resaving_after_invalidation_creates_a_fresh_record(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_normal_waterline_guide(config_path, normal_waterline_guide_payload(status="confirmed"))
    invalidate_normal_waterline_guide(config_path, "left_bank_normal_waterline", "bank_changed")

    fresh: NormalWaterlineGuide = write_normal_waterline_guide(
        config_path,
        normal_waterline_guide_payload(status="draft", notes="New bank line chosen."),
    )

    assert fresh.status == "draft"
    assert fresh.invalidated_at is None
    assert fresh.invalidation_reason is None
    assert fresh.notes == "New bank line chosen."


def test_write_normal_waterline_guides_saves_multiple_in_one_call(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_normal_waterline_guides(
        config_path,
        [
            normal_waterline_guide_payload(status="confirmed"),
            normal_waterline_guide_payload(
                id="right_bank_normal_waterline",
                label="right bank normal waterline",
                status="draft",
            ),
        ],
    )

    assert [guide.id for guide in saved] == [
        "left_bank_normal_waterline",
        "right_bank_normal_waterline",
    ]
    config = load_site_config(config_path)
    assert {guide.id: guide.status for guide in config.normal_waterline_guides} == {
        "left_bank_normal_waterline": "confirmed",
        "right_bank_normal_waterline": "draft",
    }


def test_write_normal_waterline_guides_preserves_guides_not_in_the_batch(
    tmp_path: Path,
) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_normal_waterline_guide(config_path, normal_waterline_guide_payload(status="confirmed"))

    write_normal_waterline_guides(
        config_path,
        [
            normal_waterline_guide_payload(
                id="right_bank_normal_waterline",
                label="right bank normal waterline",
                status="draft",
            )
        ],
    )

    config = load_site_config(config_path)
    assert {guide.id for guide in config.normal_waterline_guides} == {
        "left_bank_normal_waterline",
        "right_bank_normal_waterline",
    }


def test_write_normal_waterline_guides_rejects_duplicate_ids_in_the_batch(
    tmp_path: Path,
) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="Duplicate"):
        write_normal_waterline_guides(
            config_path,
            [normal_waterline_guide_payload(), normal_waterline_guide_payload()],
        )


def test_write_normal_waterline_guides_accepts_invalid_status_with_reason(
    tmp_path: Path,
) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_normal_waterline_guides(
        config_path,
        [normal_waterline_guide_payload(status="invalid", invalidation_reason="camera_moved")],
    )

    assert saved[0].status == "invalid"
    assert saved[0].invalidation_reason == "camera_moved"
    assert saved[0].invalidated_at is not None
    assert saved[0].confirmed_at is None


def test_write_normal_waterline_guides_invalid_preserves_prior_confirmed_at(
    tmp_path: Path,
) -> None:
    config_path = site_with_watched_area(tmp_path)
    confirmed = write_normal_waterline_guide(
        config_path, normal_waterline_guide_payload(status="confirmed")
    )

    invalidated = write_normal_waterline_guides(
        config_path,
        [normal_waterline_guide_payload(status="invalid", invalidation_reason="bank_changed")],
    )

    assert invalidated[0].confirmed_at == confirmed.confirmed_at


def test_write_normal_waterline_guides_rejects_invalid_status_without_reason(
    tmp_path: Path,
) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="invalidation_reason"):
        write_normal_waterline_guides(
            config_path, [normal_waterline_guide_payload(status="invalid")]
        )


def test_delete_normal_waterline_guide_removes_only_that_guide(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_normal_waterline_guide(config_path, normal_waterline_guide_payload(status="confirmed"))
    write_normal_waterline_guide(
        config_path,
        normal_waterline_guide_payload(
            id="right_bank_normal_waterline", label="right bank normal waterline"
        ),
    )

    delete_normal_waterline_guide(config_path, "left_bank_normal_waterline")

    config = load_site_config(config_path)
    assert [guide.id for guide in config.normal_waterline_guides] == ["right_bank_normal_waterline"]


def test_delete_normal_waterline_guide_leaves_no_trace(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_normal_waterline_guide(config_path, normal_waterline_guide_payload(status="confirmed"))

    delete_normal_waterline_guide(config_path, "left_bank_normal_waterline")

    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw_config["normal_waterline_guides"] == []


def test_delete_normal_waterline_guide_rejects_unknown_id(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="no normal waterline guide"):
        delete_normal_waterline_guide(config_path, "left_bank_normal_waterline")


def test_example_config_does_not_commit_private_fields() -> None:
    payload = json.loads(
        Path("data/sites/example-site/configs/example-site.json").read_text(encoding="utf-8")
    )
    text = json.dumps(payload).lower()

    private_terms = [
        "gps",
        "latitude",
        "longitude",
        "rtsp://",
        "http://",
        "https://",
        "password",
        "secret",
        "token",
        "phone",
        "email",
    ]

    assert all(term not in text for term in private_terms)

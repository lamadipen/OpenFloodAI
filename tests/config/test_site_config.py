from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.config import (
    ConfirmedReference,
    ConfirmedReferenceMarker,
    ReferenceRegion,
    SiteConfigError,
    invalidate_confirmed_reference,
    load_site_config,
    write_confirmed_reference,
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


def confirmed_reference_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "draft",
        "region": {"x": 10, "y": 55, "width": 20, "height": 15},
        "video_id": "practice-01",
        "video_time_seconds": 4.5,
        "site_id": "site-demo-01",
        "camera_id": "camera-demo-01",
        "normal_condition": True,
        "notes": "Clear view of the bridge pillar.",
        "markers": [],
    }
    payload.update(overrides)
    return payload


def site_with_watched_area(tmp_path: Path, name: str = "site.json") -> Path:
    return write_config(tmp_path / name, valid_config_payload())


def test_write_confirmed_reference_saves_draft(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_confirmed_reference(config_path, confirmed_reference_payload())

    assert saved.status == "draft"
    assert saved.confirmed_at is None
    config = load_site_config(config_path)
    assert config.confirmed_reference == saved
    assert config.reference_region == ReferenceRegion(x=0, y=50, width=100, height=50)


def test_write_confirmed_reference_confirmed_sets_confirmed_at(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_confirmed_reference(config_path, confirmed_reference_payload(status="confirmed"))

    assert saved.status == "confirmed"
    assert saved.confirmed_at is not None


def test_write_confirmed_reference_with_markers(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_confirmed_reference(
        config_path,
        confirmed_reference_payload(
            markers=[
                {"label": "bridge pillar", "region": {"x": 5, "y": 60, "width": 5, "height": 5}},
            ]
        ),
    )

    assert saved.markers == (
        ConfirmedReferenceMarker(
            label="bridge pillar",
            region=ReferenceRegion(x=5, y=60, width=5, height=5),
        ),
    )


def test_write_confirmed_reference_requires_existing_watched_area(tmp_path: Path) -> None:
    payload = valid_config_payload()
    del payload["reference_region"]
    config_path = write_config(tmp_path / "no-watched-area.json", payload)

    with pytest.raises(SiteConfigError, match="watched area"):
        write_confirmed_reference(config_path, confirmed_reference_payload())


def test_write_confirmed_reference_rejects_region_outside_watched_area(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="fit inside the site's watched area"):
        write_confirmed_reference(
            config_path,
            confirmed_reference_payload(region={"x": 0, "y": 0, "width": 20, "height": 15}),
        )


def test_write_confirmed_reference_rejects_marker_outside_watched_area(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="must fit inside the site's watched area"):
        write_confirmed_reference(
            config_path,
            confirmed_reference_payload(
                markers=[
                    {"label": "rock", "region": {"x": 0, "y": 0, "width": 5, "height": 5}},
                ]
            ),
        )


def test_write_confirmed_reference_rejects_empty_marker_label(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="label"):
        write_confirmed_reference(
            config_path,
            confirmed_reference_payload(
                markers=[{"label": " ", "region": {"x": 5, "y": 60, "width": 5, "height": 5}}]
            ),
        )


def test_write_confirmed_reference_rejects_invalid_status_value(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="'draft' or 'confirmed'"):
        write_confirmed_reference(config_path, confirmed_reference_payload(status="invalid"))


def test_write_confirmed_reference_defaults_to_manual_origin(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_confirmed_reference(config_path, confirmed_reference_payload())

    assert saved.origin == "manual"


def test_write_confirmed_reference_accepts_machine_suggested_origin(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    saved = write_confirmed_reference(
        config_path, confirmed_reference_payload(origin="machine_suggested")
    )

    assert saved.origin == "machine_suggested"
    config = load_site_config(config_path)
    assert config.confirmed_reference is not None
    assert config.confirmed_reference.origin == "machine_suggested"


def test_write_confirmed_reference_rejects_invalid_origin(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="origin"):
        write_confirmed_reference(config_path, confirmed_reference_payload(origin="ml_model"))


def test_load_confirmed_reference_without_origin_defaults_to_manual(tmp_path: Path) -> None:
    # Models a real record saved before OF-086 introduced `origin` — it must
    # keep loading rather than failing on a field it predates.
    config_path = site_with_watched_area(tmp_path)
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    raw_confirmed_reference = confirmed_reference_payload()
    raw_confirmed_reference.update(
        {"confirmed_at": None, "invalidated_at": None, "invalidation_reason": None}
    )
    assert "origin" not in raw_confirmed_reference
    raw_config["confirmed_reference"] = raw_confirmed_reference
    config_path.write_text(json.dumps(raw_config), encoding="utf-8")

    config = load_site_config(config_path)

    assert config.confirmed_reference is not None
    assert config.confirmed_reference.origin == "manual"


def test_invalidate_confirmed_reference_sets_status_and_reason(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_confirmed_reference(config_path, confirmed_reference_payload(status="confirmed"))

    invalidated = invalidate_confirmed_reference(config_path, "camera_moved", "Tilted after storm.")

    assert invalidated.status == "invalid"
    assert invalidated.invalidation_reason == "camera_moved"
    assert invalidated.invalidated_at is not None
    assert invalidated.notes == "Tilted after storm."
    config = load_site_config(config_path)
    assert config.confirmed_reference == invalidated


def test_invalidate_confirmed_reference_requires_existing_record(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)

    with pytest.raises(SiteConfigError, match="no confirmed reference"):
        invalidate_confirmed_reference(config_path, "camera_moved")


def test_invalidate_confirmed_reference_rejects_bad_reason(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_confirmed_reference(config_path, confirmed_reference_payload(status="confirmed"))

    with pytest.raises(SiteConfigError, match="Invalidation reason"):
        invalidate_confirmed_reference(config_path, "not_a_real_reason")


def test_invalidate_confirmed_reference_preserves_origin(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_confirmed_reference(
        config_path,
        confirmed_reference_payload(status="confirmed", origin="machine_suggested"),
    )

    invalidated = invalidate_confirmed_reference(config_path, "camera_moved")

    assert invalidated.origin == "machine_suggested"
    config = load_site_config(config_path)
    assert config.confirmed_reference is not None
    assert config.confirmed_reference.origin == "machine_suggested"


def test_resaving_after_invalidation_creates_a_fresh_record(tmp_path: Path) -> None:
    config_path = site_with_watched_area(tmp_path)
    write_confirmed_reference(config_path, confirmed_reference_payload(status="confirmed"))
    invalidate_confirmed_reference(config_path, "bank_changed")

    fresh: ConfirmedReference = write_confirmed_reference(
        config_path, confirmed_reference_payload(status="draft", notes="New bank line chosen.")
    )

    assert fresh.status == "draft"
    assert fresh.invalidated_at is None
    assert fresh.invalidation_reason is None
    assert fresh.notes == "New bank line chosen."


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

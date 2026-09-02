from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.config import ReferenceRegion, SiteConfigError, load_site_config


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
    configs = load_site_config(Path("configs/example-site.json"))
    assert len(configs) == 1
    config = configs[0]

    assert config.site_id == "site-demo-01"
    assert config.camera_id == "camera-demo-01"
    assert config.site_name == "Demo River Bridge"
    assert config.public_location == "Demo River near Example Town"
    assert config.input_type == "local_video"
    assert config.reference_region == ReferenceRegion(x=0, y=50, width=100, height=50)


def test_single_object_json_auto_wrapped(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "single.json", valid_config_payload())
    configs = load_site_config(config_path)
    assert len(configs) == 1
    assert configs[0].site_id == "site-demo-01"


def test_required_fields_are_enforced(tmp_path: Path) -> None:
    payload = valid_config_payload()
    del payload["site_id"]

    config_path = write_config(tmp_path / "missing-field.json", payload)

    with pytest.raises(SiteConfigError, match="site_id"):
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

    assert load_site_config(config_path)[0].reference_region is None


def test_example_config_does_not_commit_private_fields() -> None:
    payload = json.loads(Path("configs/example-site.json").read_text(encoding="utf-8"))
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


def test_unsupported_fields_rejected(tmp_path: Path) -> None:
    payload = valid_config_payload()
    payload["bad_field"] = "x"

    config_path = write_config(tmp_path / "bad-field.json", payload)

    with pytest.raises(SiteConfigError, match="unsupported"):
        load_site_config(config_path)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfloodai.ingestion import river_images as river
from openfloodai.ingestion import river_registry
from openfloodai.ingestion import usgs_gage_data as gage
from openfloodai.ingestion.river_bootstrap import (
    preview_bootstrap_run,
    run_bootstrap,
    select_cameras,
)

SLUG_A = "TEST_CAMERA_A"
SLUG_B = "TEST_CAMERA_B"


def _registry_payload() -> dict[str, object]:
    def camera(camera_id: str, folder_name: str) -> dict[str, object]:
        return {
            "river_id": "test-river",
            "camera_id": camera_id,
            "nwis_id": "09999999",
            "state": "CO",
            "latitude": 40.0,
            "longitude": -105.0,
            "display_name": camera_id,
            "folder_name": folder_name,
            "gage_relationship": "same_site",
            "timezone": "America/Denver",
        }

    return {
        "river_id": "test-river",
        "display_name": "Test River",
        "source": "https://example.invalid",
        "notes": "One hidden camera excluded.",
        "cameras": [camera(SLUG_A, "test-river-a"), camera(SLUG_B, "test-river-b")],
    }


@pytest.fixture
def reference_dir(tmp_path: Path) -> Path:
    reference_dir = tmp_path / "reference"
    rivers_dir = reference_dir / "rivers"
    rivers_dir.mkdir(parents=True)
    (rivers_dir / "test-river.json").write_text(json.dumps(_registry_payload()), encoding="utf-8")
    return reference_dir


def _key(slug: str, timestamp: str) -> str:
    return f"720/{slug}/{slug}___{timestamp}.jpg"


def _listing_xml(slug: str, entries: list[tuple[str, int]]) -> bytes:
    contents = "".join(
        f"<Contents><Key>{_key(slug, timestamp)}</Key><Size>{size}</Size></Contents>"
        for timestamp, size in entries
    )
    return (
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"{contents}<IsTruncated>false</IsTruncated></ListBucketResult>"
    ).encode()


def test_select_cameras_returns_all_when_none_named(reference_dir: Path) -> None:
    registry = river_registry.load_river_registry("test-river", reference_dir)
    assert [c.camera_id for c in select_cameras(registry, [])] == [SLUG_A, SLUG_B]


def test_select_cameras_filters_and_rejects_unknown(reference_dir: Path) -> None:
    registry = river_registry.load_river_registry("test-river", reference_dir)
    assert [c.camera_id for c in select_cameras(registry, [SLUG_B])] == [SLUG_B]
    with pytest.raises(ValueError, match="Unknown camera id"):
        select_cameras(registry, ["NOT_A_CAMERA"])


def test_preview_bootstrap_run_reports_counts_and_would_create(
    reference_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page_a = _listing_xml(SLUG_A, [("2026-09-01T18-00-00Z", 100)])
    page_b = _listing_xml(SLUG_B, [("2026-09-01T21-00-00Z", 100)])

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        if SLUG_A in url:
            return page_a, "application/xml"
        return page_b, "application/xml"

    monkeypatch.setattr(river, "_fetch", fetch)
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    preview = preview_bootstrap_run(
        reference_dir=reference_dir,
        sites_base_dir=sites_dir,
        river_id="test-river",
        camera_ids=[],
        start_date="2026-09-01",
        end_date="2026-09-01",
        sampling_mode="one_daylight_image_per_day",
    )

    assert preview.excluded_cameras_note == "One hidden camera excluded."
    by_id = {c.camera_id: c for c in preview.cameras}
    assert by_id[SLUG_A].daylight_images_available == 1
    assert by_id[SLUG_A].site_status == "would_create"
    # 21:00 UTC in America/Denver (-06:00 in September) is 15:00 local, just
    # outside the default 10:00-14:00 window -> no daylight image available.
    assert by_id[SLUG_B].daylight_images_available == 0


def test_run_bootstrap_creates_sites_downloads_images_and_writes_gage_summary(
    reference_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jpeg = b"\xff\xd8\xff\xe0test\xff\xd9"
    page_a = _listing_xml(SLUG_A, [("2026-09-01T18-00-00Z", 100)])
    page_b = _listing_xml(SLUG_B, [("2026-09-01T18-30-00Z", 100)])

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        if "?" in url:
            return (page_a, "application/xml") if SLUG_A in url else (page_b, "application/xml")
        return jpeg, "image/jpeg"

    monkeypatch.setattr(river, "_fetch", fetch)
    monkeypatch.setattr(gage, "_fetch_json", lambda url: {"value": {"timeSeries": []}})
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()

    outcomes = run_bootstrap(
        reference_dir=reference_dir,
        sites_base_dir=sites_dir,
        river_id="test-river",
        camera_ids=[],
        start_date="2026-09-01",
        end_date="2026-09-01",
        sampling_mode="one_daylight_image_per_day",
    )

    assert {o.camera_id for o in outcomes} == {SLUG_A, SLUG_B}
    for outcome in outcomes:
        assert outcome.site_status == "created"
        assert outcome.downloaded_count == 1
        assert outcome.error is None
        assert outcome.gage_available is False  # empty series -> unavailable, but no crash
    site_dir = sites_dir / "test-river-a"
    assert (site_dir / "configs" / "test-river-a.json").is_file()
    sequence_dirs = list((site_dir / "inputs" / "image-sequences").iterdir())
    assert len(sequence_dirs) == 1
    assert (sequence_dirs[0] / "gauge-readings-summary.json").is_file()


def test_run_bootstrap_reuses_the_existing_sites_own_site_id_for_downloaded_records(
    reference_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jpeg = b"\xff\xd8\xff\xe0test\xff\xd9"
    page_a = _listing_xml(SLUG_A, [("2026-09-01T18-00-00Z", 100)])

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        if "?" in url:
            return page_a, "application/xml"
        return jpeg, "image/jpeg"

    monkeypatch.setattr(river, "_fetch", fetch)
    monkeypatch.setattr(gage, "_fetch_json", lambda url: {"value": {"timeSeries": []}})
    sites_dir = tmp_path / "sites"
    reused_site = sites_dir / "test-river-a"
    (reused_site / "configs").mkdir(parents=True)
    (reused_site / "configs" / "test-river-a.json").write_text(
        json.dumps(
            {
                "site_id": "a-hand-picked-trusted-site-id",
                "camera_id": SLUG_A,
                "site_name": "Test Camera A",
                "input_type": "local_video",
            }
        ),
        encoding="utf-8",
    )

    outcomes = run_bootstrap(
        reference_dir=reference_dir,
        sites_base_dir=sites_dir,
        river_id="test-river",
        camera_ids=[SLUG_A],
        start_date="2026-09-01",
        end_date="2026-09-01",
        sampling_mode="one_daylight_image_per_day",
    )

    outcome = next(o for o in outcomes if o.camera_id == SLUG_A)
    assert outcome.site_status == "reused"
    assert outcome.error is None
    sequence_dirs = list((reused_site / "inputs" / "image-sequences").iterdir())
    manifest = json.loads(
        (sequence_dirs[0] / "sequence-manifest.jsonl").read_text().splitlines()[0]
    )
    assert manifest["site_id"] == "a-hand-picked-trusted-site-id"


def test_run_bootstrap_conflict_on_one_camera_does_not_block_the_other(
    reference_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jpeg = b"\xff\xd8\xff\xe0test\xff\xd9"
    page_b = _listing_xml(SLUG_B, [("2026-09-01T18-30-00Z", 100)])

    def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        if "?" in url:
            return page_b, "application/xml"
        return jpeg, "image/jpeg"

    monkeypatch.setattr(river, "_fetch", fetch)
    monkeypatch.setattr(gage, "_fetch_json", lambda url: {"value": {"timeSeries": []}})
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    conflicting_site = sites_dir / "test-river-a"
    (conflicting_site / "configs").mkdir(parents=True)
    (conflicting_site / "configs" / "test-river-a.json").write_text(
        json.dumps(
            {
                "site_id": "other_sid",
                "camera_id": "SOME_OTHER_CAMERA",
                "site_name": "Other",
                "input_type": "local_video",
            }
        ),
        encoding="utf-8",
    )

    outcomes = run_bootstrap(
        reference_dir=reference_dir,
        sites_base_dir=sites_dir,
        river_id="test-river",
        camera_ids=[],
        start_date="2026-09-01",
        end_date="2026-09-01",
        sampling_mode="one_daylight_image_per_day",
    )

    by_id = {o.camera_id: o for o in outcomes}
    assert by_id[SLUG_A].site_status == "conflict"
    assert by_id[SLUG_A].downloaded_count == 0
    assert by_id[SLUG_B].site_status == "created"
    assert by_id[SLUG_B].downloaded_count == 1

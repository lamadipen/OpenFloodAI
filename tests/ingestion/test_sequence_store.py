from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from openfloodai.ingestion import sequence_store as store


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   \t ", None),  # whitespace only means "use the generated default"
        ("Windy Gap 2026", "Windy Gap 2026"),
        ("  Windy   Gap   2026 ", "Windy Gap 2026"),
        (
            "<script>alert(1)</script>",
            "<script>alert(1)</script>",
        ),  # stored as text, escaped on display
        ("../../etc/passwd", "../../etc/passwd"),  # never used as a path
        ("Rivière é 雨", "Rivière é 雨"),
    ],
)
def test_display_names_are_cleaned_but_never_used_as_paths(
    raw: object, expected: str | None
) -> None:
    assert store.validate_display_name(raw) == expected


@pytest.mark.parametrize(
    "bad", ["line\nbreak", "tab\there", "nul\x00", "bell\x07", "x" * 81, 123, ["a"]]
)
def test_invalid_display_names_are_rejected(bad: object) -> None:
    with pytest.raises(store.SequenceStoreError):
        store.validate_display_name(bad)


def test_the_longest_allowed_name_is_accepted() -> None:
    assert store.validate_display_name("n" * 80) == "n" * 80


def test_label_falls_back_to_the_unique_id() -> None:
    assert (
        store.sequence_label("usgs-x-water_level-0a1b2c3d", None) == "usgs-x-water_level-0a1b2c3d"
    )
    assert store.sequence_label("usgs-x", "My name") == "My name"


def test_display_name_is_metadata_beside_the_sequence(tmp_path: Path) -> None:
    assert store.read_display_name(tmp_path) is None
    store.write_display_name(tmp_path, "Windy Gap", "2026-10-06T00:00:00+00:00")
    assert store.read_display_name(tmp_path) == "Windy Gap"
    (tmp_path / store.SEQUENCE_META_FILENAME).write_text("not json")
    assert store.read_display_name(tmp_path) is None


def test_atomic_writes_never_leave_a_partial_file(tmp_path: Path) -> None:
    target = tmp_path / "file.json"
    store.atomic_write_json(target, {"a": 1})
    before = target.read_bytes()

    class Boom:
        def __iter__(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("serialization failed")

    with pytest.raises(TypeError):
        store.atomic_write_json(target, {"bad": Boom()})
    assert target.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["file.json"]  # no temp files left


def test_batches_are_numbered_immutable_and_read_oldest_first(tmp_path: Path) -> None:
    assert store.next_batch_number(tmp_path) == 1
    store.write_batch(tmp_path, 1, {"samples": [{"filename": "a.jpg", "group": "low"}]})
    store.write_batch(
        tmp_path,
        2,
        {
            "samples": [
                {"filename": "a.jpg", "group": "high"},
                {"filename": "b.jpg", "group": "high"},
            ]
        },
    )
    assert store.next_batch_number(tmp_path) == 3
    with pytest.raises(store.SequenceStoreError):
        store.write_batch(tmp_path, 1, {"samples": []})

    batches = store.read_batches(tmp_path)
    assert [b["batch_number"] for b in batches] == [1, 2]
    found = store.samples_by_filename(batches)
    # an image belongs to the batch that first added it; a later batch cannot recategorize it
    assert found["a.jpg"]["group"] == "low" and found["a.jpg"]["batch_number"] == 1
    assert found["b.jpg"]["group"] == "high" and found["b.jpg"]["batch_number"] == 2


def test_the_legacy_single_selection_file_reads_as_batch_zero(tmp_path: Path) -> None:
    (tmp_path / store.LEGACY_SELECTION_FILENAME).write_text(
        json.dumps({"samples": [{"filename": "old.jpg", "group": "middle"}]})
    )
    store.write_batch(tmp_path, 1, {"samples": [{"filename": "new.jpg", "group": "low"}]})

    batches = store.read_batches(tmp_path)

    assert [b["batch_number"] for b in batches] == [0, 1]
    assert set(store.samples_by_filename(batches)) == {"old.jpg", "new.jpg"}


def test_the_sequence_lock_excludes_other_holders_and_times_out(tmp_path: Path) -> None:
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with store.sequence_lock(tmp_path):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(5)
    started = time.monotonic()
    with pytest.raises(store.SequenceBusyError), store.sequence_lock(tmp_path, timeout=0.3):
        pass
    assert time.monotonic() - started < 2
    release.set()
    thread.join(5)
    with store.sequence_lock(tmp_path, timeout=1):  # free again
        pass

"""Shared storage rules for image sequences (Issue #214 / OF-093).

Small, dependency-free helpers used by water-level intake and by validation runs:

- atomic file writes, so a crash never leaves a half-written manifest or summary;
- a per-sequence lock, so an append and the start of a validation run never
  interleave (a run must see one consistent snapshot of the sequence);
- the optional display name, kept as metadata beside the sequence. It is never a
  path component and never replaces the unique sequence ID;
- per-batch sampling provenance (`sampling-batches/`), one immutable file per
  download batch, plus the legacy single `water-level-selection.json`.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:  # POSIX only; the in-process lock below still covers a single running app.
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

SEQUENCE_META_FILENAME = "sequence-meta.json"
BATCHES_DIRNAME = "sampling-batches"
LEGACY_SELECTION_FILENAME = "water-level-selection.json"
LOCKS_DIRNAME = ".locks"
MAX_DISPLAY_NAME_LENGTH = 80
LOCK_TIMEOUT_SECONDS = 120.0

_BATCH_FILE = re.compile(r"^batch-(\d{4})\.json$")
_in_process_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


class SequenceStoreError(ValueError):
    """An invalid name, or a sequence that is busy or inconsistent."""


class SequenceBusyError(SequenceStoreError):
    """Another append or validation run holds this sequence."""


# --- atomic writes ----------------------------------------------------------


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write a file so readers see either the old content or the new, never a mix."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")


# --- lock -------------------------------------------------------------------


@contextmanager
def sequence_lock(sequence_dir: Path, *, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Hold exclusive access to one sequence, or raise `SequenceBusyError`.

    Used briefly by an append's commit step and for the whole of a validation
    run's start-up, so a run never reads a sequence half way through an append.
    """

    key = str(sequence_dir.resolve())
    with _registry_lock:
        thread_lock = _in_process_locks.setdefault(key, threading.Lock())
    if not thread_lock.acquire(timeout=timeout):
        raise SequenceBusyError("This sequence is busy. Try again in a moment.")
    handle = None
    try:
        if fcntl is not None and sequence_dir.is_dir():
            # Beside the sequences, not inside one: taking the lock must not change a sequence.
            lock_dir = sequence_dir.parent / LOCKS_DIRNAME
            lock_dir.mkdir(exist_ok=True)
            handle = open(lock_dir / f"{sequence_dir.name}.lock", "a+")  # noqa: SIM115
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if time.monotonic() >= deadline:
                        raise SequenceBusyError(
                            "This sequence is busy. Try again in a moment."
                        ) from error
                    time.sleep(0.05)
        yield
    finally:
        if handle is not None:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()
        thread_lock.release()


# --- display name -----------------------------------------------------------


def validate_display_name(raw: object) -> str | None:
    """A cleaned display name, or None for "use the generated default".

    Blank (or whitespace only) means no custom name. A name is display metadata
    only, so the rules are about being sensible to read, not about file systems:
    no control characters, bounded length, runs of whitespace collapsed. It is
    always HTML-escaped where shown.
    """

    if raw is None:
        return None
    if not isinstance(raw, str):
        raise SequenceStoreError("The sequence name must be text.")
    if not raw.strip():
        return None  # blank (whitespace only) means "use the generated default"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise SequenceStoreError("The sequence name cannot contain control characters.")
    cleaned = " ".join(raw.split())
    if len(cleaned) > MAX_DISPLAY_NAME_LENGTH:
        raise SequenceStoreError(
            f"The sequence name can be at most {MAX_DISPLAY_NAME_LENGTH} characters."
        )
    return cleaned


def read_display_name(sequence_dir: Path) -> str | None:
    try:
        loaded = json.loads((sequence_dir / SEQUENCE_META_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = loaded.get("display_name") if isinstance(loaded, dict) else None
    return name if isinstance(name, str) and name.strip() else None


def write_display_name(sequence_dir: Path, name: str, created_at_utc: str) -> None:
    atomic_write_json(
        sequence_dir / SEQUENCE_META_FILENAME,
        {"schema_version": 1, "display_name": name, "named_at_utc": created_at_utc},
    )


def sequence_label(sequence_id: str, display_name: str | None) -> str:
    """What to show for a sequence: its custom name, else its (unique) generated ID."""

    return display_name or sequence_id


# --- per-batch sampling provenance ------------------------------------------


def batch_dir(sequence_dir: Path) -> Path:
    return sequence_dir / BATCHES_DIRNAME


def next_batch_number(sequence_dir: Path) -> int:
    numbers = [
        int(match.group(1))
        for path in batch_dir(sequence_dir).glob("batch-*.json")
        if (match := _BATCH_FILE.fullmatch(path.name))
    ]
    return max(numbers, default=0) + 1


def write_batch(sequence_dir: Path, number: int, record: dict[str, Any]) -> Path:
    """Save one batch's provenance. A batch file is created once and never rewritten."""

    path = batch_dir(sequence_dir) / f"batch-{number:04d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SequenceStoreError(f"Batch {number} already exists for this sequence.")
    atomic_write_json(path, record)
    return path


def read_batches(sequence_dir: Path) -> list[dict[str, Any]]:
    """Every sampling batch of a sequence, oldest first.

    A sequence made before batches existed has one legacy `water-level-selection.json`;
    it is returned as batch 0 so older sequences read the same way.
    """

    batches: list[dict[str, Any]] = []
    legacy = sequence_dir / LEGACY_SELECTION_FILENAME
    if legacy.is_file():
        try:
            loaded = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None
        if isinstance(loaded, dict):
            batches.append({"batch_number": 0, "legacy": True, **loaded})
    for path in sorted(batch_dir(sequence_dir).glob("batch-*.json")):
        match = _BATCH_FILE.fullmatch(path.name)
        if not match:
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(loaded, dict):
            batches.append({"batch_number": int(match.group(1)), **loaded})
    return batches


def samples_by_filename(batches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """File name -> its sample record plus the batch it came from.

    An image belongs to the batch that first added it; a later batch that skipped it
    as a duplicate does not take it over, so earlier groups are never recategorized.
    """

    found: dict[str, dict[str, Any]] = {}
    for batch in batches:
        for sample in batch.get("samples", []):
            name = sample.get("filename") if isinstance(sample, dict) else None
            if name and name not in found:
                found[str(name)] = {**sample, "batch_number": batch.get("batch_number")}
    return found

"""Capture run inputs and read historical receipts without consulting live site files."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from openfloodai.contracts.local_store import JsonObject


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def read_input_snapshot(run_dir: Path) -> dict[str, Any]:
    """Read only a run's saved receipt, suitable for a future local export.

    Old runs without receipts raise FileNotFoundError; never substitute today's inputs.
    """

    root = run_dir / "inputs-used"
    return {
        "receipt": json.loads((root / "receipt.json").read_text(encoding="utf-8")),
        "config": json.loads((root / "site-config.snapshot.json").read_text(encoding="utf-8")),
        "watched_area": json.loads((root / "watched-area.snapshot.json").read_text(encoding="utf-8")),
        "manifest_text": (root / "manifest.snapshot.jsonl").read_text(encoding="utf-8"),
        "labels": [json.loads(line) for line in (root / "labels.snapshot.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()],
        "videos": json.loads((root / "video-list.snapshot.json").read_text(encoding="utf-8")),
    }


def finish_input_snapshot(run_dir: Path, status: str) -> None:
    """Finalize this run's receipt, without modifying any previous run."""

    path = run_dir / "inputs-used" / "receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt.update(status=status, finished_at=datetime.now(tz=UTC).isoformat())
    _write_json(path, receipt)


@contextmanager
def capture_run_inputs(
    *, site_dir: Path, run_dir: Path, config_path: Path,
    videos: list[Path], labels: list[JsonObject],
) -> Iterator[tuple[Path, list[Path]]]:
    """Freeze inputs for processing; retain video hashes, not extra permanent media.

    Temporary video copies prevent edits after capture from altering this run.
    Streaming capture bounds memory use; temporary copies are removed on exit.
    """

    root = run_dir / "inputs-used"
    root.mkdir(exist_ok=False)
    config_bytes = config_path.read_bytes() if config_path.exists() else b"null\n"
    try:
        config = json.loads(config_bytes)
    except (ValueError, UnicodeError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    captured_config = root / "site-config.snapshot.json"
    captured_config.write_bytes(config_bytes)
    _write_json(root / "watched-area.snapshot.json", (config or {}).get("reference_region"))
    manifest = site_dir / "manifest.jsonl"
    (root / "manifest.snapshot.jsonl").write_bytes(manifest.read_bytes() if manifest.exists() else b"")
    (root / "labels.snapshot.jsonl").write_text(
        "".join(json.dumps(label) + "\n" for label in labels), encoding="utf-8",
    )
    receipt = {
        "run_id": run_dir.name, "site_name": site_dir.name,
        "site_id": (config or {}).get("site_id"), "camera_id": (config or {}).get("camera_id"),
        "captured_at": datetime.now(tz=UTC).isoformat(), "status": "running",
        "config_present": config_path.exists(), "manifest_present": manifest.exists(),
        "human_label_count": len(labels), "mode": "human_comparison" if labels else "machine_only",
        "video_storage": "Temporary processing copies; permanent receipt contains SHA-256 identities only.",
    }
    _write_json(root / "receipt.json", receipt)
    _write_json(root / "video-list.snapshot.json", [])
    try:
        with TemporaryDirectory(prefix="openfloodai-run-inputs-") as temporary:
            captured_videos = []
            video_list = []
            for source in videos:
                destination = Path(temporary) / source.name
                digest = hashlib.sha256()
                size = 0
                with source.open("rb") as incoming, destination.open("wb") as outgoing:
                    before = source.stat()
                    while chunk := incoming.read(1024 * 1024):
                        outgoing.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    after = source.stat()
                if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                    raise ValueError(f"Video changed during input capture: {source.name}. Run again.")
                captured_videos.append(destination)
                video_list.append({"video_id": source.stem, "filename": source.name, "size_bytes": size, "sha256": digest.hexdigest()})
            _write_json(root / "video-list.snapshot.json", video_list)
            yield captured_config, captured_videos
    except Exception:
        finish_input_snapshot(run_dir, "failed")
        _write_json(run_dir / "run-metadata.json", {
            "run_id": run_dir.name, "site_name": site_dir.name,
            "created_at": receipt["captured_at"], "status": "failed",
            "inputs_used_path": str(root),
            "report_path": str(run_dir / "validation-report.md"),
        })
        raise

"""Which image a pair endpoint really is.

A file name does not identify an image: two different sequences can both hold ``frame-001.jpg``,
and one image can appear in several runs under the same name. An image is identified by the
checksum its run froze for it, so the same bytes are one image wherever they appear and different
bytes are different images whatever they are called.
"""

from __future__ import annotations

import json
from pathlib import Path


def frozen_image_shas(run_dir: Path) -> dict[str, str]:
    """``filename -> sha256`` of the images a run froze when it started."""

    try:
        rows = json.loads((run_dir / "inputs-used" / "images.snapshot.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        str(row["filename"]): str(row["sha256"])
        for row in rows
        if isinstance(row, dict) and row.get("filename") and row.get("sha256")
    }


class ImageIdentities:
    """Resolves ``(run_id, filename)`` to an image identity for one site, reading each run once."""

    def __init__(self, site_dir: Path, site_folder: str) -> None:
        self._site_dir = site_dir
        self._folder = site_folder
        self._runs: dict[str, dict[str, str]] = {}

    def of(self, run_id: str, filename: str) -> str:
        """The image's checksum, or a marker unique to this run and name when it cannot be known.

        The marker never equals another image's identity, so an image that cannot be identified is
        never treated as the same as, or different from, anything else by accident.
        """

        if run_id not in self._runs:
            safe = Path(run_id).name == run_id and run_id not in {"", ".", ".."}
            run_dir = self._site_dir / "outputs" / "image-sequence-runs" / run_id
            self._runs[run_id] = frozen_image_shas(run_dir) if safe else {}
        sha = self._runs[run_id].get(filename)
        return f"sha256:{sha}" if sha else f"unresolved:{self._folder}:{run_id}:{filename}"

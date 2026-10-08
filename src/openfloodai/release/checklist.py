"""The release's verification checklist: the one file a person edits after the build.

Because ticking a box changes the file, `RELEASE-CHECKLIST.md` is the single file left out of the
release checksums. Everything else is frozen.
"""

from __future__ import annotations

import re
from pathlib import Path

from openfloodai.curation.common import CurationError
from openfloodai.ingestion.sequence_store import atomic_write_text

CHECKLIST_FILENAME = "RELEASE-CHECKLIST.md"
_ITEM = re.compile(r"^- \[( |x)\] (.+)$")


def read_checklist(release_dir: Path) -> list[dict[str, object]]:
    path = release_dir / CHECKLIST_FILENAME
    if not path.is_file():
        return []
    items: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ITEM.match(line)
        if match:
            items.append(
                {"index": len(items), "checked": match.group(1) == "x", "text": match.group(2)}
            )
    return items


def set_checklist_item(release_dir: Path, index: int, checked: bool) -> list[dict[str, object]]:
    """Tick or untick one item, leaving every other line of the file as it was."""

    path = release_dir / CHECKLIST_FILENAME
    items = read_checklist(release_dir)
    if not 0 <= index < len(items):
        raise CurationError("That checklist item does not exist.")
    seen = -1
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if _ITEM.match(line):
            seen += 1
            if seen == index:
                line = f"- [{'x' if checked else ' '}] {items[index]['text']}"
        lines.append(line)
    atomic_write_text(path, "\n".join(lines) + "\n")
    return read_checklist(release_dir)

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from urllib.request import urlopen

import platformdirs
import pytest

from openfloodai.desktop.launcher import (
    resolve_default_sites_dir,
    resolve_packaged_ui_path,
    start_server,
)


def test_resolve_default_sites_dir_is_writable_and_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *_a, **_k: str(tmp_path))

    sites_dir = resolve_default_sites_dir()

    assert sites_dir == tmp_path / "sites"
    assert sites_dir.is_dir()


def test_resolve_packaged_ui_path_returns_the_bundled_html() -> None:
    with ExitStack() as resource_stack:
        ui_path = resolve_packaged_ui_path(resource_stack)

        assert ui_path.is_file()
        assert "<title>OpenFloodAI Home UI</title>" in ui_path.read_text(encoding="utf-8")


def test_start_server_binds_an_ephemeral_port_and_serves_the_app(tmp_path: Path) -> None:
    with ExitStack() as resource_stack:
        ui_path = resolve_packaged_ui_path(resource_stack)
        server = start_server("127.0.0.1", 0, tmp_path, ui_path)
        try:
            port = server.server_address[1]
            assert port != 0

            with urlopen(f"http://127.0.0.1:{port}/openfloodai-home-ui.html") as response:
                assert response.status == 200
                assert b"OpenFloodAI Home UI" in response.read()

            with urlopen(f"http://127.0.0.1:{port}/api/sites") as response:
                assert response.status == 200
        finally:
            server.shutdown()
            server.server_close()

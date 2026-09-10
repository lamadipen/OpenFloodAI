"""Standalone desktop launcher for the packaged OpenFloodAI Home UI app.

This is a separate entry point from ``scripts/run_openfloodai_home_ui.py``
(the dev workflow, which is untouched). It resolves an OS-appropriate,
writable sites directory and the packaged UI HTML as installed/frozen
resources, starts the existing local server in the background, opens the
default browser to it, and shows a tray/menu-bar icon with a way to open
the sites folder or quit.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import webbrowser
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING

import platformdirs

from openfloodai.ui.home_server import OpenFloodAIHomeHandler

if TYPE_CHECKING:
    import pystray

_APP_NAME = "OpenFloodAI"


def resolve_default_sites_dir() -> Path:
    """Return the OS-standard, writable per-app data folder for site data.

    e.g. ``~/Library/Application Support/OpenFloodAI/sites`` on macOS,
    ``%APPDATA%\\OpenFloodAI\\sites`` on Windows. This is the folder the
    Home UI's "Site folder: ..." line will display, and it is unaffected
    by deleting or reinstalling the app itself.
    """

    base = Path(platformdirs.user_data_dir(_APP_NAME, appauthor=False))
    sites_dir = base / "sites"
    sites_dir.mkdir(parents=True, exist_ok=True)
    return sites_dir


def resolve_packaged_ui_path(resource_stack: ExitStack) -> Path:
    """Resolve the packaged Home UI HTML file as a real filesystem path.

    Kept open for the process lifetime via ``resource_stack`` because the
    server re-reads this path on every request (unlike the event schema,
    which is read once and cached).

    The HTML file is placed inside the package tree only by the wheel
    build's ``force-include`` (so it can stay in ``tools/`` untouched for
    the dev workflow); an editable/dev install has no such build step, so
    this falls back to the source tree's copy in that case.
    """

    traversable = resources.files("openfloodai.ui") / "static" / "openfloodai-home-ui.html"
    packaged_path = resource_stack.enter_context(resources.as_file(traversable))
    if packaged_path.is_file():
        return packaged_path

    source_tree_path = Path(__file__).resolve().parents[3] / "tools" / "openfloodai-home-ui.html"
    if source_tree_path.is_file():
        return source_tree_path

    return packaged_path


def start_server(host: str, port: int, sites_dir: Path, ui_path: Path) -> ThreadingHTTPServer:
    """Start the existing Home UI server in the background and return it.

    Pass ``port=0`` to let the OS assign a free port; read the real port
    back from ``server.server_address[1]``.
    """

    OpenFloodAIHomeHandler.sites_dir = sites_dir
    OpenFloodAIHomeHandler.ui_path = ui_path
    server = ThreadingHTTPServer((host, port), OpenFloodAIHomeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def build_tray_icon(server: ThreadingHTTPServer, url: str, sites_dir: Path) -> pystray.Icon:
    """Build the tray/menu-bar icon offering Open in Browser / Quit actions.

    Imports pystray and PIL locally: they are optional desktop-only
    dependencies, not required for the base dev/test install.
    """

    import pystray
    from PIL import Image

    icon_bytes = (resources.files("openfloodai.desktop") / "assets" / "tray_icon.png").read_bytes()
    image = Image.open(io.BytesIO(icon_bytes))

    def open_in_browser(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        webbrowser.open(url)

    def open_sites_folder(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        _reveal_folder(sites_dir)

    def quit_app(icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        server.shutdown()
        server.server_close()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open in Browser", open_in_browser),
        pystray.MenuItem("Open Sites Folder", open_sites_folder),
        pystray.MenuItem("Quit", quit_app),
    )
    return pystray.Icon(_APP_NAME, image, _APP_NAME, menu)


def _reveal_folder(path: Path) -> None:
    """Open a folder in the platform's file browser."""

    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform.startswith("win"):
        subprocess.run(["explorer", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def main() -> None:
    """Start the local server, open the browser, and run the tray icon."""

    parser = argparse.ArgumentParser(description="Run the OpenFloodAI desktop app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=0, type=int)
    parser.add_argument("--sites-dir", default=None, type=Path)
    parser.add_argument("--ui-path", default=None, type=Path)
    args = parser.parse_args()

    with ExitStack() as resource_stack:
        sites_dir = args.sites_dir or resolve_default_sites_dir()
        sites_dir.mkdir(parents=True, exist_ok=True)
        ui_path = args.ui_path or resolve_packaged_ui_path(resource_stack)

        server = start_server(args.host, args.port, sites_dir, ui_path)
        port = server.server_address[1]
        url = f"http://{args.host}:{port}/openfloodai-home-ui.html"

        print(f"OpenFloodAI is running at {url}")
        print(f"Site folder: {sites_dir}")

        try:
            # A headless build/CI environment has no default browser configured.
            webbrowser.open(url)
        except Exception as error:
            print(f"Could not open a browser automatically: {error}")

        icon = build_tray_icon(server, url, sites_dir)
        icon.run()


if __name__ == "__main__":
    main()

"""Run the local OpenFloodAI home UI."""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path

from openfloodai.ui.home_server import OpenFloodAIHomeHandler


def main() -> None:
    """Start a local-only OpenFloodAI home UI server."""

    parser = argparse.ArgumentParser(description="Run the local OpenFloodAI home UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--sites-dir", default=Path("data/sites"), type=Path)
    parser.add_argument("--ui-path", default=Path("tools/openfloodai-home-ui.html"), type=Path)
    args = parser.parse_args()

    handler = OpenFloodAIHomeHandler
    handler.sites_dir = args.sites_dir
    handler.ui_path = args.ui_path

    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/openfloodai-home-ui.html"

    print("OpenFloodAI local home UI is running.")
    print(f"Open: {url}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()

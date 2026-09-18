# PyInstaller spec for the OpenFloodAI desktop app.
#
# Build from the repo root with:
#   pip install -e ".[desktop,packaging]"
#   pyinstaller packaging/openfloodai_desktop.spec --distpath dist --workpath build --clean
#
# PyInstaller cannot cross-compile: run this on each target OS separately.
#
# Windows builds a single onefile .exe. macOS builds onedir + BUNDLE: a
# macOS .app is already a directory structure, so PyInstaller's onefile mode
# (a self-extracting single binary) doesn't apply there and is deprecated
# when combined with BUNDLE.

import sys
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_data_files

SPEC_DIR = Path(SPECPATH)
REPO_ROOT = SPEC_DIR.parent
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

a = Analysis(
    [str(REPO_ROOT / "src" / "openfloodai" / "desktop" / "launcher.py")],
    pathex=[str(REPO_ROOT / "src")],
    datas=[
        (
            str(REPO_ROOT / "tools" / "openfloodai-review-workspace.html"),
            "openfloodai/ui/static",
        ),
        (
            str(REPO_ROOT / "src" / "openfloodai" / "schemas" / "event.schema.json"),
            "openfloodai/schemas",
        ),
        (
            str(REPO_ROOT / "tools" / "openfloodai-home-ui.html"),
            "openfloodai/ui/static",
        ),
        (
            str(REPO_ROOT / "tools" / "openfloodai-river-images.html"),
            "openfloodai/ui/static",
        ),
        (
            str(REPO_ROOT / "tools" / "openfloodai-site-details.html"),
            "openfloodai/ui/static",
        ),
        (
            str(REPO_ROOT / "src" / "openfloodai" / "desktop" / "assets" / "tray_icon.png"),
            "openfloodai/desktop/assets",
        ),
    ] + (collect_data_files("tzdata") if IS_WIN else []),
    hiddenimports=["pystray._win32"] if IS_WIN else ["pystray._darwin"],
)
pyz = PYZ(a.pure)

if IS_MAC:
    from PyInstaller.building.osx import BUNDLE

    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="OpenFloodAI",
        console=False,
        icon=str(SPEC_DIR / "assets" / "icon.icns"),
    )
    coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="OpenFloodAI")
    app = BUNDLE(
        coll,
        name="OpenFloodAI.app",
        icon=str(SPEC_DIR / "assets" / "icon.icns"),
        bundle_identifier="org.openfloodai.desktop",
        info_plist={"NSHighResolutionCapable": True},
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        name="OpenFloodAI",
        console=False,
        icon=str(SPEC_DIR / "assets" / "icon.ico"),
    )

# Building the OpenFloodAI desktop app

This produces a standalone double-clickable app for Windows or macOS, with no
Python installation required to run it. PyInstaller cannot cross-compile, so
build on the OS you're targeting.

## Build

```bash
pip install -e ".[desktop,packaging]"
pyinstaller packaging/openfloodai_desktop.spec --distpath dist --workpath build --clean
```

- macOS: produces `dist/OpenFloodAI.app`.
- Windows: produces `dist/OpenFloodAI.exe`.

## Try it locally

- macOS: `open dist/OpenFloodAI.app`, or run the binary directly for console
  output: `dist/OpenFloodAI.app/Contents/MacOS/OpenFloodAI`.
- Windows: double-click `dist/OpenFloodAI.exe`.

A menu-bar/tray icon appears with **Open in Browser**, **Open Sites Folder**,
and **Quit**. The default browser opens automatically to the running app.

## macOS Gatekeeper

This build is unsigned and unnotarized for v1. On first launch, macOS shows
"Apple could not verify ... is free of malware." Right-click the app in
Finder and choose **Open**, then confirm — this is only needed once.

## Windows SmartScreen

Unsigned executables commonly trigger "Windows protected your PC." Click
**More info**, then **Run anyway**.

## Icons

`assets/icon.ico` (Windows) and `assets/icon.icns` (macOS) are derived from
`images/logo/OpenFloodAI-logo.png`. Regenerate them if the logo changes; see
the icon-generation steps in the OF-071 implementation notes.

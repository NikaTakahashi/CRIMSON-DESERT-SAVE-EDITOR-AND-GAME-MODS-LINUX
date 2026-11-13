# Build from Source

## Prerequisites

- **Python 3.12+** from [python.org](https://www.python.org/downloads/)
  - **Do NOT use the Microsoft Store version** — it restricts site-packages and breaks PyInstaller
  - Check "Add Python to PATH" during install
- **pip packages**: `PySide6 lz4 cryptography Pillow pyinstaller`

## Windows

```bat
pip install PySide6 lz4 cryptography Pillow pyinstaller

:: Build Game Mods
cd CrimsonGameMods
python -m PyInstaller CrimsonGameMods.spec --noconfirm
:: Output: CrimsonGameMods\dist\CrimsonGameMods.exe

:: Build Save Editor
cd ..\CrimsonSaveEditor
python -m PyInstaller CrimsonSaveEditor.spec --noconfirm
:: Output: CrimsonSaveEditor\dist\CrimsonSaveEditor.exe
```

Or use `build.bat` inside `CrimsonGameMods/` — it clears caches and runs PyInstaller for you.

## Linux / SteamOS

```bash
python3 -m venv .venv && .venv/bin/pip install PySide6 lz4 cryptography Pillow pyinstaller

# Native C++ backend for the Save Editor. The ctypes wrapper looks for
# libparc_parser.so next to native_backend.py, so build it and put it there.
cmake -S CrimsonSaveEditorCpp -B CrimsonSaveEditorCpp/build
cmake --build CrimsonSaveEditorCpp
cp CrimsonSaveEditorCpp/build/libparc_parser.so CrimsonSaveEditor/

# Run straight from source
python3 CrimsonSaveEditor/main.py

# Or package it — the same specs already pick the per-platform binaries
python3 build.py --project saveeditor
# Output: CrimsonSaveEditor/dist/CrimsonSaveEditorStandalone
```

Crimson Desert has no Linux build, so game and save paths resolve through the Steam
prefix (`$XDG_DATA_HOME/Steam`, `~/.local/share/Steam`, the flatpak Steam data dir) and,
for a Proton install, through `steamapps/compatdata/3321460/pfx/drive_c/...`. Every library
folder recorded in `steamapps/libraryfolders.vdf` is included, so a game installed on a
second drive is found. There is no drive-letter logic.

Packaged (AppImage) builds pin Qt's platform theme to `generic`: under Plasma Qt would
otherwise use the KDE theme's file dialog, which needs the KF6/KIO plugins a packaged build
cannot load, and the dialog then opens with an empty listing.

`pip install lz4` compiles from source on Python versions without a wheel, which needs a C
compiler plus the Python dev headers (`python3-dev`). Without `lz4` the Save Editor cannot
open a save file, so this dependency is not optional.

## Note on native extensions

The tools use `dmm_parser` (Rust-based parser). Pre-built `.pyd` (Windows) and `.abi3.so` (Linux) binaries ship with the repo in `CrimsonGameMods/dmm_parser/`. You do not need Rust installed to build. On Linux the shipped `.abi3.so` is loaded through `importlib.machinery.ExtensionFileLoader`, because that filename is not importable as the `dmm_parser.dmm_parser` submodule.

`crimson_rs` is a pure-Python package; its optional native bindings come from `dmm_parser` (`.abi3.so` on Linux, `.pyd` on Windows), so the Linux `.abi3.so` loader fix above is what makes those functions available. Without them the pure-Python path is used and nothing fails. The Save Editor's `libparc_parser.so` is not shipped; build it with CMake as shown above.

## Troubleshooting

| Error | Fix |
|-------|-----|
| "Unable to locate PySide6/shiboken6 shared libraries" | You're using MS Store Python. Uninstall it and install from [python.org](https://www.python.org/downloads/) |
| `pip` not found | Re-run Python installer, check "Add Python to PATH" |
| `ModuleNotFoundError: No module named 'PySide6'` | Run `pip install PySide6` (make sure you're using the right pip — `python -m pip install PySide6`) |

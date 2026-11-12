# Crimson Desert — Save Editor & Game Mods · **Linux fork**

> **This repository is a fork, not the official project.** It is not maintained by the original
> author; the builds it publishes are fork builds, not upstream ones (see [Downloads](#downloads-fork-builds)).
>
> Upstream (original): [NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS](https://github.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS)
> — created and maintained by **Rice (RicePaddySoftware / NattKh)**.
>
> **Thank you, Rice** — every parser, format handler, tab and feature in these tools is their work.
> This fork changes **only how the tools run on Linux**; the editor itself is unchanged in behaviour.
> Fork by [NikaTakahashi](https://github.com/NikaTakahashi). License stays **MPL-2.0** (© RicePaddySoftware).

## What this fork is for

Crimson Desert has no Linux build, so the game runs under Proton. The editors themselves, however,
are plain Python — they were runnable on Linux in principle, but they assumed Windows at every
step: `LOCALAPPDATA`, drive letters, `tasklist`, `os.startfile`, a Windows-only `.pyd`, a `cl`-only
C++ build, and PyInstaller spec paths resolved against the current directory.

The point of this fork is that the tools run as **native Linux processes**, reading the Proton
prefix for game and save data. Nothing here pretends to emulate Windows: a missing Windows API is
guarded, and the POSIX equivalent is used instead.

## What is Linux-specific here

| Area | Change |
|---|---|
| Paths | New `platform_paths.py` in both tools: Steam data roots (`$XDG_DATA_HOME/Steam`, `~/.local/share/Steam`, `~/.steam/steam`, Snap and Flatpak installs), Proton prefix for app id `3321460`, game-install and save-folder candidates, per-user `app_data_dir` (XDG instead of `%APPDATA%`). |
| Process check | `tasklist` replaced by reading `/proc/<pid>/comm` (the kernel truncates the image name to 15 chars, so `CrimsonDesert.exe` is matched as `CrimsonDesert.e` too), `pgrep -f` on macOS, zombites skipped. |
| Shell / files | `os.startfile` → `xdg-open` (macOS keeps `open`); no drive-letter logic on POSIX. |
| Native modules | The shipped `dmm_parser.abi3.so` is loaded through `importlib.machinery.ExtensionFileLoader` — that filename is not importable as `dmm_parser.dmm_parser`, so on Linux the native functions were silently missing before. |
| C++ backend | `CMakeLists.txt` builds `libparc_parser.so` with plain CMake (no `cl`), and the `dye_cli` target — which previously only existed as a manual `cl` command — is now a real CMake target; the runtime lookup resolves `dye_cli` outside Windows. |
| Build specs | Every `.spec` now anchors native-binary and data paths to `SPECPATH` instead of `__file__` (PyInstaller ≥ 6.22 does not define `__file__` in the spec namespace) and picks binaries per platform instead of assuming a Windows `.pyd`. |
| Windows-only calls | `ctypes.windll`, `CREATE_NO_WINDOW`, `ShellExecuteW` and similar are guarded (`getattr(..., 0)`) so a missing Windows API degrades to the normal path instead of raising. |

## Status on Linux — what was actually run

Verified on an x86-64 Fedora system (Python 3.15, PySide6 6.8, PyInstaller 6.22):

| Check | Result |
|---|---|
| Dependencies install | `pip install PySide6 lz4 cryptography pyinstaller` — `lz4` compiles from source when no wheel exists, so `python3-devel` and a C compiler are required. |
| Both GUIs start and render | Yes (checked under Xvfb); tabs build, item DB loads (7080 items Save Editor JSON / 7159 Game Mods DB rows after the refresh below). |
| Save + game path discovery | A Proton prefix is found through the UI: `Auto-Detect Client` resolves the install folder, the sidebar lists the save slot under `compatdata/3321460/pfx`. |
| Native C++ backend | CMake builds `libparc_parser.so`; the ctypes wrapper loads it and reports `crimson_save_backend 2.1.0`. |
| Native Rust module | `dmm_parser` loads via the extension loader; `extract_file`, `parse_papgt_file` are present. |
| Save pipeline | Encrypt → compress → write, read back: byte-identical round-trip; a flipped byte in the payload is refused by HMAC verification. |
| Packaged binaries | `build.py` produces Linux ELF executables for both tools and they run without import errors. |
| Item table on a 2.04 install | The native extension cannot read it (`trie offset 1634142208 out of bounds`); the pure-Python readers in `dmm_parser.pack_index` / `dmm_parser.item_record` read all 7069 rows. `sync_from_local_game` in both apps now falls back to those readers when the native path fails, so a current install can be scanned. |
| String table (`item.paloc`) | Only 6 entries are plain literals; the rest of the stream is prefix-coded against a dictionary the game builds at pack time, so most display names stay internal (on current data `item_name.default` is the decimal paloc id, not localized text). |
| Bag-key rule | `1` for equip rows, `2` otherwise. It reproduces all 5886 curated `item_category_map.json` entries on this install, so it can fill the 1199 game items the map lacked. Game Mods reads bag keys from the DB table (no JSON fallback), so `--write-map --sqlite` mirrors the derived keys there too. |
| Item DB refresh | `python3 -m dmm_parser.tools.refresh_item_db <install> --write --write-map --sqlite`: +844 Save Editor entries, +1063 Game Mods entries, +1199 bag keys in both apps and the Game Mods DB table. |
| Real save parse | A genuine `save.save` decrypts, HMAC-verifies and scans: 8,050,617-byte blob, 968 item entries, 771 distinct keys. 86 of those keys were missing from the item DB before the refresh; 77 now resolve, and the Game Mods bag lookup returns the derived key for a new item (`1004403` → bag 1). |
| Tests | `python3 -m dmm_parser.tools._test_readers` — 21 tests pass against the install; the game-data ones skip when no install is available (`CD_GAME_DIR` or the default Steam path). |
| `crimson_rs` | The repository package is pure Python and works; `crimson_rs` from PyPI is not installable on Linux and is not needed. |

**Still not verified:** writing a patched save or a PAZ overlay back and observing the result in the
running game. Reading real game data and real saves is now covered (rows above); in-game behaviour is not,
so the round-trip proof still shows internal consistency, not compatibility with the game.

## Downloads (fork builds)

| Tool | Release | Assets |
|---|---|---|
| Save Editor | [standalone-v1.0.8](https://github.com/NikaTakahashi/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS-LINUX/releases/tag/standalone-v1.0.8) | `.AppImage`, `.tar.gz`, Windows `.exe` |
| Game Mods | [gamemods-v2.1.8](https://github.com/NikaTakahashi/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS-LINUX/releases/tag/gamemods-v2.1.8) | `.AppImage`, `.tar.gz`, Windows `.exe` |

- **AppImage** — self-contained, nothing to install: `chmod +x` and run it. It carries its own runtime;
  the squashfs payload is mounted read-only, so runtime data goes to the per-user data dir.
- **tar.gz** — the plain PyInstaller output plus the native modules (`libparc_parser.so`,
  `dmm_parser.abi3.so`, `dye_cli`). Extract and run the binary. Built against glibc 2.44, so an older
  distribution may refuse to start it.
- **`.exe`** — the Windows build produced by the CI workflow, kept for parity with upstream.
- The v1.0.8 **AppImage** was assembled with `squashfs-tools` (`appimagetool` is not packaged for Fedora):
  the v1.0.7 runtime and its offset table were kept, the gzip squashfs payload rebuilt with the new binary,
  `dye_cli` and `libparc_parser.so`. `--appimage-extract` returns exactly the packaged build.

Tag names follow the upstream scheme (`standalone-vX.Y.Z`, `gamemods-vX.Y.Z`), so the release titles say
*Linux fork*. Both need a desktop session for Qt.

## Quick start (Linux)

```bash
pip install PySide6 lz4 cryptography pyinstaller
# C++ backend for the Save Editor (the ctypes wrapper looks for the .so next to native_backend.py)
cmake -S CrimsonSaveEditorCpp -B build && cmake --build build
cp build/libparc_parser.so CrimsonSaveEditor/

python3 CrimsonSaveEditor/main.py            # Save Editor
python3 CrimsonGameMods/main.py              # Game Mods

# or package it
python3 build.py --project saveeditor        # → CrimsonSaveEditor/dist/CrimsonSaveEditorStandalone
python3 build.py --project gamemods          # → CrimsonGameMods/dist/CrimsonGameMods
```

Run from source or from the packaged binary; both paths were tested. `build.sh` is the Linux wrapper
around `build.py` — make sure `python3` resolves to your virtual environment, otherwise PyInstaller
cannot find PySide6.

Roots searched on Linux — no `LOCALAPPDATA`, no drive letters:

```
$XDG_DATA_HOME/Steam/steamapps/compatdata/3321460/pfx/drive_c/users/steamuser/AppData/Local/Pearl Abyss/CD/save
~/.local/share/Steam/steamapps/common/Crimson Desert
```

## Caveats worth knowing

- **The in-app updater is not fork-aware.** `updater.py` reads the upstream manifests, which point at
  Windows `.exe` builds, and `apply_update_and_restart` replaces the running binary with whatever it
  downloads — on Linux that gives you a Windows PE that will not run. Use "Check for update" as
  information only; update this fork by pulling it and rebuilding.
- **PyInstaller's `Splash` is Windows/macOS only**; the Game Mods spec's splash is skipped on Linux.
  The app's own startup screen is a Qt widget and works everywhere.
- The in-app launcher for the game calls `steam://` or the desktop shell; without a desktop session it
  has nothing to hand the URL to, so it does nothing rather than launching the game.
- `crimson_rs` native bindings come from `dmm_parser` when available; otherwise the pure-Python path is
  used. Nothing hard-fails.

## The two tools

| Tool | What it does |
|---|---|
| **Save Editor — Standalone** | Edits your local `.save` file: inventory, equipment, sockets (fill/clear up to 5), quests, knowledge, abyss gates, dye. |
| **Game Mods** | Edits the game's `.pabgb` data via PAZ overlays: ItemBuffs, Stores, DropSets, SpawnEdit, FieldEdit (mount-everywhere, killable NPCs, etc.). |

Neither tool touches the game client in memory. Save Editor writes the encrypted `save.save`; Game Mods
writes PAZ overlay directories. Both auto-backup before writing.

Feature lists are inherited from upstream; the full breakdown is in the
[upstream README](https://github.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS#readme) and in
[`CrimsonGameMods/README.md`](./CrimsonGameMods/README.md).

Usage:

1. Run the tool (source or packaged binary).
2. It writes config/backups next to itself — keep it in its own folder. If that folder is read-only
   (the AppImage mount, a squashfs image, `/opt`), it falls back to the per-user data dir:
   `~/.local/share/CrimsonSaveEditor` / `~/.local/share/CrimsonGameMods` on Linux, `%APPDATA%` on
   Windows, `~/Library/Application Support` on macOS.
3. Point the Game Path bar at the install folder (Auto-Detect tries the Proton prefix first), then pick
   the save from the sidebar.
4. The in-app **Guides** menu has per-tab walkthroughs.

## Source layout

```
CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS/
├── build.py / build.sh                ← PyInstaller entry point (platform-aware)
├── editor_version_standalone.json     ← Save Editor update manifest (upstream, Windows builds)
├── editor_version_gamemods.json       ← Game Mods update manifest (upstream, Windows builds)
├── CrimsonGameMods/                   ← Game Mods source: main.py + 91 modules, gui/ (32 modules)
│   ├── platform_paths.py              ← fork: cross-platform paths / shell / process probe
│   ├── data/, locale/, knowledge_packs/, dropset_packs/
│   └── *.spec
├── CrimsonSaveEditor/                 ← Save Editor source: main.py + 30 modules
│   ├── platform_paths.py              ← fork: same helpers
│   ├── native_backend.py              ← ctypes wrapper for the C++ backend
│   └── *.spec
└── CrimsonSaveEditorCpp/              ← C++ backend, builds .dll (Windows) / .so (Linux)
```

## Credits

- **Rice (RicePaddySoftware / [NattKh](https://github.com/NattKh))** — the whole project: editor,
  save-format work, releases. This fork stands on their work.
- **gek** — original Qt desktop editor base; **potter4208467** — Rust `crimson_rs` toolkit;
  **LukeFZ** — `pycrimson` utilities; **fire** — 3.2.0 modular refactor, socket fill/clear.
  Full list in [`CrimsonGameMods/CREDITS.md`](./CrimsonGameMods/CREDITS.md).

## License

MPL-2.0, © RicePaddySoftware — see [`LICENSE.txt`](./LICENSE.txt) and
[`CrimsonGameMods/LICENSE`](./CrimsonGameMods/LICENSE). This fork does not relicense anything; the
Linux port is contributed under the same terms.

Unofficial, non-commercial modding utilities for **Crimson Desert** (©
[Pearl Abyss](https://www.pearlabyss.com/)). No game assets, binaries or proprietary data are
redistributed — all extraction happens locally from your own installed copy. Always back up your saves
and game files. Use at your own risk.

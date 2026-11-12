"""Cross-platform path and shell helpers (Windows, macOS, Linux/SteamOS).

Crimson Desert has no native Linux build, so on Linux every game path resolves
through the Steam/Proton prefix. These helpers replace the Windows-only
``LOCALAPPDATA`` / drive-letter assumptions that the rest of the codebase used
to hard-code.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "CrimsonGameMods"

# Steam app id for Crimson Desert; also the Proton prefix folder name.
STEAM_APP_ID = 3321460

_GAME_DIR_NAMES = ("Crimson Desert", "CrimsonDesert")


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_macos() -> bool:
    return sys.platform == "darwin"


def app_data_dir(app_name: str = APP_NAME) -> Path:
    """Per-user writable directory for config, locale packs and logs."""
    if is_windows():
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / app_name
    if is_macos():
        return Path.home() / "Library" / "Application Support" / app_name
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / app_name


def program_dir() -> Path:
    """The folder the user actually launched the app from.

    A PyInstaller one-file binary inside an AppImage runs from its temporary
    extraction directory, so `sys.executable` is not a durable home for runtime
    data: whatever is written there disappears when the app exits. The AppImage
    runtime exports APPIMAGE with the path of the .AppImage file itself, so that
    folder is the stable "beside the program" location.
    """
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return Path(os.path.dirname(os.path.abspath(appimage)))
    if getattr(sys, "frozen", False):
        return Path(os.path.dirname(os.path.abspath(sys.executable)))
    return Path(os.path.dirname(os.path.abspath(__file__)))


def run_dir(subdir: str = "", app_name: str = APP_NAME) -> Path:
    """The app's own folder: beside the program, named after the app.

    A packaged build gets `<program folder>/<app name>` -- next to the AppImage
    or next to the one-file binary -- and that is where config, the icon cache,
    the JSON databases and logs live. A source checkout keeps writing in its own
    package folder.
    """
    base = program_dir()
    if getattr(sys, "frozen", False):
        base = base / app_name
    return base / subdir if subdir else base


def writable_dir(subdir: str = "", app_name: str = APP_NAME) -> Path:
    """Where runtime data (config, packs, sets, icons, JSONs) is written: the
    app's own folder beside the program.

    Read-only layouts -- an AppImage mount, a system-wide install -- make that
    folder uncreatable, so fall back to the per-user data directory. mkdir with
    exist_ok reports success on a read-only mount, so prove the folder by
    actually writing to it.
    """
    target = run_dir(subdir)
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write_probe"
        probe.touch()
        probe.unlink()
        return target
    except OSError:
        fallback = app_data_dir(app_name) / subdir
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return fallback


def open_path(path: str | os.PathLike[str]) -> None:
    """Open a folder/file in the desktop shell, or launch a steam:// URL."""
    target = str(path)
    if is_windows():
        os.startfile(target)
        return
    if is_macos():
        subprocess.Popen(["open", target])
        return
    subprocess.Popen(["xdg-open", target])


def is_process_running(image_name: str) -> bool:
    """True when a process with this image name is running.

    Windows keeps the tasklist probe. On Linux the image name is compared with
    /proc/<pid>/comm, which the kernel truncates to 15 characters
    (`CrimsonDesert.exe` shows as `CrimsonDesert.e`), so the truncated form is
    matched as well. macOS has no /proc, so pgrep matches the command line there.
    """
    if is_windows():
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
                stderr=subprocess.DEVNULL, text=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return image_name.lower() in out.lower()
        except Exception:
            return False

    names = {image_name, image_name.removesuffix(".exe")}
    names |= {name[:15] for name in names}

    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            comm, state = stat.split("(", 1)[1].rsplit(")", 1)[0], stat.rsplit(")", 1)[1].split()[0]
            if state == "Z":
                continue
            if comm in names:
                return True
        return False

    for name in sorted(names):
        try:
            out = subprocess.check_output(
                ["pgrep", "-f", name], stderr=subprocess.DEVNULL, text=True, timeout=3
            )
            if out.strip():
                return True
        except Exception:
            continue
    return False


def _steam_data_dirs() -> list[Path]:
    """Steam install roots that can hold steamapps/common and compatdata."""
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        if path and path not in seen:
            seen.add(path)
            candidates.append(path)

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        add(Path(xdg) / "Steam")
    add(Path.home() / ".local" / "share" / "Steam")
    add(Path.home() / ".steam" / "steam")
    add(Path.home() / "Snap" / "Steam" / ".steam" / "steam")
    add(Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam")
    if is_macos():
        add(Path.home() / "Library" / "Application Support" / "Steam")
    return candidates


def steam_compatdata_dir() -> list[Path]:
    """Proton prefix roots for the game's Steam app id."""
    return [d / "steamapps" / "compatdata" / str(STEAM_APP_ID) / "pfx"
            for d in _steam_data_dirs()]


def game_install_candidates() -> list[str]:
    """Readable game install folders, checked in lookup order."""
    candidates: list[str] = []

    if is_windows():
        for letter in "CDEF":
            candidates.append(f"{letter}:\\SteamLibrary\\steamapps\\common\\Crimson Desert")
        candidates.extend([
            r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert",
            r"C:\Program Files\Steam\steamapps\common\Crimson Desert",
            r"C:\Program Files\Epic Games\CrimsonDesert",
        ])
    else:
        for root in _steam_data_dirs():
            for name in _GAME_DIR_NAMES:
                candidates.append(str(root / "steamapps" / "common" / name))

    # Game installed under Proton: the Windows path lives inside the prefix.
    for prefix in steam_compatdata_dir():
        for name in _GAME_DIR_NAMES:
            candidates.append(
                str(prefix / "drive_c" / "Program Files (x86)" / "Steam"
                    / "steamapps" / "common" / name)
            )

    return candidates


def save_root_candidates() -> list[str]:
    """Folders that may contain <user id>/<slot>/save.save."""
    roots: list[str] = []

    if is_windows():
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(str(Path(local) / "Pearl Abyss" / "CD" / "save"))
            roots.append(str(Path(local) / "Pearl Abyss" / "CD_Epic" / "save"))
            roots.append(str(Path(local) / "Packages"))
    else:
        for prefix in steam_compatdata_dir():
            user_local = prefix / "drive_c" / "users" / "steamuser" / "AppData" / "Local"
            roots.append(str(user_local / "Pearl Abyss" / "CD" / "save"))
            roots.append(str(user_local / "Pearl Abyss" / "CD_Epic" / "save"))

    return [r for r in roots if os.path.isdir(r)]

"""
Legacy parser wrapper for pre-April-2026 iteminfo.pabgb files.

The current crimson_rs parser handles the new game format (April 2026+).
Old iteminfo files use a different struct layout that the new parser can't read.
This module loads the old native parser from crimson_rs/_legacy/ to handle them
(.pyd on Windows, .abi3.so/.so on Linux, .dylib on macOS).

Usage:
    from crimson_rs.legacy import is_available, parse_old_iteminfo, serialize_old_iteminfo

    if not is_available():
        print("Legacy parser missing — skipping pre-April-2026 files.")
    else:
        old_items = parse_old_iteminfo(old_pabgb_bytes)
        old_bytes = serialize_old_iteminfo(old_items)
"""

from __future__ import annotations

import importlib.util
import logging
import os

import platform_paths

log = logging.getLogger(__name__)

# Native module suffixes checked in lookup order per platform.
_SUFFIXES = {
    "win": (".pyd",),
    "darwin": (".abi3.so", ".so", ".dylib"),
    "linux": (".abi3.so", ".so"),
}

_legacy_mod = None


def _legacy_path():
    legacy_dir = os.path.join(os.path.dirname(__file__), "_legacy")
    if platform_paths.is_windows():
        key = "win"
    elif platform_paths.is_macos():
        key = "darwin"
    else:
        key = "linux"
    for suffix in _SUFFIXES[key]:
        path = os.path.join(legacy_dir, "crimson_rs" + suffix)
        if os.path.isfile(path):
            return path
    return None


def is_available() -> bool:
    """True when the pre-April-2026 native parser exists for this platform."""
    return _legacy_path() is not None


def _load_legacy():
    global _legacy_mod
    if _legacy_mod is not None:
        return _legacy_mod

    legacy_path = _legacy_path()
    if legacy_path is None:
        expected = ", ".join("crimson_rs" + s for s in _SUFFIXES[
            "win" if platform_paths.is_windows() else
            ("darwin" if platform_paths.is_macos() else "linux")])
        raise ImportError(
            f"Legacy parser not found in crimson_rs/_legacy/ (looked for {expected}). "
            f"Copy the pre-April-2026 native build of crimson_rs to crimson_rs/_legacy/."
        )

    spec = importlib.util.spec_from_file_location("crimson_rs", legacy_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _legacy_mod = mod
    return mod


def parse_old_iteminfo(data: bytes) -> list[dict]:
    if not is_available():
        log.warning("Legacy parser absent (%s); skipping pre-April-2026 file.",
                    "crimson_rs/_legacy/")
        return []
    mod = _load_legacy()
    return mod.parse_iteminfo_from_bytes(data)


def serialize_old_iteminfo(items: list[dict]) -> bytes:
    if not is_available():
        log.warning("Legacy parser absent (crimson_rs/_legacy/); skipping.")
        return b""
    mod = _load_legacy()
    return mod.serialize_iteminfo(items)

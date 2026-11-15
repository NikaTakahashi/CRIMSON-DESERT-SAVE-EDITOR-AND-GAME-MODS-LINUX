# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""
dmm-parser-extract-icons — write the item icons the game itself ships as the
`icons_local/<itemKey>.webp` files the editor reads.

Items are not in one table: the install carries `iteminfo` in pack group 0008 for
the base game, and `iteminfo.<pkg>.staticinfoheader/body` for each DLC package
under `dlc/<pkg>/0008` (dlc_01 adds 1555 rows, so 1555 item keys the base table
never lists). Every package is walked, which is what the earlier base-only pass
missed. Same for the name table: a DLC row's icon hash can resolve only through
that package's `stringinfo`, or only through the base one, so both are consulted.
The icon file itself may sit in the package's own icon pack or in the base one.

For each item row: take `item_icon_list[0].icon_path`, resolve it to the icon
name, find that name as a `.dds` in the icon pack group, decode it and write
`<itemKey>.webp` — the exact filename `icon_cache.get_pixmap` looks up.

Keys are the decimal item key from the table header, not the localization id, so
the files land where the GUI already searches. Nothing existing is overwritten
unless `--force` is given.

Usage:
    python -m dmm_parser.tools.extract_icons <game_dir>                       # report only
    python -m dmm_parser.tools.extract_icons <game_dir> --write
    python -m dmm_parser.tools.extract_icons <game_dir> --write --missing-only
    python -m dmm_parser.tools.extract_icons <game_dir> --write --out <dir>
    python -m dmm_parser.tools.extract_icons <game_dir> --key 1006238
    python -m dmm_parser.tools.extract_icons <game_dir> --base-only           # skip dlc packages

A handful of rows resolve to an icon name that has no `.dds` anywhere in the icon
pack; those are reported as `no dds` rather than guessed. Pillow is required for
the DDS decode.
"""

from __future__ import annotations

import argparse
import io
import os
import pathlib
import sys
from typing import Dict, List, Optional, Tuple

from PIL import Image

from .. import item_record, pack_index

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT = os.path.normpath(os.path.join(_HERE, '..', '..'))       # CrimsonGameMods
_REPO_ROOT = os.path.normpath(os.path.join(_APP_ROOT, '..'))        # the fork checkout
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from stringinfo_resolver import StringResolver

STATIC_DIR = 'gamedata/binarystaticinfo__/bin'
INFO_GROUP = '0008'
ICON_GROUP = '0012'                                # ui/texture/icon
QUALITY = 90


def packages(game_dir: str, base_only: bool = False) -> List[Tuple[str, pathlib.Path]]:
    """(label, root) for the base install plus every DLC package on disk."""
    root = pathlib.Path(game_dir)
    found = [('base', root)]
    if base_only:
        return found
    dlc = root / 'dlc'
    if dlc.is_dir():
        for pkg in sorted(p for p in dlc.iterdir() if p.is_dir()):
            found.append((pkg.name, pkg))
    return found


def table_blob(root: pathlib.Path, group: str, table: str, suffix: str) -> Optional[bytes]:
    """A static-info table file, e.g. `iteminfo` + `staticinfoheader`.

    Names in a DLC package carry the package tag (`iteminfo.dlc_01.staticinfoheader`),
    so the table is matched on its base name, not on the exact filename.
    """
    index = pack_index.read_index(str(root), group)
    for position, entry in enumerate(index['files']):
        name = pack_index.entry_name(index, entry)
        if name.split('.')[0] == table and name.endswith(suffix):
            dir_path, _ = pack_index.entry_path(index, position, entry)
            return pack_index.extract(str(root), group, dir_path, name)
    return None


def string_resolver(root: pathlib.Path, group: str) -> StringResolver:
    """Hash->string resolver for one package's `stringinfo` table.

    `StringResolver.load_from_game` reads through the native module, which cannot
    decode the 2.04 name encoding, so the table is read with `pack_index` and handed
    to the resolver as bytes. The record layout the resolver expects —
    `[u32 zero][u32 hash][u32 length][string]` — is the one these files use.
    """
    resolver = StringResolver()
    pabgh = table_blob(root, group, 'stringinfo', 'staticinfoheader')
    pabgb = table_blob(root, group, 'stringinfo', 'staticinfobody')
    if pabgh and pabgb:
        resolver.load_from_pabgb(pabgb, pabgh)
    return resolver


def item_icon_hashes(root: pathlib.Path, group: str) -> Dict[int, int]:
    """item key -> icon string hash, from `iteminfo` rows in table order."""
    header = table_blob(root, group, 'iteminfo', 'staticinfoheader')
    body = table_blob(root, group, 'iteminfo', 'staticinfobody')
    if not header or not body:
        return {}
    icons = {}
    for key, offset in item_record.read_header(header):
        record, _pos = item_record.read_record(body, offset)
        icon_list = record.get('item_icon_list') or []
        if icon_list:
            icons[key] = icon_list[0]['icon_path']
    return icons


def dds_entries(root: pathlib.Path, group: str) -> Dict[str, tuple]:
    """lowercase `.dds` name -> entry, for one pack group of one package."""
    index = pack_index.read_index(str(root), group)
    out = {}
    for entry in index['files']:
        name = pack_index.entry_name(index, entry).lower()
        if name.endswith('.dds'):
            out[name] = entry
    return out


def entry_blob(root: pathlib.Path, group: str, entry: tuple) -> bytes:
    """Decoded entry bytes. Icon entries report codec 1, which the reader does
    not know; their stored size equals the uncompressed size, so they are
    already readable as-is."""
    _node, offset, size, uncompressed, chunk_id, flags, _ext = entry
    raw = pack_index.read_chunk(str(root), group, chunk_id, offset, size)
    codec = flags & 0xF
    if codec in (pack_index.COMP_RAW, 1) or size == uncompressed:
        return raw
    return pack_index.decompress_chunk(str(root), group, chunk_id, offset, size,
                                       codec, uncompressed)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Write item icons from the game install as icons_local/<itemKey>.webp.')
    parser.add_argument('game_dir', help='Crimson Desert install directory')
    parser.add_argument('--out', default=os.path.join(_REPO_ROOT, 'icons_local'),
                        help='icon directory (default: the repo icons_local/)')
    parser.add_argument('--group', default=ICON_GROUP, help='pack group holding the icon dds')
    parser.add_argument('--info-group', default=INFO_GROUP, help='pack group holding the tables')
    parser.add_argument('--base-only', action='store_true', help='ignore dlc packages')
    parser.add_argument('--write', action='store_true', help='write the webp files (default: report only)')
    parser.add_argument('--missing-only', action='store_true', help='skip items that already have a file')
    parser.add_argument('--force', action='store_true', help='overwrite existing files')
    parser.add_argument('--key', type=int, help='only this item key')
    args = parser.parse_args(argv)

    if not os.path.isdir(args.game_dir):
        parser.error(f'not a game install: {args.game_dir}')

    packs = packages(args.game_dir, args.base_only)
    resolvers = {label: string_resolver(root, args.info_group) for label, root in packs}
    icons = {label: dds_entries(root, args.group) for label, root in packs}
    if not any(len(r) for r in resolvers.values()):
        print('error: no stringinfo table resolved any name; cannot resolve icon names')
        return 2

    rows: Dict[int, Tuple[str, int, int]] = {}      # key -> (own package, icon hash, row order)
    for order, (label, root) in enumerate(packs):
        for key, icon_hash in item_icon_hashes(root, args.info_group).items():
            rows.setdefault(key, (label, icon_hash, order))

    os.makedirs(args.out, exist_ok=True)
    counts = {'rows': len(rows), 'named': 0, 'no dds': 0, 'unresolved': 0,
              'existing': 0, 'written': 0}
    per_pkg = {label: {'rows': 0, 'written': 0} for label, _ in packs}
    misses: List[Tuple[int, str]] = []

    for key, (own, icon_hash, order) in sorted(rows.items()):
        if args.key is not None and key != args.key:
            continue
        per_pkg[own]['rows'] += 1
        # The row's own package first, then the base table: a DLC hash may exist
        # only in the base stringinfo, and a base hash only in the DLC one.
        name = ''
        for label, _root in [(own, None)] + [(l, None) for l, _ in packs if l != own]:
            name = (resolvers[label].resolve(icon_hash) or '').strip()
            if name:
                break
        if not name:
            counts['unresolved'] += 1
            continue
        counts['named'] += 1
        dname = name.lower() + '.dds'
        entry = None
        for label, _root in packs:
            if dname in icons[label]:
                entry = (label, icons[label][dname])
                break
        if entry is None:
            counts['no dds'] += 1
            misses.append((key, name))
            continue
        path = os.path.join(args.out, f'{key}.webp')
        if os.path.isfile(path):
            counts['existing'] += 1
            if args.missing_only or not args.force:
                continue
        if not args.write:
            continue
        source, item_entry = entry
        image = Image.open(io.BytesIO(entry_blob(dict(packs)[source], args.group, item_entry)))
        image.save(path, quality=QUALITY)
        counts['written'] += 1
        per_pkg[own]['written'] += 1

    for label in ('rows', 'named', 'no dds', 'unresolved', 'existing', 'written'):
        print(f'{label:10} {counts[label]:6}')
    for label in sorted(per_pkg):
        if per_pkg[label]['written']:
            print(f'  written from {label}: {per_pkg[label]["written"]} '
                  f'(of {per_pkg[label]["rows"]} rows)')
    for key, name in misses[:10]:
        print(f'  no dds: {key} {name}')
    if not args.write:
        print('report only; add --write to create the files')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

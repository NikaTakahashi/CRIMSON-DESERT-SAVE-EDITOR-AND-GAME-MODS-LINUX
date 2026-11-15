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

The pack in the repo is short: 6011 files against the 7068 item rows the install
carries, so 1064 items draw no icon. This walks `iteminfo` rows, takes each row's
`item_icon_list[0].icon_path` hash, resolves it through `stringinfo` to the icon
name, finds that name as a `.dds` in the icon pack group, decodes it and writes
`<itemKey>.webp` — the exact filename `icon_cache.get_pixmap` looks up.

Keys are the decimal item key from the table header, not the localization id, so
the files land where the GUI already searches. Nothing existing is overwritten
unless `--force` is given.

Usage:
    python -m dmm_parser.tools.extract_icons <game_dir>                       # report only
    python -m dmm_parser.tools.extract_icons <game_dir> --write
    python -m dmm_parser.tools.extract_icons <game_dir> --write --missing-only
    python -m dmm_parser.tools.extract_icons <game_dir> --write --out <dir>
    python -m dmm_parser.tools.extract_icons <game_dir> --key 1003774

15 item rows resolve to an icon name that has no `.dds` anywhere on the install
(the string table entry is a prefab display name, not a file name); those are
reported as `no dds`. Pillow is required for the DDS decode.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from typing import Dict, List, Tuple

from PIL import Image

from .. import item_record, pack_index

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT = os.path.normpath(os.path.join(_HERE, '..', '..'))       # CrimsonGameMods
_REPO_ROOT = os.path.normpath(os.path.join(_APP_ROOT, '..'))        # the fork checkout
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from stringinfo_resolver import StringResolver

STATIC_DIR = 'gamedata/binarystaticinfo__/bin'
ITEM_GROUP = '0008'
ICON_GROUP = '0012'                                # ui/texture/icon
QUALITY = 90


def string_resolver(game_dir: str) -> StringResolver:
    """Hash->string resolver for the `stringinfo` table (group 0008).

    `StringResolver.load_from_game` reads through the native module, which cannot
    decode the 2.04 name encoding, so the table is read with `pack_index` and handed
    to the resolver as bytes. The record layout the resolver expects —
    `[u32 zero][u32 hash][u32 length][string]` — is the one these files use.
    """
    resolver = StringResolver()
    pabgh = pack_index.extract(game_dir, ITEM_GROUP, STATIC_DIR, 'stringinfo.staticinfoheader')
    pabgb = pack_index.extract(game_dir, ITEM_GROUP, STATIC_DIR, 'stringinfo.staticinfobody')
    resolver.load_from_pabgb(pabgb, pabgh)
    return resolver


def item_icon_hashes(game_dir: str) -> Dict[int, int]:
    """item key -> icon string hash, from `iteminfo` rows in table order."""
    header = pack_index.extract(game_dir, ITEM_GROUP, STATIC_DIR,
                                'iteminfo.staticinfoheader')
    body = pack_index.extract(game_dir, ITEM_GROUP, STATIC_DIR,
                              'iteminfo.staticinfobody')
    icons = {}
    for key, offset in item_record.read_header(header):
        record, _pos = item_record.read_record(body, offset)
        icon_list = record.get('item_icon_list') or []
        if icon_list:
            icons[key] = icon_list[0]['icon_path']
    return icons


def dds_entries(index: dict) -> Dict[str, tuple]:
    """lowercase `.dds` name -> entry, for one pack group."""
    out = {}
    for entry in index['files']:
        name = pack_index.entry_name(index, entry).lower()
        if name.endswith('.dds'):
            out[name] = entry
    return out


def entry_blob(game_dir: str, group: str, entry: tuple) -> bytes:
    """Decoded entry bytes. Icon entries report codec 1, which the reader does
    not know; their stored size equals the uncompressed size, so they are
    already readable as-is."""
    _node, offset, size, uncompressed, chunk_id, flags, _ext = entry
    raw = pack_index.read_chunk(game_dir, group, chunk_id, offset, size)
    codec = flags & 0xF
    if codec in (pack_index.COMP_RAW, 1) or size == uncompressed:
        return raw
    return pack_index.decompress_chunk(game_dir, group, chunk_id, offset, size,
                                       codec, uncompressed)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Write item icons from the game install as icons_local/<itemKey>.webp.')
    parser.add_argument('game_dir', help='Crimson Desert install directory')
    parser.add_argument('--out', default=os.path.join(_REPO_ROOT, 'icons_local'),
                        help='icon directory (default: the repo icons_local/)')
    parser.add_argument('--group', default=ICON_GROUP, help='pack group holding the icon dds')
    parser.add_argument('--write', action='store_true', help='write the webp files (default: report only)')
    parser.add_argument('--missing-only', action='store_true', help='skip items that already have a file')
    parser.add_argument('--force', action='store_true', help='overwrite existing files')
    parser.add_argument('--key', type=int, help='only this item key')
    args = parser.parse_args(argv)

    if not os.path.isdir(args.game_dir):
        parser.error(f'not a game install: {args.game_dir}')

    resolver = string_resolver(args.game_dir)
    if not len(resolver):
        print('error: stringinfo hash table is empty; cannot resolve icon names')
        return 2

    hashes = item_icon_hashes(args.game_dir)
    index = pack_index.read_index(args.game_dir, args.group)
    entries = dds_entries(index)

    os.makedirs(args.out, exist_ok=True)
    counts = {'rows': len(hashes), 'named': 0, 'dds': 0, 'existing': 0, 'written': 0,
              'unresolved': 0, 'no dds': 0}
    misses: List[Tuple[int, str]] = []

    for key, icon_hash in sorted(hashes.items()):
        if args.key is not None and key != args.key:
            continue
        name = (resolver.resolve(icon_hash) or '').strip()
        if not name:
            counts['unresolved'] += 1
            continue
        counts['named'] += 1
        entry = entries.get(name.lower() + '.dds')
        if entry is None:
            counts['no dds'] += 1
            misses.append((key, name))
            continue
        counts['dds'] += 1
        path = os.path.join(args.out, f'{key}.webp')
        if os.path.isfile(path):
            counts['existing'] += 1
            if not args.force:
                continue
        if not args.write:
            continue
        image = Image.open(io.BytesIO(entry_blob(args.game_dir, args.group, entry)))
        image.save(path, quality=QUALITY)
        counts['written'] += 1

    for label in ('rows', 'named', 'no dds', 'unresolved', 'dds', 'existing', 'written'):
        print(f'{label:10} {counts[label]:6}')
    for key, name in misses[:10]:
        print(f'  no dds: {key} {name}')
    if not args.write:
        print('report only; add --write to create the files')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

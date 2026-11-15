# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""
dmm-parser-build-lang-pack — regenerate the editor's language name packs from the
game install.

The shipped packs were built before the DLC item tables were read, so every
supported pack is short: 5948 item entries against the 8307 item names the install
holds for each of its 14 language tables. This reads every install root's own
`item*.paloc` for each language directory and refreshes the `items` section of each
supported pack, which is what the GUI resolves a display name from.

Packs are written to `locale/`, the folder `gui_i18n._load_names` searches, the
PyInstaller bundle copies and the raw download URL serves. `language/` is the
authoring folder from `TranslationReadMe.txt` and is not read at runtime, so it has
to be regenerated from the same run to stay in step.

Only `items` is touched. `quests`, `missions` and `knowledge` keep whatever the
pack already had, and an entry the pack already has is never overwritten - the packs
carry curated display names the game table does not, so a disagreement is only
reported. Keys stay the decimal item keys the GUI looks up (`key`, not the paloc id
`(key << 32) | 0x70`).

Arabic (`ara`) is on the install but not in `lang_pack_downloader.SUPPORTED_LANGS`,
so it is not written. English needs no pack: the item DB is already English.

Usage:
    python -m dmm_parser.tools.build_lang_pack <game_dir>                  # report only
    python -m dmm_parser.tools.build_lang_pack <game_dir> --write
    python -m dmm_parser.tools.build_lang_pack <game_dir> --write --lang de
    python -m dmm_parser.tools.build_lang_pack <game_dir> --out <dir> --write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Tuple

from .. import pack_index, string_table
from .refresh_item_db import install_roots

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT = os.path.normpath(os.path.join(_HERE, '..', '..'))       # CrimsonGameMods
_REPO_ROOT = os.path.normpath(os.path.join(_APP_ROOT, '..'))        # the fork checkout
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from lang_pack_downloader import NATIVE_NAMES, SUPPORTED_LANGS

# Game string-table language directory -> pack code the GUI uses.
LANG_DIR_TO_CODE: Dict[str, str] = {
    'kor': 'ko',
    'jpn': 'ja',
    'rus': 'ru',
    'tur': 'tr',
    'spa-es': 'es',
    'spa-mx': 'es-mx',
    'fre': 'fr',
    'ger': 'de',
    'ita': 'it',
    'pol': 'pl',
    'por-br': 'pt-br',
    'zho-tw': 'zh-tw',
    'zho-cn': 'zh',
}

CODE_TO_LANG_DIR = {code: lang_dir for lang_dir, code in LANG_DIR_TO_CODE.items()}

ITEM_NAME_PART = 0x70

DEFAULT_OUT = os.path.join(_REPO_ROOT, 'locale')


def item_names_by_language(game_dir: str) -> Dict[str, Dict[int, str]]:
    """Item names per language directory, from every install root's tables.

    Each language lives in its own pack group, so the group's own entry path is
    used instead of `string_table.STRING_DIR`, which is hardcoded to `eng`. A group
    without an index is skipped rather than raising, because not every install has
    every language group.
    """
    names: Dict[str, Dict[int, str]] = {}
    for root, _label in install_roots(game_dir):
        for group in sorted(d for d in os.listdir(root) if len(d) == 4 and d.isdigit()):
            try:
                index = pack_index.read_index(root, group)
            except (OSError, ValueError):
                continue
            for pos, entry in enumerate(index['files']):
                table_dir, name = pack_index.entry_path(index, pos, entry)
                lang = table_dir.rsplit('/', 1)[-1]
                if not name.startswith('item') or not name.endswith('.paloc'):
                    continue
                blob = pack_index.extract(root, group, table_dir, name, index)
                table = names.setdefault(lang, {})
                for record in string_table.iter_entries(blob):
                    if record['key'] & 0xFFFFFFFF == ITEM_NAME_PART:
                        table[record['key'] >> 32] = record['value']
    return names


def merge_items(pack_items: Dict[str, str], game_names: Dict[int, str]) -> Tuple[Dict[str, str], int, int]:
    """Fill a pack's gaps from the game tables; returns (merged, added, differs).

    Keys become the decimal item key, sorted numerically. An entry the pack already
    has is never overwritten: the packs hold curated display names the game table
    does not (`Ogerring` against `Ring des Ogers`, `Ohrring der dunklen Magie`
    against `Ohrring der schwarzen Magie`), so a disagreement is counted as
    `differs` and the pack keeps its value.
    """
    merged = {int(key): value for key, value in pack_items.items()}
    added = differs = 0
    for key, value in game_names.items():
        if key not in merged:
            merged[key] = value
            added += 1
        elif merged[key] != value:
            differs += 1
    return {str(key): merged[key] for key in sorted(merged)}, added, differs


def new_pack(code: str, game_names: Dict[int, str]) -> Dict[str, object]:
    """A pack for a supported language that has no file yet."""
    return {
        '_language': code,
        '_generated_by': 'build_lang_pack.py',
        'items': {str(key): game_names[key] for key in sorted(game_names)},
        '_language_name': NATIVE_NAMES.get(code, code),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Refresh language name packs from the game install.')
    parser.add_argument('game_dir', help='Crimson Desert install directory')
    parser.add_argument('--out', default=DEFAULT_OUT, help='pack directory (default: the repo language/)')
    parser.add_argument('--lang', action='append', help='only this pack code; repeatable')
    parser.add_argument('--write', action='store_true', help='write the packs (default: report only)')
    args = parser.parse_args(argv)

    if not os.path.isdir(args.game_dir):
        parser.error(f'not a game install: {args.game_dir}')

    by_lang = item_names_by_language(args.game_dir)
    codes = args.lang or [code for code in SUPPORTED_LANGS if code in CODE_TO_LANG_DIR]
    total_added = total_differs = 0
    for code in codes:
        if code not in CODE_TO_LANG_DIR:
            print(f'{code:7} no game language table maps to this pack code')
            continue
        game_names = by_lang.get(CODE_TO_LANG_DIR[code], {})
        if not game_names:
            print(f'{code:7} no {CODE_TO_LANG_DIR[code]} table on this install')
            continue
        path = os.path.join(args.out, f'names_{code}.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as handle:
                pack = json.load(handle)
            merged, added, differs = merge_items(pack.get('items', {}), game_names)
            if args.write:
                pack['items'] = merged          # keeps the section order
                with open(path, 'w', encoding='utf-8') as handle:
                    json.dump(pack, handle, ensure_ascii=False, indent=2)
        else:
            merged, added, differs = {str(k): game_names[k] for k in sorted(game_names)}, len(game_names), 0
            if args.write:
                with open(path, 'w', encoding='utf-8') as handle:
                    json.dump(new_pack(code, game_names), handle, ensure_ascii=False, indent=2)
        total_added += added
        total_differs += differs
        print(f'{code:7} pack {len(merged):5} game {len(game_names):5} added {added:5} differs {differs:2}')
    print(f'total: added {total_added}, differs (kept) {total_differs}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

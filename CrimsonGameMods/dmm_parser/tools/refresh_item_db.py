# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser

"""Rebuild the editor's item DB from the game install instead of the community
mapping, so items added after the mapping was captured are covered.

The item table is read with the 2.04 readers in `dmm_parser.pack_index` /
`dmm_parser.item_record` (the packaged native extension cannot read current
game data). Existing entries keep their display name and category; entries the
game has but the DB does not are added with the display name when the string
table can supply one, otherwise with the internal name.

Display names live in the `.paloc` string tables. The ChaCha20 layer is handled
in pure Python (`dmm_parser.pack_crypto`), and `dmm_parser.string_table` reads
the entries stored as plain literals - 6 on `item.paloc`, cross-checked against
an independent dump of that table. The rest of the entry stream is prefix-coded
against a string dictionary the game builds at pack time and does not ship in
the table, so the native `parse_paloc_bytes` fails ("not enough data") on current
data and most names stay internal. On current game data every record's
`item_name.default` is the decimal paloc id `(key << 32) | 0x70`, not localized
text, so a name only appears when the record itself carries text or the string
table has the entry.

Usage:
    python -m dmm_parser.tools.refresh_item_db <game_dir>              # report only
    python -m dmm_parser.tools.refresh_item_db <game_dir> --write      # update the DB file
    python -m dmm_parser.tools.refresh_item_db <game_dir> --out path.json --write
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .. import string_table
from ..item_record import check_boundaries, read_header, read_record
from ..pack_index import extract, read_index

_PYTHON_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".."))
if _PYTHON_ROOT not in sys.path:
    sys.path.insert(0, _PYTHON_ROOT)

ITEM_GROUP = '0008'
ITEM_DIR = 'gamedata/binarystaticinfo__/bin'
BODY = 'iteminfo.staticinfobody'
HEADER = 'iteminfo.staticinfoheader'
STRING_GROUP = '0020'
ITEM_STRINGS = 'item.paloc'

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'item_names.json')


def display_name(record: dict, names: dict[int, str] | None = None) -> str:
    """Localized default, else the string-table entry, else the internal name."""
    default = record['item_name']['default']
    if default and default != str(record['item_name']['index']):
        return default
    if names:
        name = names.get(record['item_name']['index'])
        if name:
            return name
    return record['string_key']


def read_table(game_dir: str) -> list[dict]:
    index = read_index(game_dir, ITEM_GROUP)
    body = extract(game_dir, ITEM_GROUP, ITEM_DIR, BODY, index)
    header = extract(game_dir, ITEM_GROUP, ITEM_DIR, HEADER, index)
    rows = read_header(header)
    bad = check_boundaries(header, body)
    if bad:
        raise ValueError(f"{len(bad)} records do not end on the next row start: {bad[:5]}")
    records = []
    for key, offset in rows:
        records.append(read_record(body, offset)[0])
    return records


def merge(records: list[dict], db: dict, names: dict[int, str] | None = None) -> tuple[list[dict], list[dict]]:
    existing = {entry['itemKey']: entry for entry in db.get('items', [])}
    items = list(existing.values())
    added = []
    for record in records:
        if record['key'] in existing:
            continue
        entry = {
            'itemKey': record['key'],
            'name': display_name(record, names),
            'category': 'Misc',
            'internalName': record['string_key'],
            'maxStack': record['max_stack_count'],
        }
        items.append(entry)
        added.append(entry)
    items.sort(key=lambda e: e['itemKey'])
    return items, added


def sync_sqlite(added: list[dict]) -> int:
    """Add the new entries through the GUI's own ItemNameDB path (its SQLite file)."""
    from item_db import ItemNameDB
    from models import ItemInfo

    store = ItemNameDB()
    for entry in added:
        store.items[entry['itemKey']] = ItemInfo(
            item_key=entry['itemKey'],
            name=entry['name'],
            internal_name=entry['internalName'],
            category=entry['category'],
            max_stack=entry['maxStack'],
        )
    store.save()
    return len(store.items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Rebuild item_names.json from the game install.')
    parser.add_argument('game_dir', help='Crimson Desert install directory')
    parser.add_argument('--db', default=DEFAULT_DB, help='existing item_names.json to merge into')
    parser.add_argument('--out', help='output path (default: write back to --db)')
    parser.add_argument('--write', action='store_true', help='write the merged DB (default: report only)')
    parser.add_argument('--sqlite', action='store_true', help='also add the new entries to the GUI SQLite DB')
    parser.add_argument('--show', type=int, default=15, help='how many added items to print')
    args = parser.parse_args(argv)

    if not os.path.isdir(args.game_dir):
        print(f"Error: '{args.game_dir}' is not a directory", file=sys.stderr)
        return 1

    records = read_table(args.game_dir)
    try:
        names = string_table.read_table(args.game_dir, STRING_GROUP, ITEM_STRINGS)
    except ValueError as exc:
        print(f"string table: {exc}", file=sys.stderr)
        names = {}
    if os.path.exists(args.db):
        with open(args.db, encoding='utf-8') as fh:
            db = json.load(fh)
    else:
        db = {'items': [], 'version': 4}

    items, added = merge(records, db, names)
    print(f"game rows: {len(records)} | db entries: {len(db.get('items', []))} | added: {len(added)}")
    print(f"string table: {len(names)} readable entries (the rest is dictionary-coded)")

    for entry in added[:args.show]:
        print(f"  {entry['itemKey']:>8}  {entry['name']:<34} maxStack={entry['maxStack']}")

    if args.write:
        out = args.out or args.db
        doc = {'items': items, 'version': db.get('version', 4)}
        with open(out, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        print(f"wrote {len(items)} entries to {out}")
        if args.sqlite:
            total = sync_sqlite(added)
            print(f"sqlite now holds {total} items")
    else:
        print("report only; pass --write (and --sqlite) to update the DB")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

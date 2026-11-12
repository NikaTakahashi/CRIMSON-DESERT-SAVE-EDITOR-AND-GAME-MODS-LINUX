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

Entries the game has but the DB does not also get the two values the save side
needs: a category from the GUI's own classifier (`item_db._guess_item_category`)
and an inventory bag key. The bag rule is `1` for equip rows and `2` otherwise
(`bag_key` below), which reproduces all 5886 curated entries of
`item_category_map.json` on the current install, so it can fill the keys the map
is missing. `--write-map` does that.

Usage:
    python -m dmm_parser.tools.refresh_item_db <game_dir>              # report only
    python -m dmm_parser.tools.refresh_item_db <game_dir> --write      # update the DB file
    python -m dmm_parser.tools.refresh_item_db <game_dir> --out path.json --write
    python -m dmm_parser.tools.refresh_item_db <game_dir> --write --write-map
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

# One classifier for both the tool and the GUI: the tool must not invent a second
# set of category rules that the app would then disagree with.
from item_db import _guess_item_category

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


def bag_key(record: dict) -> int:
    """Inventory bag the save side uses: equip rows go to bag 1, the rest to bag 2.

    Reproduces all 5886 curated entries of `item_category_map.json` on the current
    install, so it is a safe stand-in for keys the map is missing.
    """
    return 1 if record.get('equip_type_info') else 2


def read_names(game_dir: str, index: dict | None = None) -> dict[int, str]:
    """Item display names that the string table stores as plain literals."""
    return string_table.read_table(game_dir, STRING_GROUP, ITEM_STRINGS, index)


def merge(records: list[dict], db: dict, names: dict[int, str] | None = None) -> tuple[list[dict], list[dict]]:
    existing = {entry['itemKey']: entry for entry in db.get('items', [])}
    items = list(existing.values())
    added = []
    for record in records:
        if record['key'] in existing:
            continue
        internal = record['string_key']
        entry = {
            'itemKey': record['key'],
            'name': display_name(record, names),
            'category': _guess_item_category(internal),
            'internalName': internal,
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


def sync_map_sqlite(mapping: dict[int, int]) -> int:
    """Mirror bag keys into the SQLite table the game-mods GUI reads.

    `parc_inserter3._get_item_bag_key` reads `item_category_map` from the database
    with no JSON fallback, so the game-mods app only sees bag keys that are in the
    table. Keys already in the table keep their curated value; only the ones the
    rule derived are inserted.
    """
    from data_db import get_connection, open_writable, reset_connection

    present = {row['item_key'] for row in get_connection().execute(
        "SELECT item_key FROM item_category_map")}
    rows = [(key, value) for key, value in mapping.items() if key not in present]
    if not rows:
        return len(present)
    conn = open_writable()
    conn.executemany("INSERT OR REPLACE INTO item_category_map VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    reset_connection()
    return len(present) + len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Rebuild item_names.json from the game install.')
    parser.add_argument('game_dir', help='Crimson Desert install directory')
    parser.add_argument('--db', default=DEFAULT_DB, help='existing item_names.json to merge into')
    parser.add_argument('--out', help='output path (default: write back to --db)')
    parser.add_argument('--write', action='store_true', help='write the merged DB (default: report only)')
    parser.add_argument('--sqlite', action='store_true', help='also add the new entries to the GUI SQLite DB')
    parser.add_argument('--map', help='item_category_map.json to fill in (default: next to --db)')
    parser.add_argument('--write-map', action='store_true', help='add bag keys for game items the map is missing')
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
    from_table = sum(1 for e in added if names.get((e['itemKey'] << 32) | 0x70))
    print(f"added names: {from_table} from the string table, {len(added) - from_table} internal")
    categories: dict[str, int] = {}
    for entry in added:
        categories[entry['category']] = categories.get(entry['category'], 0) + 1
    print("added categories: " + ", ".join(
        f"{cat}={count}" for cat, count in sorted(categories.items(), key=lambda x: -x[1])))

    by_key = {record['key']: record for record in records}
    map_path = args.map or os.path.join(os.path.dirname(os.path.abspath(args.db)), 'item_category_map.json')
    mapping = {}
    if os.path.isfile(map_path):
        with open(map_path, encoding='utf-8') as fh:
            mapping = json.load(fh)
        checked = [(k, v) for k, v in mapping.items() if int(k) in by_key]
        disagreed = sum(1 for k, v in checked if int(v) != bag_key(by_key[int(k)]))
        missing = [r for r in records if str(r['key']) not in mapping]
        print(f"bag map: {len(mapping)} entries, {len(missing)} game items missing; "
              f"rule agrees with the curated map on {len(checked) - disagreed}/{len(checked)}")
    else:
        missing = [r for r in records if str(r['key']) not in mapping]
        print(f"bag map: {map_path} not found; {len(missing)} items would need a bag key")

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
        if args.write_map and missing:
            for record in missing:
                mapping[str(record['key'])] = bag_key(record)
            with open(map_path, 'w', encoding='utf-8') as fh:
                json.dump(mapping, fh, ensure_ascii=False, indent=2)
            print(f"wrote {len(missing)} bag keys to {map_path}")
        if args.write_map and args.sqlite:
            # The game-mods GUI reads bag keys from the DB table, not the JSON, so
            # a JSON-only write leaves the derived keys invisible to that app.
            total = sync_map_sqlite({int(k): int(v) for k, v in mapping.items()})
            print(f"sqlite bag map now holds {total} rows")
    else:
        print("report only; pass --write (and --sqlite, --write-map) to update the files")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

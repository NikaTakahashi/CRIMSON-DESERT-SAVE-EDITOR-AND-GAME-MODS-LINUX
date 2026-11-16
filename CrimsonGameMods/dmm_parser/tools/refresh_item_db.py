# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser

"""Rebuild the editor's item DB from the game install instead of the community
mapping, so items added after the mapping was captured are covered.

The item table is read with the 2.04 readers in `dmm_parser.pack_index` /
`dmm_parser.item_record` (the packaged native extension cannot read current
game data). Existing entries keep their display name and category; entries the
game has but the DB does not are added, and an entry whose stored name is still
the internal identifier is corrected - that name was a fallback, not a rename the
user made.

Display names live in the `.paloc` string tables. The ChaCha20 layer is handled
in pure Python (`dmm_parser.pack_crypto`), and `dmm_parser.string_table` decodes
the LZ4 block that holds the entry stream, which gives the whole table: 14082
records on `item.paloc`, 2686 on `item.dlc_01.paloc`. Each install root has its
own table, and the base table has no entry for a DLC item, so `read_names` reads
every root. On current game data every record's `item_name.default` is the decimal
paloc id `(key << 32) | 0x70`, not localized text, so a name comes from the table
or from `item_db.clean_display_name` applied to the internal identifier; 72 of the
7068 base records have no entry at all, and those keep the normalized identifier.

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
from ..pack_index import entry_path, extract, read_index

_PYTHON_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".."))
if _PYTHON_ROOT not in sys.path:
    sys.path.insert(0, _PYTHON_ROOT)

# One classifier and one name normalizer for both the tool and the GUI: the tool
# must not invent a second set of rules that the app would then disagree with.
from item_db import _guess_item_category, clean_display_name

ITEM_GROUP = '0008'
ITEM_DIR = 'gamedata/binarystaticinfo__/bin'
BODY = 'iteminfo.staticinfobody'
HEADER = 'iteminfo.staticinfoheader'
STRING_GROUP = '0020'
ITEM_STRINGS = 'item.paloc'

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'item_names.json')


def display_name(record: dict, names: dict[int, str] | None = None) -> str:
    """Localized default, else the string-table entry, else the normalized identifier."""
    default = record['item_name']['default']
    if default and default != str(record['item_name']['index']):
        return default
    if names:
        name = names.get(record['item_name']['index'])
        if name:
            return name
    return clean_display_name(record['string_key'])


def install_roots(game_dir: str) -> list[tuple[str, str]]:
    """The install plus every DLC tree, each of which carries its own item table."""
    roots = [(game_dir, 'base game')]
    dlc_root = os.path.join(game_dir, 'dlc')
    if os.path.isdir(dlc_root):
        for name in sorted(os.listdir(dlc_root)):
            path = os.path.join(dlc_root, name)
            if os.path.isdir(path):
                roots.append((path, name))
    return roots


def read_table(game_dir: str) -> list[dict]:
    """Every item record on the install: the base table plus each DLC table.

    Group 0008 holds `iteminfo.staticinfobody` for the base game and
    `iteminfo.<dlc_id>.staticinfobody` for each DLC. Reading only the base file
    left the DLC items out of the editor's item list, so a save holding one of
    them showed `Unknown (key)` with no bag key.
    """
    records: list[dict] = []
    for root, label in install_roots(game_dir):
        index = read_index(root, ITEM_GROUP)
        entries = {entry_path(index, position, entry): entry
                   for position, entry in enumerate(index['files'])}
        for dir_path, file_name in sorted(entries):
            if dir_path != ITEM_DIR or not file_name.startswith('iteminfo'):
                continue
            if not file_name.endswith('staticinfobody'):
                continue
            header_name = f"{file_name[:-len('body')]}header"
            if (dir_path, header_name) not in entries:
                continue
            body = extract(root, ITEM_GROUP, dir_path, file_name, index)
            header = extract(root, ITEM_GROUP, dir_path, header_name, index)
            rows = read_header(header)
            bad = check_boundaries(header, body)
            if bad:
                raise ValueError(
                    f"{len(bad)} records do not end on the next row start: {bad[:5]}")
            for key, offset in rows:
                record = read_record(body, offset)[0]
                record['source'] = label
                records.append(record)
    return records


def bag_key(record: dict) -> int:
    """Inventory bag the save side uses: equip rows go to bag 1, the rest to bag 2.

    Reproduces all 5886 curated entries of `item_category_map.json` on the current
    install, so it is a safe stand-in for keys the map is missing.
    """
    return 1 if record.get('equip_type_info') else 2


def enchant_limits(records: list[dict]) -> dict[int, int]:
    """The highest enchant level each equipment item can reach on this install.

    `enchant_data_list` holds one entry per level the blacksmith can craft for the
    item, so the highest level present is the game's own limit. The curated map
    predates the DLC tables: every DLC weapon was absent from it, so the GUI showed
    a bare `+N` with no limit, and items the curated map had as 0 that the game
    data takes to +10 could not be raised.
    """
    limits: dict[int, int] = {}
    for record in records:
        edl = record.get('enchant_data_list') or []
        if not record.get('equip_type_info') or not edl:
            continue
        limits[record['key']] = max(entry.get('level', 0) for entry in edl)
    return limits


def item_table_file(index: dict) -> str | None:
    """The item-name string table inside a pack group.

    `item.paloc` for the base game, `item.<dlc_id>.paloc` for a DLC tree;
    `itemgroup.paloc` is the category table and is not a name table.
    """
    for position, entry in enumerate(index['files']):
        dir_path, file_name = entry_path(index, position, entry)
        if dir_path == string_table.STRING_DIR and file_name.startswith('item.'):
            return file_name
    return None


def read_names(game_dir: str, index: dict | None = None) -> dict[int, str]:
    """Item display names from every install root's own string table.

    Each DLC tree carries its own `item.<dlc_id>.paloc`, and the base table has no
    entry for a DLC item, so reading only `item.paloc` left every DLC name as the
    internal identifier.
    """
    names: dict[int, str] = {}
    for root, _label in install_roots(game_dir):
        root_index = index if index and root == game_dir else read_index(root, STRING_GROUP)
        table = item_table_file(root_index)
        if table:
            names.update(string_table.read_table(root, STRING_GROUP, table, root_index))
    return names


def merge(records: list[dict], db: dict, names: dict[int, str] | None = None
          ) -> tuple[list[dict], list[dict], list[dict]]:
    """Merge game records into the existing entries: (items, added, renamed).

    An entry whose stored name is the internal identifier is a fallback, not a user
    rename, so the string table replaces it; a name the user set is left alone.
    """
    existing = {entry['itemKey']: entry for entry in db.get('items', [])}
    items = list(existing.values())
    added = []
    renamed = []
    for record in records:
        entry = existing.get(record['key'])
        if entry is None:
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
        elif not entry['name'] or entry['name'] == entry['internalName']:
            resolved = display_name(record, names)
            if resolved != entry['name']:
                entry['name'] = resolved
                renamed.append(entry)
    items.sort(key=lambda e: e['itemKey'])
    return items, added, renamed


def sync_sqlite(entries: list[dict]) -> int:
    """Write the merged entries through the GUI's own ItemNameDB path (its SQLite file).

    Takes every entry, not only the added ones, so a name the merge corrected is
    written as well.
    """
    from item_db import ItemNameDB
    from models import ItemInfo

    store = ItemNameDB()
    for entry in entries:
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


def sync_enchant_sqlite(limits: dict[int, int]) -> int:
    """Mirror the derived enchant limits into the table the game-mods GUI reads.

    `main_window` builds `_max_enchant_map` from `item_enchant_limits` with no JSON
    fallback, so a derived limit only reaches that app through the table.
    """
    from data_db import open_writable, reset_connection

    conn = open_writable()
    conn.executemany("INSERT OR REPLACE INTO item_enchant_limits VALUES (?, ?)",
                     sorted(limits.items()))
    total = conn.execute("SELECT COUNT(*) FROM item_enchant_limits").fetchone()[0]
    conn.commit()
    conn.close()
    reset_connection()
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Rebuild item_names.json from the game install.')
    parser.add_argument('game_dir', help='Crimson Desert install directory')
    parser.add_argument('--db', default=DEFAULT_DB, help='existing item_names.json to merge into')
    parser.add_argument('--out', help='output path (default: write back to --db)')
    parser.add_argument('--write', action='store_true', help='write the merged DB (default: report only)')
    parser.add_argument('--sqlite', action='store_true', help='also add the new entries to the GUI SQLite DB')
    parser.add_argument('--map', help='item_category_map.json to fill in (default: next to --db)')
    parser.add_argument('--write-map', action='store_true', help='add bag keys for game items the map is missing')
    parser.add_argument('--enchant-map', help='max_enchant_map.json to fill in (default: next to --db)')
    parser.add_argument('--write-enchant', action='store_true',
                        help='write the enchant limits derived from the game data, replacing the curated map')
    parser.add_argument('--show', type=int, default=15, help='how many added items to print')
    args = parser.parse_args(argv)

    if not os.path.isdir(args.game_dir):
        print(f"Error: '{args.game_dir}' is not a directory", file=sys.stderr)
        return 1

    records = read_table(args.game_dir)
    try:
        names = read_names(args.game_dir)
    except ValueError as exc:
        print(f"string table: {exc}", file=sys.stderr)
        names = {}
    if os.path.exists(args.db):
        with open(args.db, encoding='utf-8') as fh:
            db = json.load(fh)
    else:
        db = {'items': [], 'version': 4}

    items, added, renamed = merge(records, db, names)
    sources: dict[str, int] = {}
    for record in records:
        sources[record['source']] = sources.get(record['source'], 0) + 1
    print(f"item tables: " + ", ".join(f"{label}={n}" for label, n in sorted(sources.items())))
    print(f"game rows: {len(records)} | db entries: {len(db.get('items', []))} | added: {len(added)} "
          f"| names corrected: {len(renamed)}")
    print(f"string table: {len(names)} entries decoded from every install root")
    from_table = sum(1 for e in items if names.get((e['itemKey'] << 32) | 0x70))
    print(f"names: {from_table} from the string table, {len(items) - from_table} normalized identifier")
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

    limits = enchant_limits(records)
    enchant_path = args.enchant_map or os.path.join(
        os.path.dirname(os.path.abspath(args.db)), 'max_enchant_map.json')
    curated = {}
    if os.path.isfile(enchant_path):
        with open(enchant_path, encoding='utf-8') as fh:
            curated = json.load(fh)
    limit_missing = [k for k in limits if str(k) not in curated]
    limit_disagreed = [(k, v, curated[str(k)]) for k, v in limits.items()
                       if str(k) in curated and curated[str(k)] != v]
    print(f"enchant limits: {len(limits)} equipment items; {len(curated)} curated entries, "
          f"{len(limit_missing)} game items missing, {len(limit_disagreed)} curated values below the game limit")

    for entry in added[:args.show]:
        print(f"  {entry['itemKey']:>8}  {entry['name']:<34} maxStack={entry['maxStack']}")

    if args.write:
        out = args.out or args.db
        doc = {'items': items, 'version': db.get('version', 4)}
        with open(out, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        print(f"wrote {len(items)} entries to {out}")
        if args.sqlite:
            total = sync_sqlite(items)
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
    if args.write_enchant:
        ordered = sorted(limits.items(), key=lambda item: int(item[0]))
        with open(enchant_path, 'w', encoding='utf-8') as fh:
            json.dump({str(key): value for key, value in ordered}, fh)
        print(f"wrote {len(limits)} enchant limits to {enchant_path}")
        if args.sqlite:
            print(f"sqlite enchant table now holds {sync_enchant_sqlite(limits)} rows")
    elif not args.write:
        print("report only; pass --write (and --sqlite, --write-map, --write-enchant) to update the files")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

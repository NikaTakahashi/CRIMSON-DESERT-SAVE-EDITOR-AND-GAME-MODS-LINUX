# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

r"""Regression tests for the pure-Python 2.04 readers.

These pin the two things that broke when the game moved to 2.04: the delta
LEB128 name trie, and the reordered ItemInfo record fields. They need a game
install, so they skip when none is available (same convention as the Go
fixtures that look for F:\CDump).

Run:
    python -m dmm_parser.tools._test_readers
    CD_GAME_DIR="/path/to/Crimson Desert" python -m dmm_parser.tools._test_readers
"""

from __future__ import annotations

import json
import os
import struct
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _PYTHON_ROOT not in sys.path:
    sys.path.insert(0, _PYTHON_ROOT)

from dmm_parser import pack_index  # noqa: E402
from dmm_parser import item_record  # noqa: E402
from dmm_parser import string_table  # noqa: E402
from dmm_parser.tools import refresh_item_db  # noqa: E402

GAME_DIR = os.environ.get("CD_GAME_DIR", r"F:\CDump")
GROUP = "0008"
ITEM_DIR = "gamedata/binarystaticinfo__/bin"
STRING_GROUP = "0020"


def have_game() -> bool:
    return os.path.isdir(os.path.join(GAME_DIR, GROUP))


def have_strings() -> bool:
    return os.path.isdir(os.path.join(GAME_DIR, STRING_GROUP))


@unittest.skipUnless(have_game(), f"no game install at {GAME_DIR}")
class PackIndexTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = pack_index.read_index(GAME_DIR, GROUP)

    def test_known_item_table_files_resolve(self):
        for name in (refresh_item_db.HEADER, refresh_item_db.BODY):
            entry = pack_index.find_entry(self.index, ITEM_DIR, name)
            position = self.index["files"].index(entry)
            self.assertEqual(pack_index.entry_path(self.index, position, entry), (ITEM_DIR, name))

    def test_names_need_the_delta_trie_encoding(self):
        entry = pack_index.find_entry(self.index, ITEM_DIR, refresh_item_db.BODY)
        decoded = pack_index.entry_name(self.index, entry)
        try:
            legacy = pack_index.resolve_name(self.index["file_buf"], entry[0], False)
        except struct.error:
            legacy = ""
        self.assertEqual(decoded, "iteminfo.staticinfobody")
        self.assertNotEqual(legacy, decoded, "delta trie decode regressed to the pre-2.04 reader")


@unittest.skipUnless(have_game(), f"no game install at {GAME_DIR}")
class ItemRecordTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = pack_index.read_index(GAME_DIR, GROUP)
        cls.header = pack_index.extract(GAME_DIR, GROUP, ITEM_DIR, refresh_item_db.HEADER, cls.index)
        cls.body = pack_index.extract(GAME_DIR, GROUP, ITEM_DIR, refresh_item_db.BODY, cls.index)
        cls.rows = item_record.read_header(cls.header)

    def test_every_record_ends_on_the_next_row(self):
        bad = item_record.check_boundaries(self.header, self.body)
        self.assertEqual(bad, [], f"{len(bad)} misaligned records, first: {bad[:3]}")

    def test_item_name_index_is_the_paloc_id(self):
        for key, offset in self.rows:
            record, _ = item_record.read_record(self.body, offset)
            loc = record["item_name"]
            self.assertEqual(loc["category"], 7)
            self.assertEqual(loc["index"], (key << 32) | 0x70, f"paloc id mismatch for {key}")

    def test_item_desc_index_is_the_desc_paloc_id(self):
        for key, offset in self.rows:
            record, _ = item_record.read_record(self.body, offset)
            self.assertEqual(record["item_desc"]["index"], (key << 32) | 0x71,
                             f"desc paloc id mismatch for {key}")

    def test_display_name_uses_the_string_table_only_where_it_can(self):
        # Every record's default is the decimal paloc id, so names come from the
        # string table's plain entries or fall back to the internal name.
        names = string_table.read_table(GAME_DIR, STRING_GROUP, refresh_item_db.ITEM_STRINGS)
        covered = 0
        for key, offset in self.rows:
            record, _ = item_record.read_record(self.body, offset)
            self.assertEqual(record["item_name"]["default"], str(record["item_name"]["index"]))
            loc = record["item_name"]["index"]
            if loc in names:
                covered += 1
                self.assertEqual(refresh_item_db.display_name(record, names), names[loc],
                                 f"string table name ignored for {key}")
            else:
                self.assertEqual(refresh_item_db.display_name(record, names), record["string_key"],
                                 f"unexpected localized text for {key}")
        self.assertGreater(covered, 0, "no plain entry reached the display name")
        self.assertLess(covered, len(self.rows),
                        "coverage must stay partial while the dictionary codec is undecoded")

    def test_arrow_row_decodes_to_known_values(self):
        record, consumed = item_record.read_record(self.body, self.rows[0][1])
        self.assertEqual(record["key"], 2200)
        self.assertEqual(record["string_key"], "Pyeonjeon_Arrow")
        self.assertEqual(record["max_stack_count"], 100)
        self.assertEqual(consumed - self.rows[0][1], self.rows[1][1] - self.rows[0][1])


def _plain_blob(entries, output_size=None):
    """A paloc blob: header, zero block, then plain entries at the stream start."""
    blob = bytearray(b'paloc\x00' + b'\0' * (string_table.STREAM_OFFSET - 6))
    for key, value in entries:
        blob += struct.pack('<I', len(key)) + key.encode() + struct.pack('<I', len(value)) + value.encode()
    stream = len(blob) - string_table.STREAM_OFFSET
    blob[9:13] = struct.pack('<I', stream)
    blob[13:17] = struct.pack('<I', output_size if output_size is not None else stream)
    return bytes(blob)


class StringTableFormatTest(unittest.TestCase):

    def test_header_reports_the_stored_stream_and_the_expanded_size(self):
        blob = _plain_blob([('4294967408', 'Copper')], output_size=1620928)
        self.assertEqual(string_table.parse_header(blob), {
            'stream_size': len(blob) - string_table.STREAM_OFFSET,
            'output_size': 1620928,
        })

    def test_plain_entry_round_trips(self):
        blob = _plain_blob([('9448928051312', 'Stub Arrow')])
        self.assertEqual(list(string_table.iter_plain_entries(blob)),
                         [{'key': 9448928051312, 'value': 'Stub Arrow'}])

    def test_entries_inside_the_zero_block_are_not_read(self):
        pair = struct.pack('<I', 10) + b'4294967408' + struct.pack('<I', 6) + b'Copper'
        blob = bytearray(_plain_blob([]))
        blob[200:200 + len(pair)] = pair
        self.assertEqual(list(string_table.iter_plain_entries(bytes(blob))), [])

    def test_dictionary_coded_values_are_skipped(self):
        entry = struct.pack('<I', 13) + b'9448928051312' + struct.pack('<I', 4) + b'\x80\x00\x04\x1c'
        blob = bytearray(_plain_blob([]))
        blob[string_table.STREAM_OFFSET:] = entry
        self.assertEqual(list(string_table.iter_plain_entries(bytes(blob))), [])


@unittest.skipUnless(have_strings(), f"no string table group at {GAME_DIR}/{STRING_GROUP}")
class StringTableGameTest(unittest.TestCase):

    def test_known_plain_entries_match_the_reference_dump(self):
        names = string_table.read_table(GAME_DIR, STRING_GROUP, refresh_item_db.ITEM_STRINGS)
        self.assertEqual(names.get((1 << 32) | 0x70), "Copper")
        self.assertEqual(names.get((2200 << 32) | 0x70), "Stub Arrow")

    def test_stored_stream_is_smaller_than_the_expanded_size(self):
        index = pack_index.read_index(GAME_DIR, STRING_GROUP)
        blob = pack_index.extract(GAME_DIR, STRING_GROUP, string_table.STRING_DIR,
                                  refresh_item_db.ITEM_STRINGS, index)
        header = string_table.parse_header(blob)
        self.assertEqual(header['stream_size'], len(blob) - string_table.STREAM_OFFSET)
        self.assertGreater(header['output_size'], header['stream_size'])


class DisplayNameTest(unittest.TestCase):

    def test_string_table_name_is_used_when_the_record_has_no_text(self):
        record = {"item_name": {"category": 7, "index": 9448928051312, "default": "9448928051312"},
                  "string_key": "Pyeonjeon_Arrow"}
        self.assertEqual(refresh_item_db.display_name(record, {9448928051312: "Stub Arrow"}), "Stub Arrow")

    def test_missing_string_table_entry_falls_back_to_the_internal_name(self):
        record = {"item_name": {"category": 7, "index": 123, "default": "123"},
                  "string_key": "Small_Fire_Bomb"}
        self.assertEqual(refresh_item_db.display_name(record, {9448928051312: "Stub Arrow"}),
                         "Small_Fire_Bomb")

    def test_localized_default_is_used_when_present(self):
        record = {"item_name": {"category": 7, "index": 123, "default": "Stub Arrow"},
                  "string_key": "Pyeonjeon_Arrow"}
        self.assertEqual(refresh_item_db.display_name(record), "Stub Arrow")
        self.assertEqual(refresh_item_db.display_name(record, {123: "From The String Table"}),
                         "Stub Arrow", "the string table must not override record text")

    def test_numeric_default_falls_back_to_internal_name(self):
        record = {"item_name": {"category": 7, "index": 123, "default": "123"},
                  "string_key": "Small_Fire_Bomb"}
        self.assertEqual(refresh_item_db.display_name(record), "Small_Fire_Bomb")


class DerivationTest(unittest.TestCase):

    def test_bag_key_uses_equip_type_and_defaults_to_the_general_bag(self):
        self.assertEqual(refresh_item_db.bag_key({"equip_type_info": 1963713749}), 1)
        self.assertEqual(refresh_item_db.bag_key({"equip_type_info": 0}), 2)

    def test_added_entries_get_category_and_stack_from_the_record(self):
        record = {"key": 1004051, "string_key": "Quest_Paper_Military_Notice",
                  "max_stack_count": 1, "equip_type_info": 0,
                  "item_name": {"index": 1004051, "default": "1004051"}}
        items, added = refresh_item_db.merge([record], {"items": []})
        self.assertEqual(added[0]["category"], "Quest")
        self.assertEqual(added[0]["maxStack"], 1)

    def test_merge_keeps_names_and_categories_the_user_already_has(self):
        record = {"key": 1, "string_key": "Money_Copper", "max_stack_count": 100000,
                  "equip_type_info": 0, "item_name": {"index": 1, "default": "1"}}
        db = {"items": [{"itemKey": 1, "name": "Renamed Copper", "category": "Currency",
                         "internalName": "Money_Copper", "maxStack": 100000}]}
        items, added = refresh_item_db.merge([record], db)
        self.assertEqual(added, [])
        self.assertEqual(items[0]["name"], "Renamed Copper")
        self.assertEqual(items[0]["category"], "Currency")


@unittest.skipUnless(have_game(), f"no game install at {GAME_DIR}")
class BagMapRuleTest(unittest.TestCase):
    """The save side picks the inventory bag from `item_category_map.json`; the rule
    in `refresh_item_db.bag_key` must agree with the curated map, otherwise new
    items land in the wrong bag."""

    def test_rule_reproduces_the_curated_map_on_the_current_install(self):
        map_path = os.path.join(_PYTHON_ROOT, "data", "item_category_map.json")
        if not os.path.isfile(map_path):
            self.skipTest(f"no curated map at {map_path}")
        with open(map_path, encoding="utf-8") as fh:
            curated = json.load(fh)
        records = {int(record["key"]): record for record in refresh_item_db.read_table(GAME_DIR)}
        checked = [(int(key), value) for key, value in curated.items() if int(key) in records]
        self.assertGreater(len(checked), 0, "the map and the install share no item keys")
        disagreed = [key for key, value in checked if int(value) != refresh_item_db.bag_key(records[key])]
        self.assertEqual(disagreed[:10], [], f"bag rule disagrees on {len(disagreed)} of {len(checked)} items")


if __name__ == "__main__":
    unittest.main(verbosity=2)

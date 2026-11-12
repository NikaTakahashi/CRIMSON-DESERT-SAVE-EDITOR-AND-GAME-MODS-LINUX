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
from dmm_parser.tools import refresh_item_db  # noqa: E402

GAME_DIR = os.environ.get("CD_GAME_DIR", r"F:\CDump")
GROUP = "0008"
ITEM_DIR = "gamedata/binarystaticinfo__/bin"


def have_game() -> bool:
    return os.path.isdir(os.path.join(GAME_DIR, GROUP))


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

    def test_arrow_row_decodes_to_known_values(self):
        record, consumed = item_record.read_record(self.body, self.rows[0][1])
        self.assertEqual(record["key"], 2200)
        self.assertEqual(record["string_key"], "Pyeonjeon_Arrow")
        self.assertEqual(record["max_stack_count"], 100)
        self.assertEqual(consumed - self.rows[0][1], self.rows[1][1] - self.rows[0][1])


class DisplayNameTest(unittest.TestCase):

    def test_localized_default_is_used_when_present(self):
        record = {"item_name": {"category": 7, "index": 123, "default": "Stub Arrow"},
                  "string_key": "Pyeonjeon_Arrow"}
        self.assertEqual(refresh_item_db.display_name(record), "Stub Arrow")

    def test_numeric_default_falls_back_to_internal_name(self):
        record = {"item_name": {"category": 7, "index": 123, "default": "123"},
                  "string_key": "Small_Fire_Bomb"}
        self.assertEqual(refresh_item_db.display_name(record), "Small_Fire_Bomb")


if __name__ == "__main__":
    unittest.main(verbosity=2)

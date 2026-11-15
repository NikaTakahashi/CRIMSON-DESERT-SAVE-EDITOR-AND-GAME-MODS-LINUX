# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""Merge rules for the language name packs. The GUI reads `items` by decimal item
key, so the merge must keep that key shape, sort numerically, fill the gaps the game
tables cover, and never drop or overwrite what the pack already had.

Run:
    python -m dmm_parser.tools._test_lang_pack
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _PYTHON_ROOT not in sys.path:
    sys.path.insert(0, _PYTHON_ROOT)

from dmm_parser.tools import build_lang_pack  # noqa: E402


class MergeItemsTest(unittest.TestCase):
    def test_pack_entries_survive_and_gaps_are_filled(self):
        merged, added, differs = build_lang_pack.merge_items(
            {'7': 'Curated name', '9': 'Not in the tables'},
            {5: 'New entry', 7: 'Game table name'},
        )
        self.assertEqual(merged, {
            '5': 'New entry',
            '7': 'Curated name',
            '9': 'Not in the tables',
        })
        self.assertEqual((added, differs), (1, 1))

    def test_keys_sort_numerically_not_lexically(self):
        merged, _, _ = build_lang_pack.merge_items({'10': 'a', '2': 'b'}, {})
        self.assertEqual(list(merged), ['2', '10'])


if __name__ == '__main__':
    unittest.main()

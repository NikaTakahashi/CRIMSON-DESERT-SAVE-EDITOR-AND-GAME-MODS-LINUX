# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

r"""Regression tests for the pure-Python pack crypto (Jenkins + ChaCha20).

Two things broke while porting `src/crypto/{checksum,chacha20}.rs`: the ChaCha20
sigma constants, and the Jenkins finalize rotation order. Both change every
output byte, so they are pinned here against a reference vector and against the
values the game actually uses. The end-to-end case runs the crypto path through
`pack_index.extract` and needs a game install (same convention as
`_test_readers.py`).

Run:
    python -m dmm_parser.tools._test_pack_crypto
    CD_GAME_DIR="/path/to/Crimson Desert" python -m dmm_parser.tools._test_pack_crypto
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _PYTHON_ROOT not in sys.path:
    sys.path.insert(0, _PYTHON_ROOT)

from dmm_parser import pack_crypto  # noqa: E402
from dmm_parser import pack_index  # noqa: E402

GAME_DIR = os.environ.get("CD_GAME_DIR", r"F:\CDump")
GROUP = "0020"
STRING_DIR = "gamedata/stringtable/binary__/eng"
PALOC = "item.paloc"
ENCRYPT_INFO = bytes.fromhex("020e61")


def have_game() -> bool:
    return os.path.isdir(os.path.join(GAME_DIR, GROUP))


class ChecksumTest(unittest.TestCase):
    def test_empty_input_returns_the_seed(self):
        self.assertEqual(pack_crypto.calculate_checksum(b""), 0xDEBA1DCD)

    def test_entry_filename_derives_the_game_nonce(self):
        # Value the game uses for group 0020 / item.paloc; only this counter
        # makes the stored bytes decode to the string-table magic.
        self.assertEqual(pack_crypto.calculate_checksum(b"item.paloc"), 0xF55A43FF)
        nonce = pack_crypto.entry_nonce16(PALOC)
        self.assertEqual(nonce, bytes.fromhex("ff435af5") * 4)


class ChaCha20Test(unittest.TestCase):
    def test_block_matches_the_reference_vector(self):
        block = pack_crypto._chacha20_block([0] * 8, 0, [0] * 3)
        self.assertEqual(
            block[:16], bytes.fromhex("76b8e0ada0f13d90405d6ae55386bd28")
        )

    def test_decrypt_is_symmetric(self):
        data = b"localization string table payload"
        enc = pack_crypto.decrypt_entry(data, ENCRYPT_INFO, PALOC)
        self.assertNotEqual(enc, data)
        self.assertEqual(pack_crypto.decrypt_entry(enc, ENCRYPT_INFO, PALOC), data)


@unittest.skipUnless(have_game(), f"no game install at {GAME_DIR}")
class ExtractEncryptedEntryTest(unittest.TestCase):
    def test_crypto_entry_decodes_to_the_string_table(self):
        out = pack_index.extract(GAME_DIR, GROUP, STRING_DIR, PALOC)
        self.assertTrue(out.startswith(b"paloc\x00"), "ChaCha20 path regressed")
        # item key 1, name category 0x70: key text + u32 value length + value.
        self.assertIn(b"4294967408\x06\x00\x00\x00Copper", out)


if __name__ == "__main__":
    unittest.main()

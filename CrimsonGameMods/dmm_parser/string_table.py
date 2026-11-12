# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser

"""Read path for the game's `.paloc` string tables (the localized display names).

Layout measured on a 2.04.08 install:

    0-4    'paloc'
    5-8    u32, zero on every table checked
    9-12   u32 length of the entry stream (blob length - 16 - the zero block)
    13-16  u32 size the entry stream expands to; bigger than the stored region
           on the big tables (item.paloc: 589,043 stored / 1,620,928 output)
    16-511 zero block
    512    entry stream: [u8 control][u8 size][u16 table id = 1][u8 control]
                            [u8][u32 key length][key][u32 value length][value]

Only entries stored as plain literals can be read here, because the rest of the
stream is prefix-coded against a string dictionary that the game builds at pack
time and does not ship inside the table. On `item.paloc` that is 6 entries
(Copper, Camp Funds, Stub Arrow, Small Bag, Bird Soup, Wells Military Champron),
cross-checked against an independent dump of the same table. The native extension
cannot read these tables at all on current data: `parse_paloc_bytes` fails on the
control bytes.

So `read_table` returns a partial map; callers must keep the internal name as the
fallback and must not assume a key is present.

Usage:
    from dmm_parser import string_table
    names = string_table.read_table(game_dir, '0020', 'item.paloc')
    names[(1 << 32) | 0x70]      # 'Copper'   (item names: (key << 32) | 0x70)
    names[(2200 << 32) | 0x70]   # 'Stub Arrow'
"""

from __future__ import annotations

from . import pack_index

MAGIC = b'paloc\x00'
STRING_DIR = 'gamedata/stringtable/binary__/eng'
STREAM_OFFSET = 512
_PLAIN_KEYS = 64
_PLAIN_VALUES = 4096
_PRINTABLE = frozenset(range(0x20, 0x7F)) | {0x09, 0x0A}


def parse_header(blob: bytes) -> dict:
    """Stored entry-stream length and the size it expands to."""
    if not blob.startswith(MAGIC):
        raise ValueError(f"not a paloc table: {blob[:6]!r}")
    return {
        'stream_size': int.from_bytes(blob[9:13], 'little'),
        'output_size': int.from_bytes(blob[13:17], 'little'),
    }


def _printable(data: bytes) -> bool:
    return bool(data) and all(c in _PRINTABLE for c in data)


def iter_plain_entries(blob: bytes):
    """Yield `{'key': int, 'value': str}` for entries kept as plain literals.

    Keys are the decimal localization ids (`(item_key << 32) | 0x70` for item
    names, `| 0x71` for descriptions), so the scan requires an all-digit key.
    """
    pos = STREAM_OFFSET
    end = len(blob)
    while pos + 8 <= end:
        key_len = int.from_bytes(blob[pos:pos + 4], 'little')
        if 1 <= key_len <= _PLAIN_KEYS:
            key = blob[pos + 4:pos + 4 + key_len]
            if key.isdigit() and _printable(key):
                after = pos + 4 + key_len
                value_len = int.from_bytes(blob[after:after + 4], 'little')
                if 1 <= value_len <= _PLAIN_VALUES:
                    value = blob[after + 4:after + 4 + value_len]
                    if _printable(value):
                        yield {'key': int(key), 'value': value.decode('utf-8')}
                        pos = after + 4 + value_len
                        continue
        pos += 1


def read_table(game_dir: str, group: str, table: str, index: dict | None = None) -> dict[int, str]:
    """Decrypt a string table in `group` and return the entries that are readable."""
    index = index or pack_index.read_index(game_dir, group)
    blob = pack_index.extract(game_dir, group, STRING_DIR, table, index)
    return {entry['key']: entry['value'] for entry in iter_plain_entries(blob)}

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
    512    entry stream, an LZ4 block that expands to the size in the header;
           decoded, each record is [u32 control = 7][u32 zero][u32 key length]
                                    [key][u32 value length][value]

`iter_entries` decodes that block, so `read_table` returns the whole table -
14082 records on `item.paloc`, 2686 on `item.dlc_01.paloc`, against the 6 plain
literals that were readable in the stored bytes alone. When the block cannot be
decoded the scan falls back to those plain literals, so a caller that has no `lz4`
still gets what it used to. Keys are the decimal localization ids.

Callers must still keep a fallback for keys the table does not carry: on
`item.paloc` 72 of the 7068 item records have no entry, and DLC item tables only
hold DLC items, so `read_names` has to read every install root's own table.

Usage:
    from dmm_parser import string_table
    names = string_table.read_table(game_dir, '0020', 'item.paloc')
    names[(1 << 32) | 0x70]      # 'Copper'   (item names: (key << 32) | 0x70)
    names[(2200 << 32) | 0x70]   # 'Stub Arrow'
"""

from __future__ import annotations

import lz4.block

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


def iter_entries(blob: bytes):
    """Yield `{'key': int, 'value': str}` for every entry in the table.

    Decodes the LZ4 block that holds the entry stream; on decode failure, or when
    the header says the stream is stored uncompressed, the plain-literal scan of
    the stored bytes is used instead.
    """
    header = parse_header(blob)
    stream = blob[STREAM_OFFSET:STREAM_OFFSET + header['stream_size']]
    if header['output_size'] == header['stream_size']:
        out = stream
    else:
        try:
            out = lz4.block.decompress(stream, uncompressed_size=header['output_size'])
        except Exception:
            yield from iter_plain_entries(blob)
            return
    pos = 0
    while pos + 16 <= len(out):
        key_len = int.from_bytes(out[pos + 8:pos + 12], 'little')
        if not 1 <= key_len <= _PLAIN_KEYS:
            break
        key = out[pos + 12:pos + 12 + key_len]
        if not key.isdigit():
            break
        after = pos + 12 + key_len
        value_len = int.from_bytes(out[after:after + 4], 'little')
        if not 1 <= value_len <= _PLAIN_VALUES:
            break
        yield {'key': int(key),
               'value': out[after + 4:after + 4 + value_len].decode('utf-8', 'replace')}
        pos = after + 4 + value_len


def read_table(game_dir: str, group: str, table: str, index: dict | None = None) -> dict[int, str]:
    """Decrypt a string table in `group` and return its entries."""
    index = index or pack_index.read_index(game_dir, group)
    blob = pack_index.extract(game_dir, group, STRING_DIR, table, index)
    return {entry['key']: entry['value'] for entry in iter_entries(blob)}

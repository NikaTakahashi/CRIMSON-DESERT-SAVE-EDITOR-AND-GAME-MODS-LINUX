# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser

"""Game pack index (`.pamt`) reader for the 2.04 name encoding.

The packaged native extension resolves index names through the pre-2.04 trie
(a fixed 4-byte parent pointer per name node). Game build 2.04.00 encodes the
same trie as LEB128 delta chains, so `crimson_rs.extract_file()` fails on
current installs with `trie offset ... out of bounds`. This module reads the
index without the native extension.

The LZ4/zlib codecs and ChaCha20 (crypto method 3) are implemented here; ICE and
AES entries are still left to the native `Crypto` layer and raise.
"""

from __future__ import annotations

import lz4.block
import pathlib
import struct
import zlib

from . import pack_crypto

COMP_RAW = 0
COMP_LZ4_BLOCK = 2
COMP_ZLIB = 3


def read_leb(buf: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def resolve_name(buf: bytes, offset: int, delta: bool) -> str:
    """Resolve one trie node to its name, chaining parents iteratively."""
    if offset < 0 or offset >= len(buf):
        return ""
    chain = []
    node = offset
    while True:
        if delta:
            parent_delta, length_at = read_leb(buf, node)
            parent = -1 if parent_delta == 0 else node - parent_delta
        else:
            parent = struct.unpack_from('<i', buf, node)[0]
            length_at = node + 4
        chain.append(buf[length_at + 1:length_at + 1 + buf[length_at]])
        if parent < 0:
            break
        node = parent
    return b''.join(reversed(chain)).decode('utf-8', 'replace')


def parse_pamt(data: bytes, delta_names: bool | None = None) -> dict:
    checksum, count, _ = struct.unpack_from('<IHH', data, 0)
    # PackMetaHeader trailing bytes: u8 unknown, then the 3-byte encrypt_info
    # that keys every ChaCha20 entry in the group.
    encrypt_info = data[9:12]
    pos = 12
    chunks = []
    for _ in range(count):
        chunks.append(struct.unpack_from('<III', data, pos))
        pos += 12
    # The ffffffff header sentinel used to mark the delta trie; current packs
    # store a real checksum there, so the encoding is taken as the default.
    delta = True if delta_names is None else delta_names

    dir_len = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    dir_buf = data[pos:pos + dir_len]
    pos += dir_len
    file_len = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    file_buf = data[pos:pos + file_len]
    pos += file_len

    dir_count = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    dirs = []
    for _ in range(dir_count):
        dirs.append(struct.unpack_from('<IIII', data, pos))
        pos += 16

    file_count = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    files = []
    for _ in range(file_count):
        files.append(struct.unpack_from('<IIIIHBB', data, pos))
        pos += 20

    exts = []
    if pos < len(data):
        ext_len = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        exts = data[pos:pos + ext_len].split(b'\0')

    return {
        'checksum': checksum,
        'encrypt_info': encrypt_info,
        'chunks': chunks,
        'delta': delta,
        'dir_buf': dir_buf,
        'file_buf': file_buf,
        'dirs': dirs,
        'files': files,
        'ext': exts,
    }


def read_index(game_dir: str, group: str) -> dict:
    """Read a pack group index, preferring the name-index file when present.

    Entry fields: (name node, chunk offset, compressed size, uncompressed size,
    chunk id, flags, ext index); the low nibble of flags is the codec.
    """
    group_dir = pathlib.Path(game_dir) / group
    path = group_dir / '0.pamt.idx'
    if not path.exists():
        path = group_dir / '0.pamt'
    return parse_pamt(path.read_bytes())


def entry_name(index: dict, entry: tuple) -> str:
    name = resolve_name(index['file_buf'], entry[0], index['delta'])
    ext = index['ext'][entry[6]] if entry[6] < len(index['ext']) else b'?'
    return name + ext.decode('utf-8', 'replace')


def entry_path(index: dict, position: int, entry: tuple) -> tuple[str, str]:
    """(dir, name) for an entry; dirs own a contiguous run of the file list."""
    for _dir_hash, dir_node, first, count in index['dirs']:
        if first <= position < first + count:
            return resolve_name(index['dir_buf'], dir_node, index['delta']), entry_name(index, entry)
    return '', entry_name(index, entry)


def read_chunk(game_dir: str, group: str, chunk_id: int, offset: int, size: int) -> bytes:
    blob = pathlib.Path(game_dir) / group / f'{chunk_id}.paz'
    return blob.read_bytes()[offset:offset + size]


def _decompress(raw: bytes, compression: int, uncompressed_size: int) -> bytes:
    if compression == COMP_RAW:
        return raw
    if compression == COMP_LZ4_BLOCK:
        return lz4.block.decompress(raw, uncompressed_size=uncompressed_size)
    if compression == COMP_ZLIB:
        return zlib.decompress(raw)
    raise ValueError(f"unsupported compression method {compression}")


def decompress_chunk(game_dir: str, group: str, chunk_id: int, offset: int, size: int,
                     compression: int, uncompressed_size: int) -> bytes:
    return _decompress(read_chunk(game_dir, group, chunk_id, offset, size),
                       compression, uncompressed_size)


def find_entry(index: dict, dir_path: str, file_name: str) -> tuple:
    target = (dir_path or '').replace('\\', '/').strip('/')
    for position, entry in enumerate(index['files']):
        entry_dir, entry_file = entry_path(index, position, entry)
        if entry_dir == target and entry_file == file_name:
            return entry
    raise KeyError(f"{dir_path}/{file_name} not found in pack group")


def extract(game_dir: str, group: str, dir_path: str, file_name: str,
           index: dict | None = None) -> bytes:
    index = index or read_index(game_dir, group)
    entry = find_entry(index, dir_path, file_name)
    _node, chunk_offset, chunk_size, uncompressed, chunk_id, flags, _ext = entry
    crypto = flags >> 4
    raw = read_chunk(game_dir, group, chunk_id, chunk_offset, chunk_size)
    if crypto == pack_crypto.CRYPTO_CHACHA20:
        # Entries are compressed before being encrypted, so decrypt first.
        raw = pack_crypto.decrypt_entry(raw, index['encrypt_info'], entry_name(index, entry))
    elif crypto:
        raise ValueError(f"{dir_path}/{file_name} needs crypto method {crypto}; use the native reader")
    return _decompress(raw, flags & 0xF, uncompressed)

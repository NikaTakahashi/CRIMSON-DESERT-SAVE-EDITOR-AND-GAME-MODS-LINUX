# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser

"""Pack entry decryption for crypto method 3 (ChaCha20).

Port of upstream `src/crypto/checksum.rs` and `src/crypto/chacha20.rs`. The
per-entry nonce is the Jenkins hashlittle2 of the entry's own filename (the last
path segment, not the full path) repeated four times; the key is the fixed pack
base key XOR that nonce XOR the XOR of the three PAMT `encrypt_info` bytes.

Entries are compressed before encryption, so callers decrypt the stored bytes
first and only then run the codec.
"""

from __future__ import annotations

import struct

MASK = 0xFFFFFFFF

CRYPTO_NONE = 0
CRYPTO_ICE = 1
CRYPTO_AES = 2
CRYPTO_CHACHA20 = 3

PACK_ENTRY_BASE_KEY = bytes((
    0x0E, 0x0F, 0x0C, 0x0D, 0x04, 0x05, 0x06, 0x07,
    0x02, 0x03, 0x00, 0x01, 0x08, 0x09, 0x0A, 0x0B,
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
    0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,
))


def _rot(x: int, k: int) -> int:
    return ((x << k) | (x >> (32 - k))) & MASK


def _sub(x: int, y: int) -> int:
    return (x - y) & MASK


def _mix(a: int, b: int, c: int) -> tuple[int, int, int]:
    a = _sub(a, c) ^ _rot(c, 4)
    c = (c + b) & MASK
    b = _sub(b, a) ^ _rot(a, 6)
    a = (a + c) & MASK
    c = _sub(c, b) ^ _rot(b, 8)
    b = (b + a) & MASK
    a = _sub(a, c) ^ _rot(c, 16)
    c = (c + b) & MASK
    b = _sub(b, a) ^ _rot(a, 19)
    a = (a + c) & MASK
    c = _sub(c, b) ^ _rot(b, 4)
    b = (b + a) & MASK
    return a, b, c


def _finalize(a: int, b: int, c: int) -> tuple[int, int, int]:
    c = _sub(c ^ b, _rot(b, 14))
    a = _sub(a ^ c, _rot(c, 11))
    b = _sub(b ^ a, _rot(a, 25))
    c = _sub(c ^ b, _rot(b, 16))
    a = _sub(a ^ c, _rot(c, 4))
    b = _sub(b ^ a, _rot(a, 14))
    c = _sub(c ^ b, _rot(b, 24))
    return a, b, c


def calculate_checksum(data: bytes) -> int:
    """Jenkins hashlittle2 seeded with `len(data) + 0xDEBA1DCD`."""
    init = (len(data) + 0xDEBA1DCD) & MASK
    a = b = c = init
    pos, remaining = 0, len(data)
    while remaining > 12:
        w0, w1, w2 = struct.unpack_from('<III', data, pos)
        a = (a + w0) & MASK
        b = (b + w1) & MASK
        c = (c + w2) & MASK
        a, b, c = _mix(a, b, c)
        pos += 12
        remaining -= 12
    if remaining == 0:
        return c
    tail = data[pos:pos + remaining].ljust(12, b'\0')
    w0, w1, w2 = struct.unpack('<III', tail)
    a = (a + w0) & MASK
    b = (b + w1) & MASK
    c = (c + w2) & MASK
    return _finalize(a, b, c)[2]


def _chacha20_block(key_words: list[int], counter: int, nonce_words: list[int]) -> bytes:
    state = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574] + key_words + [counter] + nonce_words
    work = list(state)

    def quarter(a: int, b: int, c: int, d: int) -> None:
        work[a] = (work[a] + work[b]) & MASK
        work[d] = _rot(work[d] ^ work[a], 16)
        work[c] = (work[c] + work[d]) & MASK
        work[b] = _rot(work[b] ^ work[c], 12)
        work[a] = (work[a] + work[b]) & MASK
        work[d] = _rot(work[d] ^ work[a], 8)
        work[c] = (work[c] + work[d]) & MASK
        work[b] = _rot(work[b] ^ work[c], 7)

    for _ in range(10):
        quarter(0, 4, 8, 12)
        quarter(1, 5, 9, 13)
        quarter(2, 6, 10, 14)
        quarter(3, 7, 11, 15)
        quarter(0, 5, 10, 15)
        quarter(1, 6, 11, 12)
        quarter(2, 7, 8, 13)
        quarter(3, 4, 9, 14)

    return b''.join(struct.pack('<I', (state[i] + work[i]) & MASK) for i in range(16))


def _keystream(data: bytes, key: bytes, nonce16: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
        enc = Cipher(algorithms.ChaCha20(key, nonce16), mode=None).encryptor()
        return enc.update(data) + enc.finalize()
    except Exception:
        pass

    key_words = [struct.unpack_from('<I', key, i * 4)[0] for i in range(8)]
    nonce_words = [struct.unpack_from('<I', nonce16, 4 + i * 4)[0] for i in range(3)]
    counter = struct.unpack_from('<I', nonce16, 0)[0]
    out = bytearray(len(data))
    pos = 0
    while pos < len(data):
        block = _chacha20_block(key_words, counter, nonce_words)
        end = min(pos + 64, len(data))
        chunk = data[pos:end]
        out[pos:end] = bytes(x ^ y for x, y in zip(chunk, block[:len(chunk)]))
        pos = end
        counter = (counter + 1) & MASK
    return bytes(out)


def entry_nonce16(file_name: str) -> bytes:
    """Nonce for one entry: its filename checksum, repeated four times."""
    counter = calculate_checksum(file_name.encode('utf-8'))
    return counter.to_bytes(4, 'little') * 4


def decrypt_entry(data: bytes, encrypt_info: bytes, file_name: str) -> bytes:
    """Decrypt one pack entry. Symmetric, so it also encrypts."""
    nonce16 = entry_nonce16(file_name)
    k = encrypt_info[0] ^ encrypt_info[1] ^ encrypt_info[2]
    key = bytes((PACK_ENTRY_BASE_KEY[i] ^ nonce16[i % 16] ^ k) for i in range(32))
    return _keystream(data, key, nonce16)

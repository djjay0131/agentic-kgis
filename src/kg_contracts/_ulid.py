"""Minimal ULID generator (stdlib only, no third-party dependency).

Layout matches the standard ULID spec: a 48-bit millisecond timestamp
followed by 80 bits of randomness, both encoded in Crockford's base32
(which excludes the visually ambiguous I, L, O, U). The result is a
26-character string that sorts lexicographically in creation order.

Internal helper used for identity IDs, trace IDs (see security.py),
and later ledger IDs.
"""

import os
import time

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_base32(data: bytes, length: int) -> str:
    """Encode `data` as `length` Crockford-base32 characters, MSB first."""
    value = int.from_bytes(data, byteorder="big")
    chars = ["0"] * length
    for i in range(length - 1, -1, -1):
        chars[i] = _CROCKFORD_ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(chars)


def new_ulid() -> str:
    """Generate a 26-char Crockford-base32 ULID.

    First 10 chars: 48-bit millisecond timestamp (sortable).
    Last 16 chars: 80 random bits (10 bytes from os.urandom).
    """
    timestamp_ms = int(time.time() * 1000)
    timestamp_bytes = timestamp_ms.to_bytes(6, byteorder="big")
    random_bytes = os.urandom(10)
    return _encode_base32(timestamp_bytes, 10) + _encode_base32(random_bytes, 16)

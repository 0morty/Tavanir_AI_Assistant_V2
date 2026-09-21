from __future__ import annotations

import hashlib


def suggestion_id_to_lock_key(suggestion_id: str) -> int:
    """
    Deterministically hash an arbitrary string suggestion ID into a 64-bit signed integer.

    This maps the string domain identifier to PostgreSQL's native `bigint` advisory lock key
    space [-2^63, 2^63 - 1], effectively eliminating 32-bit Birthday Paradox hash collisions.
    """
    digest = hashlib.sha256(suggestion_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


__all__ = ["suggestion_id_to_lock_key"]

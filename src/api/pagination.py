"""Keyset pagination: ``?limit=`` (1–100) and an opaque ``?cursor=`` → ``{"items", "next_cursor"}``."""

from __future__ import annotations

import base64
import binascii
import json

from fastapi import Query

from src.api.errors import ApiError

MAX_CURSOR_LEN = 200


def encode_cursor(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')


def decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    if len(cursor) > MAX_CURSOR_LEN:
        raise ApiError(422, 'invalid_cursor', 'Invalid cursor.')
    try:
        padded = cursor + '=' * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise ApiError(422, 'invalid_cursor', 'Invalid cursor.') from None
    if not isinstance(value, dict):
        raise ApiError(422, 'invalid_cursor', 'Invalid cursor.')
    return value


def limit_param(limit: int = Query(25, ge=1, le=100)) -> int:
    return limit


def cursor_id(cursor: dict | None, *, upper: int = 2**31) -> int | None:
    """The ``id`` from a decoded keyset cursor, bounded to the column range (422 otherwise)."""
    if not cursor:
        return None
    value = cursor.get('id')
    if not isinstance(value, int) or isinstance(value, bool) or not 0 < value < upper:
        raise ApiError(422, 'invalid_cursor', 'Invalid cursor.')
    return value

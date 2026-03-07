from __future__ import annotations

import base64
from typing import Any

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def parse_limit(raw: Any) -> int:
    try:
        value = int(raw)
    except Exception:
        return DEFAULT_LIMIT

    if value <= 0:
        return DEFAULT_LIMIT

    return min(value, MAX_LIMIT)


def decode_cursor(raw: Any) -> int:
    if not isinstance(raw, str) or raw == "":
        return 0

    try:
        padding = "=" * ((4 - len(raw) % 4) % 4)
        decoded = base64.urlsafe_b64decode(f"{raw}{padding}".encode("utf-8")).decode("utf-8")
        value = int(decoded)
        if value < 0:
            return 0
        return value
    except Exception:
        return 0


def encode_cursor(index: int | None) -> str | None:
    if index is None or index < 0:
        return None

    return base64.urlsafe_b64encode(str(index).encode("utf-8")).decode("utf-8").rstrip("=")


def paginate(items: list[Any], cursor: Any, limit_raw: Any) -> dict[str, Any]:
    start = decode_cursor(cursor)
    limit = parse_limit(limit_raw)
    page_items = items[start : start + limit]
    next_index = start + len(page_items)
    has_more = next_index < len(items)

    return {
        "items": page_items,
        "nextCursor": encode_cursor(next_index) if has_more else None,
        "limit": limit,
    }

"""Small display helpers that conservatively budget Discord text in UTF-16 units."""


def text_units(text: str) -> int:
    return len(text.encode('utf-16-le', errors='replace')) // 2


def clip_text(value, limit: int) -> str:
    if limit <= 0:
        return ''
    text = '' if value is None else str(value)
    encoded = text.encode('utf-16-le', errors='replace')
    if len(encoded) <= limit * 2:
        return encoded.decode('utf-16-le')
    return encoded[: max(0, limit - 1) * 2].decode('utf-16-le', errors='ignore') + '…'


def bounded_items(items: list[str], limit: int) -> str:
    """Keep items intact and make omitted counts explicit (e.g. role mentions)."""
    if not items:
        return clip_text('None', limit)
    kept: list[str] = []
    for item in items:
        remaining = len(items) - len(kept) - 1
        suffix = f' … (+{remaining} more)' if remaining else ''
        if text_units(', '.join([*kept, item]) + suffix) > limit:
            break
        kept.append(item)
    remaining = len(items) - len(kept)
    return clip_text(', '.join(kept) + (f' … (+{remaining} more)' if remaining else ''), limit)

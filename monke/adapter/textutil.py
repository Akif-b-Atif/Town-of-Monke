"""Small pure helpers shared by the Discord adapter (XC-4, XC-5)."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterator, Sequence, TypeVar

from ..names import fmt_player, fmt_players  # noqa: F401  (NAM-2, re-exported for the adapter)

T = TypeVar("T")

MAX_CONTENT = 2000
MAX_EMBED_DESCRIPTION = 4096
MAX_EMBEDS_PER_MESSAGE = 10


def rel(epoch: float) -> str:
    """Discord relative timestamp, e.g. 'in 5 minutes'."""
    return f"<t:{int(epoch)}:R>"


def clock(epoch: float) -> str:
    """Discord short-time timestamp, shown in each reader's own timezone."""
    return f"<t:{int(epoch)}:t>"


def split_text(text: str, limit: int = MAX_CONTENT) -> list[str]:
    """Split text into pieces of at most `limit` characters, breaking at line
    boundaries. A single line longer than `limit` is cut hard."""
    if not text:
        return []
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                chunks.append("\n".join(cur))
                cur, cur_len = [], 0
            chunks.append(line[:limit])
            line = line[limit:]
        add = len(line) + (1 if cur else 0)
        if cur and cur_len + add > limit:
            chunks.append("\n".join(cur))
            cur, cur_len = [line], len(line)
        else:
            cur.append(line)
            cur_len += add
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def chunked(items: Sequence[T], size: int = MAX_EMBEDS_PER_MESSAGE) -> Iterator[Sequence[T]]:
    """Yield consecutive slices of at most `size` items."""
    for i in range(0, len(items), size):
        yield items[i : i + size]

NAME_MAX = 20
_MD_CHARS = re.compile(r"([\\*_~|`>])")


def sanitize_name(raw: str, fallback: str = "Player") -> str:
    """NAM-1: strip control, zero-width and bidi characters, collapse whitespace, cut to 20
    characters with an ellipsis, then escape markdown and mentions. Empty becomes `fallback`."""
    s = "".join(" " if ch.isspace() else ch for ch in (raw or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co", "Cn"))
    s = " ".join(s.split())
    if len(s) > NAME_MAX:
        s = s[: NAME_MAX - 1].rstrip() + "…"
    if not s:
        return fallback
    s = _MD_CHARS.sub(r"\\\1", s)
    return s.replace("@", "@\u200b")

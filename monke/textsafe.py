"""Sanitising text a player writes (CARD-3): mentions neutralised, invite links removed, at most 10 new lines.
Markdown is allowed. Pure."""
from __future__ import annotations

import re

ZWSP = "\u200b"
_INVITE = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite|dsc\.gg)/\S+", re.I)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_NEWLINES = 10


def sanitize_text(text: str) -> str:
    text = _CONTROL.sub("", (text or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = _INVITE.sub("", text)
    text = re.sub(r"<(@[!&]?|#)(?=\d)", lambda m: "<" + ZWSP + m.group(1), text)  # user, role and channel mentions
    text = re.sub(r"@(everyone|here)", "@" + ZWSP + r"\1", text, flags=re.I)
    parts = text.split("\n")
    if len(parts) > MAX_NEWLINES + 1:  # at most 10 new lines: the rest is joined onto the last line
        text = "\n".join(parts[:MAX_NEWLINES]) + "\n" + " ".join(p for p in parts[MAX_NEWLINES:] if p.strip())
    return text.strip()

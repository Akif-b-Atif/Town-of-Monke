"""Parse `monke start @p1 ... @pN` + role tokens (one per line) + optional key=value settings."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..errors import Rejected

_MENTION = re.compile(r"<@!?(\d+)>")
_OPTION = re.compile(r"\b(\w+)=(\S+)")


@dataclass
class StartRequest:
    user_ids: list = field(default_factory=list)
    tokens: list = field(default_factory=list)
    options: dict = field(default_factory=dict)


def parse_start(content: str, bot_ids: set = frozenset()) -> StartRequest:
    body = re.sub(r"^\s*\S*monke\S*\s+start\b", "", content, count=1, flags=re.I)
    users: list = []
    for m in _MENTION.finditer(body):
        uid = int(m.group(1))
        if uid in bot_ids:
            raise Rejected("Bots cannot play.")
        if uid not in users:
            users.append(uid)
    options = dict(_OPTION.findall(body))
    tokens: list = []
    for line in body.splitlines():
        line = _OPTION.sub("", _MENTION.sub("", line))
        for chunk in line.split(","):
            chunk = chunk.strip()
            if chunk:
                tokens.append(chunk)
    if not users:
        raise Rejected("Mention the players: `monke start @p1 @p2 ...` then one role token per line.")
    return StartRequest(users, tokens, options)

"""Role-list tokens: groups and random tokens."""
from __future__ import annotations

from .registry import all_defs

TOWN_GROUPS = ("TK", "TI", "TP", "TS")
MAFIA_GROUPS = ("MK", "MS")
NEUTRAL_GROUPS = ("NK", "NE")
GROUP_TOKENS = TOWN_GROUPS + MAFIA_GROUPS + NEUTRAL_GROUPS
RANDOM_TOKENS = ("RT", "RM", "RN", "Any")


def group_pool(group: str) -> list:
    return [d for d in all_defs() if d.group == group]


def random_pool(token: str) -> list:
    """RT never Jailor, RM never Godfather, RN any Neutral, Any any role except Jailor and Godfather (LOB-2)."""
    if token == "Any":
        return [d for d in all_defs() if d.id not in ("jailor", "godfather")]
    groups = {"RT": TOWN_GROUPS, "RM": MAFIA_GROUPS, "RN": NEUTRAL_GROUPS}[token]
    return [d for d in all_defs() if d.group in groups]

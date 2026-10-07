"""Role-list tokens: groups and random tokens."""
from __future__ import annotations

from .registry import all_defs

TOWN_GROUPS = ("TK", "TI", "TP", "TS")
MAFIA_GROUPS = ("MK", "MS")
NEUTRAL_GROUPS = ("NK", "NE")
GROUP_TOKENS = TOWN_GROUPS + MAFIA_GROUPS + NEUTRAL_GROUPS
RANDOM_TOKENS = ("RT", "RM")


def group_pool(group: str) -> list:
    return [d for d in all_defs() if d.group == group]


def random_pool(token: str) -> list:
    groups = TOWN_GROUPS if token == "RT" else MAFIA_GROUPS  # RT never Jailor, RM never Godfather
    return [d for d in all_defs() if d.group in groups]

"""Role-list parsing, validation and generation (section 6.3)."""
from __future__ import annotations

import random
import re

from .. import constants as C
from ..errors import Rejected
from ..roles import all_defs, get_def
from ..roles.groups import GROUP_TOKENS, RANDOM_TOKENS, group_pool, random_pool
from ..roles.registry import has_role


def _key(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", s).lower()


def normalize_token(raw: str):
    """Canonical token: a role id (fixed), a group token (TK...) or RT/RM. None if unknown."""
    k = _key(raw)
    if not k:
        return None
    for g in GROUP_TOKENS + RANDOM_TOKENS:
        if k == g.lower():
            return g
    for d in all_defs():
        if k in (_key(d.id), _key(d.name)):
            return d.id
    return None


def validate_rolelist(tokens: list, n_players: int) -> list:
    if not C.MIN_PLAYERS <= n_players <= C.MAX_PLAYERS:
        raise Rejected("error.player_count", count=n_players)
    canon = []
    for raw in tokens:
        c = normalize_token(raw)
        if c is None:
            raise Rejected("error.rolelist_unknown_token", causes=raw)
        canon.append(c)
    if len(canon) != n_players:
        raise Rejected("error.rolelist_count", count=len(canon), needed=n_players)
    if canon.count("jailor") != 1:
        raise Rejected("error.rolelist_jailor")
    if canon.count("godfather") != 1:
        raise Rejected("error.rolelist_godfather")
    return canon


def generate_roles(canon: list, rng: random.Random) -> list:
    """Fixed tokens first, then group tokens, then random tokens. Unique roles leave the pool once drawn."""
    used: set = set()
    out: list = []
    fixed = [t for t in canon if has_role(t)]
    groups = [t for t in canon if t in GROUP_TOKENS]
    randoms = [t for t in canon if t in RANDOM_TOKENS]
    for t in fixed:
        d = get_def(t)
        if d.unique and t in used:
            raise Rejected("error.rolelist_unique", role=d.name)
        used.add(t)
        out.append(t)
    for t in groups:
        pool = sorted(d.id for d in group_pool(t) if not (d.unique and d.id in used))
        if not pool:
            raise Rejected("error.rolelist_pool", group=t)
        pick = rng.choice(pool)
        used.add(pick)
        out.append(pick)
    for t in randoms:
        pool = sorted(d.id for d in random_pool(t) if not (d.unique and d.id in used))
        if not pool:
            raise Rejected("error.rolelist_pool", group=t)
        pick = rng.choice(pool)
        used.add(pick)
        out.append(pick)
    return out


def assign(user_ids: list, roles: list, rng: random.Random) -> list:
    """Returns [(slot, user_id, role_id)]. Roles and slot numbers use two independent shuffles."""
    roles = list(roles)
    rng.shuffle(roles)
    slots = list(range(1, len(user_ids) + 1))
    rng.shuffle(slots)
    return [(slots[i], user_ids[i], roles[i]) for i in range(len(user_ids))]


# ---------------------------------------------------------------------------------------- defaults (LOB-1)
_TOWN_ORDER = ("Jailor", "TK", "TI", "TP", "TS", "RT")  # the classic list's reading order


def default_counts(n: int) -> tuple:
    """(town, mafia, neutral) for 5 to 20 players: mafia = max(1, round(n*4/15)), 1 neutral up to 11 players and 2
    from 12, and Town always stays strictly larger than Mafia plus Neutral."""
    mafia = max(1, int(n * 4 / 15 + 0.5))
    neutral = 1 if n <= 11 else 2
    town = n - mafia - neutral
    if town <= mafia + neutral:
        mafia -= 1
        town = n - mafia - neutral
    return town, mafia, neutral


def default_rolelist(n: int) -> list:
    """The default role list for n players (LOB-1). The classic 15-player list is
    Jailor TK TI TI TP TP TS RT RT / Godfather MK RM RM / NK NE. Small rosters repeat roles; that goes away in 2.0."""
    if not C.MIN_PLAYERS <= n <= C.MAX_PLAYERS:
        raise Rejected("error.player_count", count=n)
    town, mafia, neutral = default_counts(n)
    town_slots = ["Jailor", "TI", "TP", "TK", "TS", "TI", "TP"][:town]
    town_slots += ["RT"] * (town - len(town_slots))
    town_slots.sort(key=lambda t: _TOWN_ORDER.index(t))  # stable: groups together, in the classic order
    mafia_slots = (["Godfather", "MK", "RM", "RM", "RM"])[:mafia]
    neutral_slots = ["RN"] if neutral == 1 else ["NK", "NE"]
    return town_slots + mafia_slots + neutral_slots


def split_tokens(text: str) -> list:
    """Role list tokens separated by spaces, commas or new lines, case-insensitive (LOB-2). Multi-word role names
    such as 'Serial Killer' stay together; an unknown word is passed through so validation can name it."""
    out: list = []
    for chunk in re.split(r"[,\n;]+", text):
        words = chunk.split()
        i = 0
        while i < len(words):
            for span in (3, 2, 1):
                cand = " ".join(words[i:i + span])
                if span == 1 or normalize_token(cand) is not None:
                    out.append(cand)
                    i += span
                    break
    return out

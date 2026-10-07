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
        raise Rejected(f"A game needs {C.MIN_PLAYERS}-{C.MAX_PLAYERS} players (got {n_players}).")
    canon = []
    for raw in tokens:
        c = normalize_token(raw)
        if c is None:
            raise Rejected(f"Unknown role list token: {raw!r}.")
        canon.append(c)
    if len(canon) != n_players:
        raise Rejected(f"The role list has {len(canon)} entries but there are {n_players} players.")
    if canon.count("jailor") != 1:
        raise Rejected("The role list needs exactly one Jailor.")
    if canon.count("godfather") != 1:
        raise Rejected("The role list needs exactly one Godfather.")
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
            raise Rejected(f"{d.name} is unique but appears more than once in the role list.")
        used.add(t)
        out.append(t)
    for t in groups:
        pool = sorted(d.id for d in group_pool(t) if not (d.unique and d.id in used))
        if not pool:
            raise Rejected(f"The role list has too many {t} entries: every {t} role is already taken.")
        pick = rng.choice(pool)
        used.add(pick)
        out.append(pick)
    for t in randoms:
        pool = sorted(d.id for d in random_pool(t) if not (d.unique and d.id in used))
        if not pool:
            raise Rejected(f"No roles left for {t}.")
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

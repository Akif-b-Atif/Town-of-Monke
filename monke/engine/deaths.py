from __future__ import annotations

from .. import constants as C
from ..roles import get_def
from . import events as E


def kill(s, slot: int, causes: list, where: str = "day", note: str = "") -> E.Event:
    """Mark a player dead and return the PlayerDied event (the role is always revealed).
    `where` is 'dawn' for night deaths (the dawn report tells the town) or 'day' (announced at once)."""
    first = not any(not q.alive for q in s.players.values())
    p = s.players[slot]
    p.alive = False
    night = s.phase == C.NIGHT
    p.death = {
        "phase": s.phase,
        "day_or_night": f"N{s.night_number}" if night else f"D{s.day_number}",
        "causes": list(causes),
    }
    if s.settings.allow_wills and p.will:  # shown for every cause: lynching and execution included (CARD-3)
        p.death["will"] = p.will
    if note and s.settings.allow_deathnotes:  # only when the killer's attack succeeded (CARD-4)
        p.death["note"] = note
    d = get_def(p.role_id)
    return E.ev(E.T.PLAYER_DIED, slot=slot, user_id=p.user_id, role_id=d.id, role=d.name,
                causes=list(causes), where=where, first_death=first)

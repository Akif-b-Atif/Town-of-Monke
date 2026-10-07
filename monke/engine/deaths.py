from __future__ import annotations

from .. import constants as C
from ..roles import get_def
from . import events as E

CAUSE_TEXT = {
    C.MAFIA_KILL: "killed by the Mafia",
    C.SERIAL_KILLER: "killed by a Serial Killer",
    C.VETERAN: "shot by a Veteran",
    C.EXECUTED: "executed by the Jailor",
    C.HAUNTED: "haunted by the Jester",
    C.LYNCHED: "lynched by the town",
    C.ABANDONED: "left the game",
}


def kill(s, slot: int, causes: list) -> E.Event:
    """Mark a player dead and return the public PlayerDied event (victim's role is always revealed)."""
    p = s.players[slot]
    p.alive = False
    night = s.phase == C.NIGHT
    p.death = {
        "phase": s.phase,
        "day_or_night": f"N{s.night_number}" if night else f"D{s.day_number}",
        "causes": list(causes),
    }
    d = get_def(p.role_id)
    how = " and ".join(CAUSE_TEXT[c] for c in causes)
    text = f"Player {slot} was {how}. They were the {d.name}." if causes != [C.ABANDONED] else \
        f"Player {slot} {how}. They were the {d.name}."
    return E.ev(E.T.PLAYER_DIED, slot=slot, user_id=p.user_id, role_id=d.id, role=d.name,
                causes=list(causes), text=text)

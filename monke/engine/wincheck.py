from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .. import constants as C
from ..roles import get_def


@dataclass
class Outcome:
    faction: str  # TOWN | MAFIA | SERIAL_KILLER | DRAW | ABORTED
    winners: list = field(default_factory=list)
    reason: str = ""


def _winners(s, faction: str) -> list:
    return sorted(p.slot for p in s.players.values() if get_def(p.role_id).win_faction == faction)


def check(s) -> Optional[Outcome]:
    """Evaluated after every death event. The Jester's win is separate and never ends the game."""
    alive = [p for p in s.players.values() if p.alive]
    if not alive:
        return Outcome("DRAW", [], "nobody survived")
    town = [p for p in alive if get_def(p.role_id).alignment == C.TOWN]
    mafia = [p for p in alive if get_def(p.role_id).alignment == C.MAFIA]
    nk = [p for p in alive if get_def(p.role_id).group == "NK"]
    if town and not mafia and not nk:
        return Outcome("TOWN", _winners(s, "TOWN"), "all threats eliminated")
    if mafia and not town and not nk:
        return Outcome("MAFIA", _winners(s, "MAFIA"), "the Mafia took the town")
    if len(nk) == 1 and not town and not mafia:
        return Outcome("SERIAL_KILLER", _winners(s, "SERIAL_KILLER"), "the Serial Killer is the last killer standing")
    if not town and not mafia and not nk:
        return Outcome("DRAW", [], "only neutral roles remain")
    return None

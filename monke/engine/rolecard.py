from __future__ import annotations

from .. import constants as C
from ..roles import get_def


def role_card(s, p) -> dict:
    d = get_def(p.role_id)
    card = {
        "slot": p.slot, "role_id": d.id, "role": d.name, "alignment": d.alignment,
        "objective": d.objective, "summary": d.summary, "special": d.special, "tips": d.tips,
        "attack": C.ATTACK_NAMES[d.attack_level], "defense": C.DEFENSE_NAMES[d.defense_level],
        "teammates": [],
    }
    if d.alignment == C.MAFIA:
        card["teammates"] = [
            {"slot": q.slot, "role": get_def(q.role_id).name}
            for q in sorted(s.players.values(), key=lambda x: x.slot)
            if q.slot != p.slot and get_def(q.role_id).alignment == C.MAFIA
        ]
    return card

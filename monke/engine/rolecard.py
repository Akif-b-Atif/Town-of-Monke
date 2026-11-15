"""The structured role card: data only. The renderer turns it into an embed with flavour text (CARD-1)."""
from __future__ import annotations

from .. import constants as C
from ..roles import get_def, get_handler


def role_card(s, p) -> dict:
    d = get_def(p.role_id)
    h = get_handler(p.role_id)
    card = {
        "slot": p.slot, "role_id": d.id, "role": d.name, "alignment": d.alignment,
        "attack": d.attack_level, "defense": d.defense_level,
        "abilities": [{"id": a.id, "phase": a.phase, "uses_left": h.uses_left(s, p, a)} for a in d.abilities],
        "kills": d.attack_level > 0,
        "teammates": [],
    }
    if d.alignment == C.MAFIA:
        card["teammates"] = [
            {"slot": q.slot, "role_id": q.role_id, "role": get_def(q.role_id).name}
            for q in sorted(s.players.values(), key=lambda x: x.slot)
            if q.slot != p.slot and get_def(q.role_id).alignment == C.MAFIA
        ]
    return card

"""Wills, death notes and the journal (CARD-2 to CARD-4). Pure."""
from __future__ import annotations

from .. import constants as C
from ..errors import Rejected
from ..textsafe import sanitize_text
from . import events as E

# The ability a role's death note belongs to: roles whose ability kills (CARD-4). For the Mafia the note that is
# attached is the one of the player who PERFORMED the kill (the Mafioso when he carries out the Godfather's order).
NOTE_ABILITY = {"godfather": "order", "mafioso": "kill", "serial_killer": "kill", "veteran": "alert",
                "jailor": "execute", "jester": "haunt"}


def when_label(s) -> str:
    """'N2' during a night, otherwise 'D3': the key for a journal entry."""
    return f"N{s.night_number}" if s.phase == C.NIGHT else f"D{s.day_number}"


def private(s, events: list, slot: int, key: str, **vars) -> None:
    """A private message that is also written to the player's journal (CARD-2)."""
    events.append(E.ev(E.T.PRIVATE, E.to_slot(slot), text_key=key, vars=vars))
    s.players[slot].journal.append({"when": when_label(s), "text_key": key, "vars": vars})


def set_will(s, slot: int, text: str) -> None:
    p = s.players.get(slot)
    if p is None or not p.alive:
        raise Rejected("error.dead")
    if not s.settings.allow_wills:
        raise Rejected("will.disabled")
    if len(text or "") > s.settings.will_max:
        raise Rejected("will.too_long", count=s.settings.will_max)
    p.will = sanitize_text(text)


def set_death_note(s, slot: int, text: str) -> None:
    p = s.players.get(slot)
    if p is None or not p.alive:
        raise Rejected("error.dead")
    if p.role_id not in NOTE_ABILITY:
        raise Rejected("deathnote.not_allowed")
    if not s.settings.allow_deathnotes:
        raise Rejected("deathnote.disabled")
    if len(text or "") > s.settings.note_max:
        raise Rejected("deathnote.too_long", count=s.settings.note_max)
    p.death_notes[NOTE_ABILITY[p.role_id]] = sanitize_text(text)


def note_of(p) -> str:
    return (p.death_notes.get(NOTE_ABILITY.get(p.role_id, ""), "") or "") if p is not None else ""

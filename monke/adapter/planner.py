"""Permission planner: PURE function of game state (spec 10.2). No Discord imports.
Channel access is derived here, diffed against what is applied, and synced by the presenter.
No handler ever edits a permission directly."""
from __future__ import annotations

from typing import Optional

from .. import constants as C
from ..engine.state import GameState
from ..roles import get_def

NONE, VIEW, SEND = 0, 1, 2
TOWN, MAFIA, JAIL, GRAVEYARD = "town", "mafia", "jail", "graveyard"
CHANNELS = (TOWN, MAFIA, JAIL, GRAVEYARD)


def plan(state: Optional[GameState]) -> dict:
    """Returns {channel: {slot: level}}; slots absent from a channel have no access at all."""
    out: dict = {c: {} for c in CHANNELS}
    if state is None or state.status == C.STARTING:
        return out  # between games everything is hidden
    if state.status == C.ENDED:
        for slot in state.players:  # post-game chat: participants get Town Centre only
            out[TOWN][slot] = SEND
        return out
    paused = state.status == C.PAUSED  # fail closed: nobody can talk anywhere
    phase = state.phase
    defendant = state.trial["defendant"] if state.trial else None
    for slot, p in state.players.items():
        d = get_def(p.role_id)
        # Town Centre
        if not p.alive:
            lvl = VIEW
        elif paused or phase in (C.TRIAL_VERDICT, C.NIGHT):
            lvl = VIEW
        elif phase == C.TRIAL_DEFENSE:
            lvl = SEND if slot == defendant else VIEW
        else:
            lvl = SEND
        out[TOWN][slot] = lvl
        # Mafia Lair (dead non-Mafia never see it: D6)
        if d.alignment == C.MAFIA:
            night_talk = (p.alive and phase == C.NIGHT and not paused and slot != state.prisoner_slot)
            out[MAFIA][slot] = SEND if night_talk else VIEW
        # Jail: the prisoner only. The Jailor never has access (relay is via DM).
        if phase == C.NIGHT and not paused and p.alive and slot == state.prisoner_slot:
            out[JAIL][slot] = SEND
        # Graveyard
        if not p.alive:
            out[GRAVEYARD][slot] = SEND
    return out

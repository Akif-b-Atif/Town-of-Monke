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


def plan(state: Optional[GameState], archiving: bool = False) -> dict:
    """Returns {channel: {slot: level}}; slots absent from a channel have no access at all.
    `archiving=True` is the ARCHIVING mode (ARC-9): every game channel is hidden while the zip is built."""
    out: dict = {c: {} for c in CHANNELS}
    if archiving or state is None or state.status == C.STARTING:
        return out  # between games, and while archiving, everything is hidden
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
        if phase == C.NIGHT and p.alive and slot == state.prisoner_slot:
            out[JAIL][slot] = VIEW if paused else SEND
        # Graveyard: the dead talk freely, except while the game is paused (everything is read-only then)
        if not p.alive:
            out[GRAVEYARD][slot] = VIEW if paused else SEND
    return out



# --- Monke Commands (ADM-1): a static plan, independent of game state ---------
# Everyone can read the channel (so players see what the admin does and can
# download the archive later). Only Monke Admin can write there.
COMMANDS_EVERYONE = {
    "view_channel": True,
    "read_message_history": True,
    "send_messages": False,
    "add_reactions": False,
    "create_public_threads": False,
    "create_private_threads": False,
    "use_application_commands": False,
}
COMMANDS_ADMIN = {
    "send_messages": True,
    "use_application_commands": True,
}
# The bot needs explicit allows, because the @everyone denies above would
# otherwise also apply to it.
COMMANDS_BOT = {
    "view_channel": True,
    "read_message_history": True,
    "send_messages": True,
    "embed_links": True,
    "manage_messages": True,
    "add_reactions": True,
}


def commands_channel_plan() -> dict:
    """Permission plan for #monke-commands: {'everyone': {...}, 'admin': {...}, 'bot': {...}}.
    Each value maps a Discord permission name to True (allow) or False (deny)."""
    return {
        "everyone": dict(COMMANDS_EVERYONE),
        "admin": dict(COMMANDS_ADMIN),
        "bot": dict(COMMANDS_BOT),
    }

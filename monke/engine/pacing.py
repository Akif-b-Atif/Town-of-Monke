"""Pure helpers for warnings, nudges and early endings (QOL-2, PACE-2, PACE-3)."""
from __future__ import annotations

from typing import Optional

from .. import constants as C
from ..roles import get_handler

WARN_FRACTION, WARN_MIN, WARN_MAX, WARN_MIN_PHASE = 0.25, 30.0, 900.0, 60.0


def warning_lead(phase_length: float) -> Optional[float]:
    """Seconds before the end at which to warn: 25% of the phase, clamped to 30 s .. 15 min. Phases under 60 s
    (Defense and Verdict at normal timings) get none (QOL-2)."""
    if phase_length < WARN_MIN_PHASE:
        return None
    return min(max(phase_length * WARN_FRACTION, WARN_MIN), WARN_MAX)


def prompt_holders(s) -> list:
    """Slots that hold a night prompt right now."""
    out = []
    for slot in sorted(s.players):
        p = s.players[slot]
        if get_handler(p.role_id).prompts(s, p, C.KIND_NIGHT):
            out.append(slot)
    return out


def recorded(s, slot: int) -> bool:
    """An action is recorded, or the player explicitly chose to do nothing."""
    return slot in s.night_actions or slot in s.night_declined


def nudge_targets(s) -> list:
    """Night: players who hold a prompt and have no action recorded. The Mafia are nudged only when neither the
    Godfather nor the Mafioso has submitted. A player without a prompt is never nudged (QOL-2)."""
    if s.phase != C.NIGHT or s.status != C.RUNNING:
        return []
    holders = prompt_holders(s)
    killers = [x for x in holders if s.players[x].role_id in ("godfather", "mafioso")]
    mafia_done = any(recorded(s, x) for x in killers)
    return [x for x in holders if not recorded(s, x) and not (x in killers and mafia_done)]

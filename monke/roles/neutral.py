from __future__ import annotations

from .. import constants as C
from .base import AbilityDef, RoleDef, RoleHandler
from .registry import register

SERIAL_KILLER = RoleDef(
    "serial_killer", "Serial Killer", C.NEUTRAL, "NK", False, 1, 1, False, "Guilty", "SERIAL_KILLER",
    abilities=(AbilityDef("kill", C.KIND_NIGHT, "single", label="Choose who to kill"),),
    objective="Be the last killer standing: eliminate Town, Mafia and every other killer.",
    summary="Each night, attack one player.",
    special="Basic attack, Basic defense. If you are roleblocked you attack the blocker instead. If jailed, you attack the Jailor.",
    tips="Your Basic defense beats the Mafia's attacks.",
)

JESTER = RoleDef(
    "jester", "Jester", C.NEUTRAL, "NE", False, 3, 0, False, "Innocent", "JESTER",
    abilities=(AbilityDef("haunt", C.KIND_NIGHT, "single", label="Haunt a guilty voter"),),
    objective="Get yourself lynched. You win even if the game continues.",
    summary="If lynched, you may haunt one living player who voted guilty against you.",
    special="Your haunt is Unstoppable, does not visit, and cannot be jailed, blocked or healed. One use.",
    tips="Look suspicious, but not too suspicious.",
)


class SerialKillerHandler(RoleHandler):
    role = SERIAL_KILLER


class JesterHandler(RoleHandler):
    role = JESTER

    def init_state(self, state, player):
        return {"haunt_available": False, "haunt_targets": []}

    def valid_targets(self, state, player, ability):
        return [t for t in player.state.get("haunt_targets", []) if state.players[t].alive]

    def can_act(self, state, player, ability):
        return (
            not player.alive
            and not player.state.get("inactive")
            and bool(player.state.get("haunt_available"))
            and bool(self.valid_targets(state, player, ability))
        )


register(SERIAL_KILLER, SerialKillerHandler)
register(JESTER, JesterHandler)

from __future__ import annotations

from .. import constants as C
from .base import AbilityDef, RoleDef, RoleHandler
from .registry import get_def, register

_OBJ = "Kill everyone who would oppose the Mafia."

GODFATHER = RoleDef(
    "godfather", "Godfather", C.MAFIA, "LEADER", True, 1, 1, False, "Innocent", "MAFIA",
    abilities=(AbilityDef("order", C.KIND_NIGHT, "single", label="Order the kill"),),
    objective=_OBJ,
    summary="Each night, order the Mafia kill. The Mafioso carries it out if he can; otherwise you do it yourself.",
    special="You have Basic defense and appear Innocent to the Sheriff.",
    tips="If you are jailed or roleblocked your order is void.",
)

MAFIOSO = RoleDef(
    "mafioso", "Mafioso", C.MAFIA, "MK", True, 1, 0, False, "Guilty", "MAFIA",
    abilities=(AbilityDef("kill", C.KIND_NIGHT, "single", label="Choose who to kill"),),
    objective=_OBJ,
    summary="Carry out the Godfather's order. With no order, pick your own target.",
    special="Your attack is Basic.",
    tips="If the Godfather gives an order it overrides your choice.",
)

CONSIGLIERE = RoleDef(
    "consigliere", "Consigliere", C.MAFIA, "MS", False, 0, 0, False, "Guilty", "MAFIA",
    abilities=(AbilityDef("investigate", C.KIND_NIGHT, "single", label="Investigate someone"),),
    objective=_OBJ,
    summary="Each night, learn a player's exact role.",
    tips="Share your findings in the Lair, not in town.",
)


class _NoMafiaTargets(RoleHandler):
    def valid_targets(self, state, player, ability):
        return [
            t for t in super().valid_targets(state, player, ability)
            if get_def(state.players[t].role_id).alignment != C.MAFIA
        ]


class GodfatherHandler(_NoMafiaTargets):
    role = GODFATHER


class MafiosoHandler(_NoMafiaTargets):
    role = MAFIOSO


class ConsigliereHandler(RoleHandler):
    role = CONSIGLIERE


for _r, _h in ((GODFATHER, GodfatherHandler), (MAFIOSO, MafiosoHandler), (CONSIGLIERE, ConsigliereHandler)):
    register(_r, _h)

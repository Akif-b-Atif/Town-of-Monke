from __future__ import annotations

from .. import constants as C
from .base import AbilityDef, RoleDef, RoleHandler
from .registry import get_def, register

GODFATHER = RoleDef(
    "godfather", "Godfather", C.MAFIA, "LEADER", True, 1, 1, False, "Innocent", "MAFIA",
    abilities=(AbilityDef("order", C.KIND_NIGHT, "single"),),
)

MAFIOSO = RoleDef(
    "mafioso", "Mafioso", C.MAFIA, "MK", True, 1, 0, False, "Guilty", "MAFIA",
    abilities=(AbilityDef("kill", C.KIND_NIGHT, "single"),),
)

CONSIGLIERE = RoleDef(
    "consigliere", "Consigliere", C.MAFIA, "MS", False, 0, 0, False, "Guilty", "MAFIA",
    abilities=(AbilityDef("investigate", C.KIND_NIGHT, "single"),),
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

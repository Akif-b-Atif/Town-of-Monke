from __future__ import annotations

from .. import constants as C
from ..errors import Rejected
from .base import AbilityDef, RoleDef, RoleHandler
from .registry import register

# D1: Town of Salem gives the Veteran Basic defense while on alert. The spec table says "None" and
# asks for verification, so this is a single switch. Set to 0 to make alerting Veterans fragile.
VETERAN_ALERT_DEFENSE = 1

JAILOR = RoleDef(
    "jailor", "Jailor", C.TOWN, "LEADER", True, 3, 0, True, "Innocent", "TOWN",
    abilities=(
        AbilityDef("jail", C.KIND_DAY, "single"),
        AbilityDef("execute", C.KIND_NIGHT, "toggle"),
    ),
)


class JailorHandler(RoleHandler):
    role = JAILOR

    def init_state(self, state, player):
        return {"jailor_exec_disabled": False}

    def toggle_block_reason(self, state, player, ability):
        if player.state.get("jailor_exec_disabled"):
            return "jailor.exec_disabled"
        if state.prisoner_slot is None:
            return "error.no_prisoner"
        return None


VETERAN = RoleDef(
    "veteran", "Veteran", C.TOWN, "TK", True, 2, 0, True, "Innocent", "TOWN",
    abilities=(AbilityDef("alert", C.KIND_NIGHT, "toggle"),),
    alert_defense=VETERAN_ALERT_DEFENSE,
)


class VeteranHandler(RoleHandler):
    role = VETERAN

    def init_state(self, state, player):
        return {"alerts_left": max(1, len(state.players) // 5)}

    def toggle_block_reason(self, state, player, ability):
        if player.state.get("alerts_left", 0) <= 0:
            return "vet.no_alerts"
        return None

    def uses_left(self, state, player, ability):
        return player.state.get("alerts_left", 0)


SHERIFF = RoleDef(
    "sheriff", "Sheriff", C.TOWN, "TI", False, 0, 0, False, "Innocent", "TOWN",
    abilities=(AbilityDef("investigate", C.KIND_NIGHT, "single"),),
)

DOCTOR = RoleDef(
    "doctor", "Doctor", C.TOWN, "TP", False, 0, 0, False, "Innocent", "TOWN",
    abilities=(AbilityDef("heal", C.KIND_NIGHT, "single", self_allowed=True),),
)


class DoctorHandler(RoleHandler):
    role = DOCTOR

    def init_state(self, state, player):
        return {"self_heals_left": 1}

    def validate(self, state, player, ability, target, active):
        if target == player.slot and player.state.get("self_heals_left", 0) <= 0:
            raise Rejected("doctor.no_self_heal")
        super().validate(state, player, ability, target, active)

    def valid_targets(self, state, player, ability):
        targets = super().valid_targets(state, player, ability)
        if player.state.get("self_heals_left", 0) <= 0:
            targets = [t for t in targets if t != player.slot]
        return targets


ESCORT = RoleDef(
    "escort", "Escort", C.TOWN, "TS", False, 0, 0, True, "Innocent", "TOWN",
    abilities=(AbilityDef("roleblock", C.KIND_NIGHT, "single"),),
)


class SheriffHandler(RoleHandler):
    role = SHERIFF


class EscortHandler(RoleHandler):
    role = ESCORT


for _r, _h in ((JAILOR, JailorHandler), (VETERAN, VeteranHandler), (SHERIFF, SheriffHandler),
               (DOCTOR, DoctorHandler), (ESCORT, EscortHandler)):
    register(_r, _h)

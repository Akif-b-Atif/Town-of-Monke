from __future__ import annotations

from .. import constants as C
from .base import AbilityDef, RoleDef, RoleHandler
from .registry import register

# D1: Town of Salem gives the Veteran Basic defense while on alert. The spec table says "None" and
# asks for verification, so this is a single switch. Set to 0 to make alerting Veterans fragile.
VETERAN_ALERT_DEFENSE = 1

JAILOR = RoleDef(
    "jailor", "Jailor", C.TOWN, "LEADER", True, 3, 0, True, "Innocent", "TOWN",
    abilities=(
        AbilityDef("jail", C.KIND_DAY, "single", label="Choose who to jail tonight"),
        AbilityDef("execute", C.KIND_NIGHT, "toggle", label="Execute your prisoner"),
    ),
    objective="Lynch every criminal and evildoer.",
    summary="By day, pick a prisoner. At night you can talk to them anonymously and choose to execute them.",
    special="Your attack is Unstoppable and ignores heals. Executing a Town member removes your execution for the rest of the game. You cannot be roleblocked.",
    tips="Interrogate before you execute.",
)


class JailorHandler(RoleHandler):
    role = JAILOR

    def init_state(self, state, player):
        return {"jailor_exec_disabled": False}

    def toggle_block_reason(self, state, player, ability):
        if player.state.get("jailor_exec_disabled"):
            return "You executed a Town member and can no longer execute."
        if state.prisoner_slot is None:
            return "You have no prisoner tonight."
        return None


VETERAN = RoleDef(
    "veteran", "Veteran", C.TOWN, "TK", True, 2, 0, True, "Innocent", "TOWN",
    abilities=(AbilityDef("alert", C.KIND_NIGHT, "toggle", label="Go on alert tonight"),),
    alert_defense=VETERAN_ALERT_DEFENSE,
    objective="Lynch every criminal and evildoer.",
    summary="At night you may go on alert (limited uses). Everyone who visits you while on alert is shot.",
    special="Your attack is Powerful. You cannot be roleblocked. Alerts: one per 5 players (minimum 1).",
    tips="Alert on nights you expect to be targeted, but you cannot tell friend from foe.",
)


class VeteranHandler(RoleHandler):
    role = VETERAN

    def init_state(self, state, player):
        return {"alerts_left": max(1, len(state.players) // 5)}

    def toggle_block_reason(self, state, player, ability):
        if player.state.get("alerts_left", 0) <= 0:
            return "You have no alerts left."
        return None

    def label_for(self, state, player, ability):
        return f"{ability.label} ({player.state.get('alerts_left', 0)} left)"


SHERIFF = RoleDef(
    "sheriff", "Sheriff", C.TOWN, "TI", False, 0, 0, False, "Innocent", "TOWN",
    abilities=(AbilityDef("investigate", C.KIND_NIGHT, "single", label="Investigate someone"),),
    objective="Lynch every criminal and evildoer.",
    summary="Each night, check whether a player seems Innocent or Guilty.",
    special="The Godfather appears Innocent. Mafia and Serial Killers appear Guilty.",
    tips="Share results carefully; the Mafia will claim your role.",
)

DOCTOR = RoleDef(
    "doctor", "Doctor", C.TOWN, "TP", False, 0, 0, False, "Innocent", "TOWN",
    abilities=(AbilityDef("heal", C.KIND_NIGHT, "single", self_allowed=True, label="Heal someone"),),
    objective="Lynch every criminal and evildoer.",
    summary="Each night, heal one player. A healed player survives Basic and Powerful attacks.",
    special="You may heal yourself once. You are told if your patient was attacked.",
    tips="Healing the same person every night makes you predictable.",
)


class DoctorHandler(RoleHandler):
    role = DOCTOR

    def init_state(self, state, player):
        return {"self_heals_left": 1}

    def valid_targets(self, state, player, ability):
        targets = super().valid_targets(state, player, ability)
        if player.state.get("self_heals_left", 0) <= 0:
            targets = [t for t in targets if t != player.slot]
        return targets


ESCORT = RoleDef(
    "escort", "Escort", C.TOWN, "TS", False, 0, 0, True, "Innocent", "TOWN",
    abilities=(AbilityDef("roleblock", C.KIND_NIGHT, "single", label="Distract someone"),),
    objective="Lynch every criminal and evildoer.",
    summary="Each night, distract one player. They cannot use their ability.",
    special="You cannot be roleblocked. Some roles are immune to your distraction. A Serial Killer you block will attack you.",
    tips="Blocking a suspected killer is risky: if it is the Serial Killer, you may die.",
)


class SheriffHandler(RoleHandler):
    role = SHERIFF


class EscortHandler(RoleHandler):
    role = ESCORT


for _r, _h in ((JAILOR, JailorHandler), (VETERAN, VeteranHandler), (SHERIFF, SheriffHandler),
               (DOCTOR, DoctorHandler), (ESCORT, EscortHandler)):
    register(_r, _h)

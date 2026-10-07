"""Role definitions (pure data) and the handler base class."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from .. import constants as C
from ..errors import Rejected

if TYPE_CHECKING:  # pragma: no cover
    from ..engine.state import GameState, Player


@dataclass(frozen=True)
class AbilityDef:
    id: str
    phase: str  # C.KIND_DAY | C.KIND_NIGHT
    targeting: str  # "single" | "toggle"
    self_allowed: bool = False
    label: str = ""


@dataclass(frozen=True)
class RoleDef:
    id: str
    name: str
    alignment: str
    group: str  # TK TI TP TS MK MS NK NE or LEADER
    unique: bool
    attack_level: int
    defense_level: int
    rb_immune: bool
    sheriff_result: str  # "Innocent" | "Guilty"
    win_faction: str  # TOWN | MAFIA | SERIAL_KILLER | JESTER
    abilities: tuple = ()
    alert_defense: int = 0  # defense while an alert is active (Veteran)
    objective: str = ""
    summary: str = ""
    special: str = ""
    tips: str = ""


@dataclass
class Prompt:
    ability_id: str
    kind: str  # "select" | "toggle"
    options: list
    label: str
    phase_kind: str


class RoleHandler:
    """Per-role logic hooks. Night *resolution* lives in engine/night.py (one pipeline, so the
    ordering rules stay in one place); handlers own initial state, prompts and validation."""

    role: RoleDef

    def init_state(self, state: "GameState", player: "Player") -> dict:
        return {}

    def ability(self, ability_id: str) -> Optional[AbilityDef]:
        for a in self.role.abilities:
            if a.id == ability_id:
                return a
        return None

    @staticmethod
    def is_active(player: "Player") -> bool:
        return player.alive and not player.state.get("inactive")

    def can_act(self, state: "GameState", player: "Player", ability: AbilityDef) -> bool:
        return self.is_active(player)

    def valid_targets(self, state: "GameState", player: "Player", ability: AbilityDef) -> list:
        return [
            s for s, p in sorted(state.players.items())
            if p.alive and (s != player.slot or ability.self_allowed)
        ]

    def toggle_block_reason(self, state: "GameState", player: "Player", ability: AbilityDef) -> Optional[str]:
        return None

    def label_for(self, state: "GameState", player: "Player", ability: AbilityDef) -> str:
        return ability.label

    @staticmethod
    def phase_ok(state: "GameState", ability: AbilityDef) -> bool:
        if ability.phase == C.KIND_NIGHT:
            return state.phase == C.NIGHT
        return state.phase in C.DAY_PHASES

    def validate(self, state: "GameState", player: "Player", ability: AbilityDef,
                 target: Optional[int], active: bool) -> None:
        if state.status != C.RUNNING:
            raise Rejected("The game is not running.")
        if not self.phase_ok(state, ability):
            raise Rejected("You can't do that right now.")
        if not self.can_act(state, player, ability):
            raise Rejected("You can't use that ability right now.")
        if ability.targeting == "single":
            if target is not None and target not in self.valid_targets(state, player, ability):
                raise Rejected("That is not a valid target.")
        elif ability.targeting == "toggle":
            if target is not None:
                raise Rejected("That ability does not take a target.")
            if active:
                reason = self.toggle_block_reason(state, player, ability)
                if reason:
                    raise Rejected(reason)

    def prompts(self, state: "GameState", player: "Player", phase_kind: str) -> list:
        out = []
        for ab in self.role.abilities:
            if ab.phase != phase_kind or not self.can_act(state, player, ab):
                continue
            label = self.label_for(state, player, ab)
            if ab.targeting == "toggle":
                if self.toggle_block_reason(state, player, ab):
                    continue
                out.append(Prompt(ab.id, "toggle", [], label, phase_kind))
            elif ab.targeting == "single":
                opts = self.valid_targets(state, player, ab)
                if opts:
                    out.append(Prompt(ab.id, "select", opts, label, phase_kind))
        return out

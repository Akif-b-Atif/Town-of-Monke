from __future__ import annotations

import copy
import random
from dataclasses import asdict, dataclass, field, fields
from typing import Optional

from .. import constants as C
from .settings import Settings

SCHEMA_VERSION = 1


@dataclass
class Player:
    slot: int
    user_id: int
    role_id: str
    alive: bool = True
    death: Optional[dict] = None
    state: dict = field(default_factory=dict)


@dataclass
class Action:
    actor_slot: int
    ability_id: str
    target_slot: Optional[int] = None
    active: bool = True
    submitted_at: float = 0.0


@dataclass
class GameState:
    game_id: str
    guild_id: int
    status: str = C.STARTING
    phase: str = C.NO_PHASE
    phase_id: int = 0
    day_number: int = 0
    night_number: int = 0
    phase_ends_at: float = 0.0
    paused_remaining: Optional[float] = None  # noon time saved while a trial runs
    admin_pause_remaining: Optional[float] = None  # phase time saved by Pause
    settings: Settings = field(default_factory=Settings)
    rolelist: list = field(default_factory=list)
    rng_seed: int = 0
    rng_state: Optional[list] = None
    players: dict = field(default_factory=dict)  # slot -> Player
    votes: dict = field(default_factory=dict)  # voter -> target
    trial: Optional[dict] = None  # {"defendant": int, "verdicts": {voter: verdict}}
    pending_jail_slot: Optional[int] = None  # Jailor's day choice
    prisoner_slot: Optional[int] = None  # locked at night entry
    night_actions: dict = field(default_factory=dict)  # slot -> Action
    innocent_verdicts_today: int = 0
    pardoned_today: list = field(default_factory=list)
    quiet_cycles: int = 0
    death_this_cycle: bool = False
    winners: list = field(default_factory=list)
    winning_faction: Optional[str] = None
    end_reason: Optional[str] = None
    event_log_seq: int = 0

    # ---- helpers ----
    def alive_slots(self) -> list:
        return sorted(s for s, p in self.players.items() if p.alive)

    def slot_of_user(self, user_id: int) -> Optional[int]:
        for s, p in self.players.items():
            if p.user_id == user_id:
                return s
        return None

    def token_for(self, phase_kind: str) -> str:
        """Prompt freshness token. Night prompts die with the phase; day prompts last the whole day."""
        return f"n{self.phase_id}" if phase_kind == C.KIND_NIGHT else f"d{self.day_number}"

    def rng(self) -> random.Random:
        r = random.Random(self.rng_seed)
        if self.rng_state:
            v, internal, gauss = self.rng_state
            r.setstate((v, tuple(internal), gauss))
        return r

    def save_rng(self, r: random.Random) -> None:
        v, internal, gauss = r.getstate()
        self.rng_state = [v, list(internal), gauss]

    # ---- serialization ----
    def to_dict(self) -> dict:
        d = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if f.name == "settings":
                v = asdict(v)
            elif f.name == "players":
                v = {str(k): asdict(p) for k, p in v.items()}
            elif f.name == "votes":
                v = {str(k): t for k, t in v.items()}
            elif f.name == "night_actions":
                v = {str(k): asdict(a) for k, a in v.items()}
            elif f.name == "trial" and v:
                v = {"defendant": v["defendant"], "verdicts": {str(k): x for k, x in v["verdicts"].items()}}
            else:
                v = copy.deepcopy(v)
            d[f.name] = v
        d["schema_version"] = SCHEMA_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        d = dict(d)
        ver = d.pop("schema_version", SCHEMA_VERSION)
        if ver != SCHEMA_VERSION:
            raise ValueError(f"Unsupported snapshot schema_version {ver}")
        d["settings"] = Settings(**d["settings"])
        d["players"] = {int(k): Player(**v) for k, v in d["players"].items()}
        d["votes"] = {int(k): int(v) for k, v in d["votes"].items()}
        d["night_actions"] = {int(k): Action(**v) for k, v in d["night_actions"].items()}
        t = d.get("trial")
        if t:
            d["trial"] = {"defendant": t["defendant"], "verdicts": {int(k): x for k, x in t["verdicts"].items()}}
        return cls(**d)

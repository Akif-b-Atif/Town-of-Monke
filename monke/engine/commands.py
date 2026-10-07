"""Commands: the only way to change state. Plain data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BeginGame:
    pass


@dataclass
class AdvancePhase:
    expected_phase_id: int
    force: bool = False  # `monke skip`


@dataclass
class Vote:
    voter_slot: int
    target_slot: Optional[int]  # None = unvote


@dataclass
class Verdict:
    voter_slot: int
    verdict: str


@dataclass
class SubmitAction:
    actor_slot: int
    ability_id: str
    target_slot: Optional[int] = None
    active: bool = True  # for toggles; False (or no target for single) clears the choice


@dataclass
class Pause:
    reason: str = ""


@dataclass
class Resume:
    pass


@dataclass
class Abort:
    reason: str = "aborted by an admin"


@dataclass
class Abandon:
    slot: int

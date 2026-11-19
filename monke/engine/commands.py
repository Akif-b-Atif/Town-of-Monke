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
    by: str = ""  # display name of the admin who skipped (for the banner)


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
class ToggleSkipVote:
    """PACE-2: a player presses Skip ahead (or presses it again to take the vote back)."""
    slot: int


@dataclass
class ConfirmNight:
    """PACE-3: a player confirms their night is done."""
    slot: int


@dataclass
class NoteActivity:
    """PACE-7: a player did something that counts as activity (a Town Centre message)."""
    slot: int


@dataclass
class SetWill:
    slot: int
    text: str


@dataclass
class SetDeathNote:
    slot: int
    text: str


@dataclass
class ShiftDeadline:
    """REL-6: move the running phase's deadline (time given back after downtime). Goes through the command log."""
    new_end: float
    reason: str = "downtime"


@dataclass
class Abort:
    reason: str = "aborted by an admin"


@dataclass
class Abandon:
    slot: int

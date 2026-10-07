"""Engine output. Events are plain data; the adapter decides how to show them."""
from __future__ import annotations

from dataclasses import dataclass, field

PUBLIC = "public"
ADMIN = "admin"


def to_slot(n: int) -> str:
    return f"slot:{n}"


def to_alignment(a: str) -> str:
    return f"alignment:{a}"


class T:
    PHASE_CHANGED = "PhaseChanged"
    ANNOUNCEMENT = "Announcement"
    PLAYER_DIED = "PlayerDied"
    PRIVATE = "PrivateMessage"
    VOTE = "VoteUpdated"
    TRIAL_STARTED = "TrialStarted"
    VERDICT_OPENED = "VerdictOpened"
    VERDICT_RECORDED = "VerdictRecorded"
    VERDICTS_REVEALED = "VerdictsRevealed"
    PROMPT = "PromptRequested"
    ACTION_RECORDED = "ActionRecorded"
    ROLE_ASSIGNED = "RoleAssigned"
    ROSTER = "RosterPosted"
    GAME_ENDED = "GameEnded"
    JAIL_STARTED = "JailStarted"
    JAIL_ENDED = "JailEnded"
    STATUS = "StatusChanged"


@dataclass
class Event:
    type: str
    payload: dict = field(default_factory=dict)
    audience: str = PUBLIC
    seq: int = 0


def ev(type_: str, audience: str = PUBLIC, **payload) -> Event:
    return Event(type_, payload, audience)

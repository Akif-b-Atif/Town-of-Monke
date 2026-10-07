from __future__ import annotations

from typing import Optional

from .. import constants as C
from ..errors import Rejected
from . import events as E


def threshold(alive_count: int) -> int:
    return alive_count // 2 + 1  # strict majority of living players


def _voter(s, slot: int):
    p = s.players.get(slot)
    if p is None or not p.alive or p.state.get("inactive"):
        raise Rejected("Only living players can do that.")
    return p


def cast_vote(s, voter: int, target: Optional[int], events: list) -> Optional[int]:
    """Record or clear a vote. Returns the defendant slot if the threshold was reached."""
    if s.phase != C.NOON:
        raise Rejected("Voting is only open at noon.")
    _voter(s, voter)
    need = threshold(len(s.alive_slots()))
    if target is None:
        prev = s.votes.pop(voter, None)
        count = sum(1 for t in s.votes.values() if t == prev) if prev is not None else 0
        events.append(E.ev(E.T.VOTE, voter=voter, target=None, previous=prev, count=count, threshold=need))
        return None
    t = s.players.get(target)
    if t is None or not t.alive:
        raise Rejected("You can only vote for a living player.")
    if target == voter:
        raise Rejected("You can't vote for yourself.")
    if target in s.pardoned_today:
        raise Rejected("That player was already pardoned today.")
    prev = s.votes.get(voter)
    s.votes[voter] = target
    count = sum(1 for x in s.votes.values() if x == target)
    events.append(E.ev(E.T.VOTE, voter=voter, target=target, previous=prev, count=count, threshold=need))
    return target if count >= need else None


def cast_verdict(s, voter: int, verdict: str, events: list) -> None:
    if s.phase != C.TRIAL_VERDICT or not s.trial:
        raise Rejected("There is no verdict to cast right now.")
    _voter(s, voter)
    if voter == s.trial["defendant"]:
        raise Rejected("The defendant cannot vote on their own trial.")
    if verdict not in (C.GUILTY, C.INNOCENT, C.ABSTAIN):
        raise Rejected("Verdict must be guilty, innocent or abstain.")
    s.trial["verdicts"][voter] = verdict
    events.append(E.ev(E.T.VERDICT_RECORDED, E.to_slot(voter), verdict=verdict))

from __future__ import annotations

from typing import Optional

from .. import constants as C
from ..errors import Rejected
from . import events as E


def threshold(alive_count: int) -> int:
    return alive_count // 2 + 1  # strict majority of living players


def next_noon(s) -> dict:
    """When voting next opens, as data ('Day 3 Noon'): the renderer words it."""
    if s.phase in (C.DAY_1, C.DAY):
        return {"when": "noon", "day": s.day_number} if s.phase == C.DAY else {"when": "noon", "day": 2}
    return {"when": "noon", "day": s.day_number + 1}


def _voter(s, slot: int):
    p = s.players.get(slot)
    if p is None or not p.alive or p.state.get("inactive"):
        raise Rejected("error.dead")
    return p


def cast_vote(s, voter: int, target: Optional[int], events: list) -> Optional[int]:
    """Record or clear a vote. Returns the defendant slot if the threshold was reached."""
    if s.phase != C.NOON:
        raise Rejected("error.vote_wrong_phase", time=next_noon(s))
    _voter(s, voter)
    need = threshold(len(s.alive_slots()))
    if target is None:
        prev = s.votes.pop(voter, None)
        count = sum(1 for t in s.votes.values() if t == prev) if prev is not None else 0
        events.append(E.ev(E.T.VOTE, voter=voter, target=None, previous=prev, count=count, threshold=need))
        return None
    t = s.players.get(target)
    if t is None or not t.alive:
        raise Rejected("error.dead_target")
    if target == voter:
        raise Rejected("error.self_target")
    if target in s.pardoned_today:
        raise Rejected("error.already_pardoned")
    prev = s.votes.get(voter)
    s.votes[voter] = target
    count = sum(1 for x in s.votes.values() if x == target)
    events.append(E.ev(E.T.VOTE, voter=voter, target=target, previous=prev, count=count, threshold=need))
    return target if count >= need else None


def cast_verdict(s, voter: int, verdict: str, events: list) -> None:
    if s.phase != C.TRIAL_VERDICT or not s.trial:
        raise Rejected("error.no_verdict")
    _voter(s, voter)
    if voter == s.trial["defendant"]:
        raise Rejected("error.defendant_cannot_vote")
    if verdict not in (C.GUILTY, C.INNOCENT, C.ABSTAIN):
        raise Rejected("error.bad_verdict")
    s.trial["verdicts"][voter] = verdict
    events.append(E.ev(E.T.VERDICT_RECORDED, E.to_slot(voter), verdict=verdict))

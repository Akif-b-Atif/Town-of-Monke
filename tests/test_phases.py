import pytest

from monke import constants as C
from monke.engine import Settings, handle, new_game
from monke.engine import commands as K
from monke.engine.voting import threshold
from monke.errors import Rejected

TOKENS = ["Jailor", "Godfather", "TI", "TP", "TS", "MK", "NK", "RT"]  # 8 players


def started(seed=1, tokens=TOKENS):
    s, _ = new_game("g", 1, list(range(100, 100 + len(tokens))), tokens, Settings(), seed)
    return handle(s, K.BeginGame(), 0).state


def adv(s, now=None, force=True):
    return handle(s, K.AdvancePhase(s.phase_id, force=force), s.phase_ends_at if now is None else now).state


def to_noon(s):
    s = adv(s)            # DAY_1 -> NIGHT
    assert s.phase == C.NIGHT
    s = adv(s)            # -> DAY 2
    assert s.phase == C.DAY and s.day_number == 2
    return adv(s)         # -> NOON


def test_day1_skips_noon_and_is_half_length():
    s = started()
    assert s.phase == C.DAY_1 and s.phase_ends_at == s.settings.day_s / 2
    s = adv(s)
    assert s.phase == C.NIGHT and s.night_number == 1


@pytest.mark.parametrize("alive,need", [(5, 3), (6, 4), (7, 4), (8, 5), (20, 11)])
def test_threshold(alive, need):
    assert threshold(alive) == need


def test_vote_to_trial_and_lynch():
    s = to_noon(started())
    a = s.alive_slots()
    target = a[0]
    need = threshold(len(a))
    voters = [x for x in a if x != target][:need]
    for v in voters:
        s = handle(s, K.Vote(v, target), s.phase_ends_at - 100).state
    assert s.phase == C.TRIAL_DEFENSE and s.trial["defendant"] == target
    assert s.paused_remaining == pytest.approx(100.0)
    s = adv(s)
    assert s.phase == C.TRIAL_VERDICT
    for v in [x for x in a if x != target]:
        s = handle(s, K.Verdict(v, C.GUILTY), s.phase_ends_at - 5).state
    s = adv(s)
    assert not s.players[target].alive
    assert s.players[target].death["causes"] == [C.LYNCHED]
    assert s.phase in (C.AFTERNOON, C.ENDED)


def _trial(s, defendant, verdicts):
    a = s.alive_slots()
    voters = [x for x in a if x != defendant][:threshold(len(a))]
    for v in voters:
        s = handle(s, K.Vote(v, defendant), s.phase_ends_at - 100).state
    s = adv(s)
    for v, verdict in verdicts.items():
        s = handle(s, K.Verdict(v, verdict), s.phase_ends_at - 1).state
    return adv(s)


def test_tie_pardons_and_returns_to_noon_with_time_restored():
    s = to_noon(started())
    a = s.alive_slots()
    d = a[0]
    others = [x for x in a if x != d]
    s = _trial(s, d, {others[0]: C.GUILTY, others[1]: C.INNOCENT})
    assert s.players[d].alive and s.phase == C.NOON
    assert s.innocent_verdicts_today == 1 and d in s.pardoned_today
    assert s.votes == {}
    with pytest.raises(Rejected):
        handle(s, K.Vote(others[0], d), 0)  # pardoned players can't be voted again today


def test_innocent_majority_and_three_pardons_end_noon():
    s = to_noon(started())
    for i in range(3):
        d = [x for x in s.alive_slots() if x not in s.pardoned_today][0]
        others = [x for x in s.alive_slots() if x != d]
        s = _trial(s, d, {o: C.INNOCENT for o in others})
    assert s.phase == C.AFTERNOON


def test_abstain_default_and_guilty_must_exceed_innocent():
    s = to_noon(started())
    d = s.alive_slots()[0]
    s = _trial(s, d, {})  # everyone abstains -> 0 guilty is not > 0 innocent
    assert s.players[d].alive


def test_stale_timer_ignored_and_early_timer_ignored():
    s = started()
    stale = handle(s, K.AdvancePhase(s.phase_id - 1), s.phase_ends_at)
    assert stale.state.phase == s.phase and stale.events == []
    early = handle(s, K.AdvancePhase(s.phase_id), 0.0)
    assert early.state.phase == s.phase


def test_votes_rejected_outside_noon_and_self_votes():
    s = started()
    with pytest.raises(Rejected):
        handle(s, K.Vote(1, 2), 0)
    s = to_noon(s)
    with pytest.raises(Rejected):
        handle(s, K.Vote(1, 1), 0)


def test_pause_resume_and_abort():
    s = started()
    p = handle(s, K.Pause("boom"), 10).state
    assert p.status == C.PAUSED
    with pytest.raises(Rejected):
        handle(p, K.SubmitAction(1, "jail", None), 0)
    r = handle(p, K.Resume(), 500).state
    assert r.status == C.RUNNING and r.phase_ends_at == pytest.approx(500 + s.phase_ends_at - 10)
    ended = handle(r, K.Abort(), 600)
    assert ended.state.status == C.ENDED
    assert ended.events[-1].type == "GameEnded"


def test_abandoned_player_dies_at_dawn():
    s = started()
    slot = s.alive_slots()[0]
    s = handle(s, K.Abandon(slot), 0).state
    s = adv(s)
    s = adv(s)
    assert not s.players[slot].alive or s.status == C.ENDED
    if s.players[slot].death:
        assert s.players[slot].death["causes"] == [C.ABANDONED]


def test_stalemate_draw_after_three_quiet_cycles():
    s = started(tokens=["Jailor", "Godfather", "TI", "TP", "TS", "NK", "TK", "NE"])
    for _ in range(12):
        if s.status == C.ENDED:
            break
        s = adv(s)
    assert s.status == C.ENDED and s.winning_faction == "DRAW"


def test_jester_lynch_wins_game_continues_and_haunt_targets_recorded():
    tokens = ["Jailor", "Godfather", "TI", "TP", "TS", "MK", "NE", "RT", "RT"]
    s = to_noon(started(tokens=tokens))
    j = next(p.slot for p in s.players.values() if p.role_id == "jester")
    others = [x for x in s.alive_slots() if x != j]
    s = _trial(s, j, {o: C.GUILTY for o in others})
    assert j in s.winners and s.status == C.RUNNING
    assert sorted(s.players[j].state["haunt_targets"]) == sorted(others)
    assert s.players[j].state["haunt_available"]

"""QOL-2: warning point, nudges, and the second wake-up."""
import asyncio

import pytest

from monke import constants as C
from monke.engine import Settings, handle, new_game
from monke.engine import commands as K
from monke.engine.pacing import nudge_targets, prompt_holders, warning_lead
from tests.crashworld import NAMES, TOKENS, USERS, Clock, Proc, World, new_path


@pytest.mark.parametrize("length,lead", [(30, None), (59, None), (60, 30), (120, 30), (240, 60), (3600, 900), (7200, 900)])
def test_warning_point_is_a_quarter_of_the_phase_clamped(length, lead):
    assert warning_lead(length) == lead


def night_game():
    s, _ = new_game("g", 1, USERS, ["Jailor", "Godfather", "Mafioso", "Sheriff", "Doctor"], Settings(), 3, names=NAMES)
    s = handle(s, K.BeginGame(), 0).state
    return handle(s, K.AdvancePhase(s.phase_id, force=True), 1).state


def test_only_prompt_holders_with_nothing_recorded_are_nudged():
    s = night_game()
    holders = prompt_holders(s)
    assert s.phase == C.NIGHT and holders
    nudged = nudge_targets(s)
    assert set(nudged) == set(holders)
    sheriff = next(x for x in holders if s.players[x].role_id == "sheriff")
    target = next(x for x in s.alive_slots() if x != sheriff)
    s = handle(s, K.SubmitAction(sheriff, "investigate", target), 2).state
    assert sheriff not in nudge_targets(s)
    # an explicit 'do nothing' counts as recorded
    doctor = next(x for x in holders if s.players[x].role_id == "doctor")
    s = handle(s, K.SubmitAction(doctor, "heal", None), 3).state
    assert doctor not in nudge_targets(s)
    # and changing your mind back to a real choice records it again
    s = handle(s, K.SubmitAction(doctor, "heal", target), 4).state
    assert doctor in s.night_actions and doctor not in s.night_declined


def test_the_mafia_is_nudged_only_when_neither_killer_has_submitted():
    s = night_game()
    gf = next(x for x in s.players if s.players[x].role_id == "godfather")
    mf = next(x for x in s.players if s.players[x].role_id == "mafioso")
    assert gf in nudge_targets(s) and mf in nudge_targets(s)
    victim = next(x for x in s.alive_slots() if s.players[x].role_id == "doctor")
    s = handle(s, K.SubmitAction(gf, "order", victim), 2).state
    assert gf not in nudge_targets(s) and mf not in nudge_targets(s)


def test_a_player_without_a_prompt_is_never_nudged_and_day_has_no_nudges():
    s = night_game()
    for x in nudge_targets(s):
        assert prompt_holders(s).count(x) == 1
    s2, _ = new_game("g", 1, USERS, TOKENS, Settings(), 3, names=NAMES)
    assert nudge_targets(handle(s2, K.BeginGame(), 0).state) == []


def test_the_warning_is_posted_once_and_ignored_after_the_phase_changed():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        posted = []

        async def post_key(s, channel, key, **vars):
            posted.append((key, vars.get("time")))
        a.pres.post_key = post_key
        s = await a.svc.start_game(1, USERS, TOKENS, Settings(), seed=5, names=NAMES)
        clock.advance(s.phase_length - 40)  # 40 s left
        await a.svc._on_warn(s.game_id, s.phase_id)
        assert posted == [("phase.warning", pytest.approx(40, abs=1))]
        posted.clear()
        await a.svc.submit(1, K.AdvancePhase(s.phase_id, force=True))
        await a.svc._on_warn(s.game_id, s.phase_id)  # the phase changed: ignored
        assert posted == []
        a.svc.scheduler.cancel(s.game_id)
    asyncio.run(go())


def test_the_warning_is_armed_only_when_the_point_is_still_ahead():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await a.svc.start_game(1, USERS, TOKENS, Settings(), seed=5, names=NAMES)
        assert s.game_id in a.svc.scheduler._warns  # 120 s Day 1: warns at 30 s before the end
        a.svc.scheduler.cancel(s.game_id)
        assert s.game_id not in a.svc.scheduler._warns
    asyncio.run(go())

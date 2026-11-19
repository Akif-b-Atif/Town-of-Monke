"""M16: the permission matrix for every state, DEAD-1..5, PACE-2/3/5/7."""
import pytest

from monke import constants as C
from monke.adapter import planner
from monke.adapter.planner import GRAVEYARD, JAIL, MAFIA, SEND, TOWN, VIEW
from monke.compose import Composer
from monke.engine import commands as K
from monke.engine import deaths, handle
from monke.engine.phases import skip_needed
from monke.errors import Rejected
from monke.text.bank import default_bank
from tests.helpers import make_state

C_ = Composer(default_bank(), fixed=True)
# make_state's cast: 1 Jailor, 2 Veteran, 3 Sheriff, 4 Doctor, 5 Escort, 6 Godfather, 7 Mafioso, 8 Consigliere,
# 9 Serial Killer, 10 Jester


def plan(s):
    return planner.plan(s)


# ------------------------------------------------------------------ the matrix (section 6 and PACE-5)
@pytest.mark.parametrize("phase,alive_town", [(C.DAY, SEND), (C.NOON, SEND), (C.AFTERNOON, SEND), (C.NIGHT, VIEW),
                                              (C.TRIAL_VERDICT, VIEW)])
def test_alive_players_talk_in_town_by_phase(phase, alive_town):
    p = plan(make_state(phase=phase))
    assert p[TOWN][3] == alive_town
    assert 3 not in p[GRAVEYARD] and 3 not in p[MAFIA] and 3 not in p[JAIL]  # hidden from the living town player


def test_the_defendant_speaks_at_trial_and_everyone_else_only_reads():
    s = make_state(phase=C.TRIAL_DEFENSE)
    s.trial = {"defendant": 4}
    p = plan(s)
    assert p[TOWN][4] == SEND and all(v == VIEW for slot, v in p[TOWN].items() if slot != 4)


def test_dead_players_view_town_and_talk_in_the_graveyard_every_phase():
    for phase in (C.DAY, C.NOON, C.NIGHT, C.TRIAL_DEFENSE, C.AFTERNOON):
        s = make_state(phase=phase)
        s.players[3].alive = False
        s.trial = {"defendant": 4} if phase == C.TRIAL_DEFENSE else None
        p = plan(s)
        assert p[TOWN][3] == VIEW and p[GRAVEYARD][3] == SEND and 3 not in p[MAFIA] and 3 not in p[JAIL], phase


def test_mafia_view_always_and_send_at_night_dead_mafia_view_only():
    for phase, alive in ((C.DAY, VIEW), (C.NOON, VIEW), (C.NIGHT, SEND)):
        p = plan(make_state(phase=phase))
        assert p[MAFIA][6] == alive and p[MAFIA][7] == alive and p[MAFIA][8] == alive, phase
    s = make_state(phase=C.NIGHT)
    s.players[7].alive = False  # D11: dead Mafia keep read-only access to the Lair at all times
    p = plan(s)
    assert p[MAFIA][7] == VIEW and p[GRAVEYARD][7] == SEND and p[TOWN][7] == VIEW


def test_the_prisoner_talks_in_jail_at_night_only_and_loses_the_lair_while_jailed():
    s = make_state(phase=C.NIGHT)
    s.prisoner_slot = 6  # a jailed Godfather
    p = plan(s)
    assert p[JAIL] == {6: SEND} and p[MAFIA][6] == VIEW  # cannot talk to the team
    s2 = make_state(phase=C.DAY)
    s2.prisoner_slot = 6
    assert plan(s2)[JAIL] == {}


def test_a_paused_game_is_read_only_everywhere_including_the_graveyard():
    s = make_state(phase=C.NIGHT)
    s.status = C.PAUSED
    s.prisoner_slot = 3
    s.players[5].alive = False
    p = plan(s)
    assert all(v == VIEW for v in p[TOWN].values()) and all(v == VIEW for v in p[MAFIA].values())
    assert p[JAIL] == {3: VIEW} and p[GRAVEYARD] == {5: VIEW}


def test_post_game_opens_town_for_everyone_and_nothing_else():
    s = make_state(phase=C.PHASE_ENDED)
    s.status = C.ENDED
    p = plan(s)
    assert all(v == SEND for v in p[TOWN].values()) and p[MAFIA] == p[JAIL] == p[GRAVEYARD] == {}


# ------------------------------------------------------------------ dead players (DEAD-2, DEAD-3)
def test_dead_players_cannot_vote_give_verdicts_or_act_except_a_jester_ghost_with_a_haunt():
    s = make_state(phase=C.NOON)
    s.players[3].alive = False
    with pytest.raises(Rejected) as e:
        handle(s, K.Vote(3, 4), 0)
    assert e.value.key == "error.dead"
    n = make_state()
    n.players[4].alive = False
    with pytest.raises(Rejected):
        handle(n, K.SubmitAction(4, "heal", 3), 0)
    n.players[10].alive = False
    n.players[10].state["haunt_available"] = True
    n.players[10].state["haunt_targets"] = [7, 8]  # those who voted guilty
    n.players[10].death = {"phase": C.NOON, "day_or_night": "D1", "causes": [C.LYNCHED]}
    n = handle(n, K.SubmitAction(10, "haunt", 7), 0).state  # the Jester's ghost may still act
    assert n.night_actions[10].target_slot == 7


def test_death_posts_a_graveyard_welcome_that_mentions_the_player_and_pins_the_rules_once():
    s = make_state(phase=C.NOON)
    first = deaths.kill(s, 3, [C.LYNCHED])
    second = deaths.kill(s, 4, [C.LYNCHED])
    m1 = C_.compose(s, first)
    welcome = [m for m in m1 if m.target == "graveyard"]
    assert welcome[0].mentions and f"<@{s.players[3].user_id}>" in welcome[0].content
    assert [m.effect for m in welcome] == [None, "pin"]  # the rules are pinned on the first death
    m2 = [m for m in C_.compose(s, second) if m.target == "graveyard"]
    assert [m.effect for m in m2] == [None]  # never again
    assert all(not m.mentions for m in C_.compose(s, first) if m.target == "town")  # only the welcome pings


# ------------------------------------------------------------------ Skip ahead (PACE-2)
def day(n_alive=10, phase=C.DAY):
    s = make_state(phase=phase)
    for slot in list(s.players)[n_alive:]:
        s.players[slot].alive = False
    return s


@pytest.mark.parametrize("alive,need", [(10, 6), (9, 5), (5, 3), (4, 3), (3, 2)])
def test_skip_needs_a_strict_majority_of_the_living(alive, need):
    assert skip_needed(day(alive)) == need


def test_a_majority_moves_day_to_noon_and_day_one_or_afternoon_to_night_with_reason_skip_early():
    for phase, nxt in ((C.DAY, C.NOON), (C.DAY_1, C.NIGHT), (C.AFTERNOON, C.NIGHT)):
        s = day(5, phase)
        for slot in (1, 2):
            s = handle(s, K.ToggleSkipVote(slot), 0).state
            assert s.phase == phase and len(s.skip_votes) == slot
        r = handle(s, K.ToggleSkipVote(3), 0)
        assert r.state.phase == nxt and r.state.skip_votes == []  # votes clear at every phase change
        changed = next(e for e in r.events if e.type == "PhaseChanged")
        assert changed.payload["reason"] == "skip_early"
        assert C_.compose(r.state, changed)[0].text().startswith(C_.t(r.state, "transition.skip_early"))


def test_pressing_again_takes_the_vote_back_and_progress_is_reported():
    s = day(5)
    s = handle(s, K.ToggleSkipVote(1), 0).state
    r = handle(s, K.ToggleSkipVote(1), 0)
    assert r.state.skip_votes == []
    prog = [e for e in r.events if e.type == "SkipVotesChanged"][0].payload
    assert (prog["count"], prog["needed"]) == (0, 3)
    banner, _ = C_.banner(s, {"phase": C.DAY, "day_number": 2, "night_number": 1, "ends_at": 100, "phase_id": 3})
    assert "Skip ahead: 1/3" in banner


def test_noon_and_trials_can_never_be_skipped_and_the_dead_and_the_setting_are_respected():
    for phase in (C.NOON, C.TRIAL_DEFENSE, C.TRIAL_VERDICT, C.NIGHT):
        with pytest.raises(Rejected) as e:
            handle(day(5, phase), K.ToggleSkipVote(1), 0)
        assert e.value.key == "error.cant_use"
    s = day(5)
    s.players[1].alive = False
    with pytest.raises(Rejected) as e:
        handle(s, K.ToggleSkipVote(1), 0)
    assert e.value.key == "error.dead"
    s = day(5)
    s.settings.early_day = False
    with pytest.raises(Rejected):
        handle(s, K.ToggleSkipVote(1), 0)
    assert C_.banner_view(s, 1) is None and C_.banner_view(day(5), 1)[0] == "skip"


def test_a_death_lowers_the_majority_needed():
    s = day(6)
    s = handle(s, K.ToggleSkipVote(1), 0).state
    s = handle(s, K.ToggleSkipVote(2), 0).state
    s = handle(s, K.ToggleSkipVote(3), 0).state
    assert s.phase == C.DAY and skip_needed(s) == 4
    s.players[6].alive = False
    s.players[5].alive = False  # now 4 alive: 3 votes are a majority
    assert skip_needed(s) == 3


# ------------------------------------------------------------------ early night (PACE-3)
def test_early_night_resolves_only_when_every_prompt_holder_has_confirmed():
    from monke.engine.pacing import prompt_holders
    s = make_state()
    s.settings.early_night = True
    holders = prompt_holders(s)
    for slot in holders[:-1]:
        s = handle(s, K.ConfirmNight(slot), 0).state
        assert s.phase == C.NIGHT  # an unset prompt counts as unconfirmed
    r = handle(s, K.ConfirmNight(holders[-1]), 0)
    assert r.state.phase == C.DAY and any(e.type == "DawnReport" for e in r.events)


def test_early_night_is_off_by_default_and_only_for_prompt_holders():
    s = make_state()
    with pytest.raises(Rejected):
        handle(s, K.ConfirmNight(1), 0)
    s.settings.early_night = True
    with pytest.raises(Rejected):
        handle(s, K.ConfirmNight(1000 if False else 3 if 3 not in __import__("monke.engine.pacing", fromlist=["x"]).prompt_holders(s) else 99), 0)


# ------------------------------------------------------------------ pause (PACE-5)
def test_pause_stores_the_remaining_time_and_resume_gives_it_back():
    s = make_state()
    s.phase_ends_at = 1000.0
    s = handle(s, K.Pause("admin"), 400.0).state
    assert s.status == C.PAUSED and s.admin_pause_remaining == pytest.approx(600.0)
    banner, _ = C_.banner(s, {"phase": C.NIGHT, "day_number": 1, "night_number": 1, "ends_at": 1000, "phase_id": 1})
    assert "Paused" in banner
    s2 = handle(s, K.ShiftDeadline(5000.0), 500.0).state  # a pause never gets compensation
    assert s2.phase_ends_at == s.phase_ends_at
    r = handle(s, K.Resume(), 900.0).state
    assert r.status == C.RUNNING and r.phase_ends_at == pytest.approx(1500.0)


def test_extend_and_compensation_edit_the_banner_in_place():
    s = make_state()
    r = handle(s, K.ShiftDeadline(s.phase_ends_at + 60), 1.0)
    ev = next(e for e in r.events if e.type == "PhaseExtended")
    assert C_.compose(r.state, ev)[0].effect == "banner_edit"


# ------------------------------------------------------------------ AFK (PACE-7)
def run_cycle(s, active=(), now=0.0):
    """One dusk: the given slots were active since the last one."""
    s.active_today = list(active)
    s.phase = C.AFTERNOON
    return handle(s, K.AdvancePhase(s.phase_id, force=True), now)


def test_afk_counts_inactive_days_warns_at_two_and_removes_at_three_with_the_will_shown():
    s = make_state(phase=C.AFTERNOON)
    s.day_number = 2
    s.players[4].will = "I was only napping."
    everyone_but_4 = [x for x in s.players if x != 4]
    r = run_cycle(s, everyone_but_4)
    assert r.state.players[4].inactive_days == 1 and not [e for e in r.events if e.type == "PrivateMessage"]
    s = r.state
    s.day_number = 3
    r = run_cycle(s, everyone_but_4)
    s = r.state
    assert s.players[4].inactive_days == 2
    warn = [e for e in r.events if e.type == "PrivateMessage" and e.audience == "slot:4"]
    assert warn and warn[0].payload["text_key"] == "afk.warning" and warn[0].payload["vars"] == {"count": 2}
    notice = [e for e in r.events if e.audience == "notice"]
    assert notice and notice[0].payload["text_key"] == "afk.admin_warning"  # the admin is told, without any role
    s.day_number = 4
    r = run_cycle(s, everyone_but_4)
    s = r.state
    assert s.players[4].state.get("inactive")  # removed at the next dawn
    s = handle(s, K.AdvancePhase(s.phase_id, force=True), 1.0).state
    assert not s.players[4].alive and s.players[4].death["causes"] == [C.ABANDONED]
    assert s.players[4].death["will"] == "I was only napping."  # normal reveal, will shown


def test_any_activity_resets_the_counter_day_one_is_not_counted_and_zero_disables():
    s = make_state(phase=C.AFTERNOON)
    s.day_number = 1  # Day 1 is not counted
    assert run_cycle(s, []).state.players[4].inactive_days == 0
    s = make_state(phase=C.AFTERNOON)
    s.day_number = 2
    s.players[4].inactive_days = 2
    assert run_cycle(s, [4]).state.players[4].inactive_days == 0  # activity resets
    s = make_state(phase=C.AFTERNOON)
    s.day_number = 2
    s.settings.afk_cycles = 0
    s.players[4].inactive_days = 7
    r = run_cycle(s, [])
    assert not r.state.players[4].state.get("inactive") and not [e for e in r.events if e.audience == "notice"]


def test_votes_verdicts_buttons_and_night_actions_count_as_activity():
    s = make_state(phase=C.NOON)
    s = handle(s, K.Vote(3, 4), 5.0).state
    assert 3 in s.active_today and s.players[3].last_active_at == 5.0
    n = make_state()
    n = handle(n, K.SubmitAction(3, "investigate", 6), 7.0).state
    assert 3 in n.active_today
    d = day(5)
    d = handle(d, K.ToggleSkipVote(2), 1.0).state
    assert 2 in d.active_today
    d = handle(d, K.NoteActivity(4), 2.0).state  # a Town Centre message
    assert 4 in d.active_today and d.active_today.count(4) == 1

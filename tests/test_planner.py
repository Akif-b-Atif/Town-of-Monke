from monke import constants as C
from monke.adapter.planner import GRAVEYARD, JAIL, MAFIA, NONE, SEND, TOWN, VIEW, plan
from monke.adapter.parsing import parse_start
from monke.errors import Rejected
from tests.helpers import make_state

import pytest

MAFIA_SLOTS = {6, 7, 8}


def at(phase, **kw):
    s = make_state(phase=phase)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


@pytest.mark.parametrize("phase", [C.DAY_1, C.DAY, C.NOON, C.AFTERNOON])
def test_day_phases(phase):
    p = plan(at(phase))
    assert all(p[TOWN][s] == SEND for s in range(1, 11))
    assert all(p[MAFIA][s] == VIEW for s in MAFIA_SLOTS) and set(p[MAFIA]) == MAFIA_SLOTS
    assert p[JAIL] == {} and p[GRAVEYARD] == {}


def test_trial_defense_and_verdict():
    s = at(C.TRIAL_DEFENSE, trial={"defendant": 4, "verdicts": {}})
    p = plan(s)
    assert p[TOWN][4] == SEND and all(p[TOWN][x] == VIEW for x in range(1, 11) if x != 4)
    assert all(v == VIEW for v in plan(at(C.TRIAL_VERDICT, trial={"defendant": 4, "verdicts": {}}))[TOWN].values())


def test_night_mafia_talks_prisoner_in_jail_jailor_excluded():
    s = at(C.NIGHT, prisoner_slot=3)
    p = plan(s)
    assert all(v == VIEW for v in p[TOWN].values())
    assert all(p[MAFIA][x] == SEND for x in MAFIA_SLOTS)
    assert p[JAIL] == {3: SEND}
    assert 1 not in p[JAIL]  # the Jailor (slot 1) never has Jail access


def test_jailed_mafia_cannot_talk_in_lair():
    p = plan(at(C.NIGHT, prisoner_slot=7))
    assert p[MAFIA][7] == VIEW and p[MAFIA][6] == SEND


def test_dead_players():
    s = at(C.NOON)
    s.players[3].alive = False   # Town: no lair, no jail
    s.players[7].alive = False   # Mafia keeps view of its own lair
    p = plan(s)
    assert p[TOWN][3] == VIEW and p[GRAVEYARD][3] == SEND and 3 not in p[MAFIA] and 3 not in p[JAIL]
    assert p[MAFIA][7] == VIEW and p[GRAVEYARD][7] == SEND


def test_leak_checklist_non_mafia_never_in_lair():
    for phase in (C.DAY, C.NOON, C.TRIAL_DEFENSE, C.TRIAL_VERDICT, C.AFTERNOON, C.NIGHT):
        s = at(phase, trial={"defendant": 2, "verdicts": {}}, prisoner_slot=4)
        assert set(plan(s)[MAFIA]) <= MAFIA_SLOTS


def test_paused_locks_everything_and_ended_opens_town_only():
    s = at(C.NIGHT, status=C.PAUSED, prisoner_slot=3)
    p = plan(s)
    assert all(v == VIEW for v in p[TOWN].values()) and all(v == VIEW for v in p[MAFIA].values()) and p[JAIL] == {}
    s = at(C.PHASE_ENDED, status=C.ENDED)
    p = plan(s)
    assert all(v == SEND for v in p[TOWN].values()) and p[MAFIA] == p[JAIL] == p[GRAVEYARD] == {}


def test_no_game_hides_everything():
    assert plan(None) == {TOWN: {}, MAFIA: {}, JAIL: {}, GRAVEYARD: {}}


def test_parse_start():
    r = parse_start("monke start <@1> <@!2> <@3>\nJailor\nGodfather, RT\nSerial Killer\nday=5 noon=3 defense=30")
    assert r.user_ids == [1, 2, 3]
    assert r.tokens == ["Jailor", "Godfather", "RT", "Serial Killer"]
    assert r.options == {"day": "5", "noon": "3", "defense": "30"}
    with pytest.raises(Rejected):
        parse_start("monke start\nJailor")
    with pytest.raises(Rejected):
        parse_start("monke start <@9> <@1>", bot_ids={9})

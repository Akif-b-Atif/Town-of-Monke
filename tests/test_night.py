import pytest

from monke import constants as C
from monke.engine import handle
from monke.engine import commands as K
from monke.errors import Rejected
from tests.helpers import dead, make_state, msgs, run_night


def has(texts, fragment):
    return any(fragment in t for t in texts)


def test_mafioso_kills_unprotected_town():
    s, _ = run_night([(7, "kill", 3)])
    assert dead(s) == [3]
    assert s.players[3].death["causes"] == [C.MAFIA_KILL]


def test_doctor_heals_mafia_target():
    s, ev = run_night([(7, "kill", 3), (4, "heal", 3)])
    assert dead(s) == []
    assert has(msgs(ev, 4), "attacked")
    assert has(msgs(ev, 3), "nursed you back")
    assert has(msgs(ev, 7), "healed")


def test_basic_cannot_beat_basic_defense():
    s, ev = run_night([(7, "kill", 9)])  # Mafia vs Serial Killer
    assert dead(s) == [] and has(msgs(ev, 7), "too strong")
    s, _ = run_night([(9, "kill", 6)])  # SK vs Godfather
    assert dead(s) == []


def test_escort_blocks_doctor_and_sheriff():
    s, _ = run_night([(5, "roleblock", 4), (4, "heal", 3), (7, "kill", 3)])
    assert dead(s) == [3]
    s, ev = run_night([(5, "roleblock", 3), (3, "investigate", 9)])
    assert not has(msgs(ev, 3), "Your target, Player")
    assert has(msgs(ev, 3), "roleblocked")


@pytest.mark.parametrize("target", [2, 1])
def test_escort_cannot_block_veteran_or_jailor(target):
    s, ev = run_night([(5, "roleblock", target)])
    assert has(msgs(ev, 5), "cannot be roleblocked")


def test_veteran_alert_shoots_visitors_only():
    acts = [(2, "alert", None), (5, "roleblock", 2), (4, "heal", 2), (3, "investigate", 2),
            (7, "kill", 2), (8, "investigate", 9)]
    s, _ = run_night(acts)
    assert dead(s) == [3, 4, 5, 7]  # all visitors die; vet survives (Basic defense on alert); consigliere safe
    assert s.players[2].alive and s.players[8].alive
    assert s.players[2].state["alerts_left"] == 1


def test_blocked_sk_kills_escort_jailed_sk_kills_jailor():
    s, _ = run_night([(5, "roleblock", 9), (9, "kill", 3)])
    assert dead(s) == [5]
    s, _ = run_night([(9, "kill", 3)], prisoner=9)
    assert dead(s) == [1]


def test_visitors_to_prisoner_fail():
    s, ev = run_night([(4, "heal", 3), (7, "kill", 3), (8, "investigate", 3)], prisoner=3)
    assert dead(s) == []
    assert has(msgs(ev, 4), "in jail") and has(msgs(ev, 7), "in jail") and has(msgs(ev, 8), "in jail")


def test_execution_beats_defense_and_disables_on_town():
    s, _ = run_night([(1, "execute", None)], prisoner=6)  # Godfather has Basic defense
    assert dead(s) == [6] and not s.players[1].state["jailor_exec_disabled"]
    s, _ = run_night([(1, "execute", None)], prisoner=3)  # executing Town
    assert dead(s) == [3] and s.players[1].state["jailor_exec_disabled"]
    s.phase = C.NIGHT
    s.prisoner_slot = 4
    with pytest.raises(Rejected):
        handle(s, K.SubmitAction(1, "execute", None, True), 0)


def test_godfather_mafioso_chain():
    s, _ = run_night([(6, "order", 3), (5, "roleblock", 7)])  # Mafioso blocked: Godfather kills
    assert dead(s) == [3]
    s, _ = run_night([(6, "order", 3), (7, "kill", 4)])  # order overrides Mafioso's own pick
    assert dead(s) == [3]
    s, _ = run_night([(7, "kill", 4)])  # no order: Mafioso picks
    assert dead(s) == [4]
    s, _ = run_night([(6, "order", 3), (7, "kill", 4)], prisoner=6)  # jailed Godfather's order is void
    assert dead(s) == [4]


def test_only_one_mafia_kill_per_night():
    s, _ = run_night([(6, "order", 3), (7, "kill", 4)])
    assert len(dead(s)) == 1


def test_two_attackers_one_death_two_causes():
    s, _ = run_night([(7, "kill", 3), (9, "kill", 3)])
    assert dead(s) == [3]
    assert set(s.players[3].death["causes"]) == {C.MAFIA_KILL, C.SERIAL_KILLER}


def test_doctor_self_heal_once():
    s, _ = run_night([(4, "heal", 4), (9, "kill", 4)])
    assert dead(s) == [] and s.players[4].state["self_heals_left"] == 0
    s.phase = C.NIGHT
    with pytest.raises(Rejected):
        handle(s, K.SubmitAction(4, "heal", 4), 0)


@pytest.mark.parametrize("n,alerts", [(5, 1), (9, 1), (10, 2), (14, 2), (15, 3), (20, 4)])
def test_veteran_alert_count(n, alerts):
    cast = {1: "jailor", 2: "veteran", 3: "godfather"}
    cast.update({i: "sheriff" for i in range(4, n + 1)})
    assert make_state(cast).players[2].state["alerts_left"] == alerts


def test_jailed_veteran_cannot_alert():
    s, _ = run_night([(2, "alert", None)], prisoner=2)
    assert s.players[2].state["alerts_left"] == 2  # not consumed


def test_jester_haunt():
    def lynched(s):
        j = s.players[10]
        j.alive, j.death = False, {"causes": [C.LYNCHED]}
        j.state.update(haunt_available=True, haunt_targets=[3, 4])
    s, _ = run_night([(10, "haunt", 3), (4, "heal", 3)], mutate=lynched)  # ignores heal
    assert not s.players[3].alive and s.players[3].death["causes"] == [C.HAUNTED]
    assert not s.players[10].state["haunt_available"]  # once only
    s0 = make_state()
    lynched(s0)
    with pytest.raises(Rejected):  # 5 did not vote guilty
        handle(s0, K.SubmitAction(10, "haunt", 5), 0)


def test_jester_haunt_ignores_jail():
    def lynched(s):
        j = s.players[10]
        j.alive, j.death = False, {"causes": [C.LYNCHED]}
        j.state.update(haunt_available=True, haunt_targets=[3])
    s, _ = run_night([(10, "haunt", 3)], prisoner=3, mutate=lynched)
    assert not s.players[3].alive


def test_dead_player_cannot_act_and_mafia_cannot_target_mafia():
    s = make_state()
    s.players[3].alive = False
    with pytest.raises(Rejected):
        handle(s, K.SubmitAction(3, "investigate", 9), 0)
    with pytest.raises(Rejected):
        handle(make_state(), K.SubmitAction(7, "kill", 6), 0)


def test_sheriff_and_consigliere_results():
    _, ev = run_night([(3, "investigate", 6), (8, "investigate", 6), (3, "investigate", 9)])
    assert has(msgs(ev, 3), "Player 9, seems Guilty")  # latest action wins
    s, ev = run_night([(3, "investigate", 6), (8, "investigate", 6)])
    assert has(msgs(ev, 3), "seems Innocent")  # Godfather looks innocent
    assert has(msgs(ev, 8), "Godfather")

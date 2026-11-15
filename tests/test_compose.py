"""The composer: dawn layout (QOL-3), vote lines (QOL-4), banner, and error wording (QOL-11)."""
import re

from monke import constants as C
from monke.compose import Composer
from monke.engine import handle
from monke.engine import commands as K
from monke.roles import all_defs
from monke.text.bank import default_bank
from tests.helpers import make_state, run_night

COMP = Composer(default_bank(), fixed=True)
GAMEPLAY_ERRORS = ["error.dead", "error.wrong_phase", "error.vote_wrong_phase", "error.stale_prompt",
                   "error.unknown_target", "error.dead_target", "error.self_target", "error.no_uses",
                   "error.already_pardoned", "error.defendant_cannot_vote", "error.no_prisoner", "error.no_ability",
                   "error.cant_use", "error.no_target_needed", "error.no_verdict", "error.bad_verdict",
                   "error.not_in_game", "error.game_ended", "error.paused", "jailor.exec_disabled", "vet.no_alerts",
                   "doctor.no_self_heal"]


def test_gameplay_errors_never_name_a_role():
    bank = default_bank()
    names = [bank.render(f"role.{d.id}.name", variant=0) for d in all_defs()]
    for key in GAMEPLAY_ERRORS:
        for i in range(bank.count(key)):
            text = bank.render(key, variant=i, causes="Night", time="Night 2", target="x", count=1, needed=1)
            assert not any(re.search(rf"\b{re.escape(n)}\b", text) for n in names), (key, text)


def test_dawn_is_one_message_with_cause_reveal_and_survivors_last():
    s, ev = run_night([(7, "kill", 4)])  # the helper's default game: Mafioso attacks slot 4
    died = [e for e in ev if e.type == "PlayerDied"]
    dawn = [e for e in ev if e.type == "DawnReport"]
    assert len(dawn) == 1 and dawn[0].payload["deaths"] == [d.payload["slot"] for d in died]
    msgs = COMP.compose(s, dawn[0])
    assert len(msgs) == 1
    text = msgs[0].text()
    assert text.startswith(COMP.t(s, "phase.dawn", day=s.day_number))
    assert COMP.t(s, "dawn.survivors", alive=len(s.alive_slots())) in text
    if died:
        slot = died[0].payload["slot"]
        assert COMP.cause_line(s, slot, s.players[slot].death["causes"]) in text
        assert COMP.t(s, f"role.{s.players[slot].role_id}.reveal", player=slot) in text
    # night deaths post nothing else to Town Centre: the report tells everyone
    assert all(m.target != "town" for e in died for m in COMP.compose(s, e))


def test_nobody_died_line():
    s, ev = run_night([])
    dawn = next(e for e in ev if e.type == "DawnReport")
    assert COMP.t(s, "dawn.no_deaths") in COMP.compose(s, dawn)[0].text()


def test_two_attackers_use_the_multiple_causes_line():
    s = make_state()
    s.phase = C.NIGHT
    from monke.engine import deaths
    deaths.kill(s, 4, [C.MAFIA_KILL, C.SERIAL_KILLER], where="dawn")
    line = COMP.cause_line(s, 4, [C.MAFIA_KILL, C.SERIAL_KILLER])
    assert "the Mafia and a Serial Killer" in line


def test_vote_lines_show_count_and_previous():
    s = make_state()
    c = Composer(default_bank(), fixed=True)
    from monke.engine.events import Event
    ev = lambda **p: Event("VoteUpdated", p, "public", 1)
    assert "(2/4)" in c.compose(s, ev(voter=3, target=5, previous=None, count=2, threshold=4))[0].text()
    changed = c.compose(s, ev(voter=3, target=5, previous=2, count=2, threshold=4))[0].text()
    assert c.name(s, 2) in changed and c.name(s, 5) in changed and "(2/4)" in changed
    assert c.name(s, 5) in c.compose(s, ev(voter=3, target=None, previous=5, count=1, threshold=4))[0].text()
    assert c.compose(s, ev(voter=3, target=None, previous=None, count=0, threshold=4)) == []


def test_error_text_words_a_rejection_with_the_next_opportunity():
    s = make_state()
    s.phase = C.NIGHT
    try:
        handle(s, K.Vote(1, 2), 0)
    except Exception as e:
        text = COMP.error(e, s)
        assert "Day" in text and "Noon" in text

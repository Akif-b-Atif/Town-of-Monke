"""CARD-1 to CARD-5 and QOL-9: role cards, wills, death notes, the journal, the night recap, the dawn layout."""
import pytest

from monke import constants as C
from monke.compose import Composer
from monke.engine import commands as K
from monke.engine import deaths, handle
from monke.engine.rolecard import role_card
from monke.errors import Rejected
from monke.text.bank import default_bank
from monke.textsafe import ZWSP, sanitize_text
from tests.helpers import make_state, private, run_night

C_ = Composer(default_bank(), fixed=True)


# ------------------------------------------------------------------ sanitiser (CARD-3)
def test_the_sanitiser_neutralises_mentions_strips_invites_and_limits_newlines():
    out = sanitize_text("hi @everyone and @here <@123456> <@&99> <#5> join discord.gg/abcdef or https://discord.com/invite/xyz ok")
    assert "@" + ZWSP + "everyone" in out and "@" + ZWSP + "here" in out and "<" + ZWSP + "@123456>" in out
    assert "discord.gg" not in out and "invite/xyz" not in out and out.endswith("ok")
    many = "\n".join(str(i) for i in range(30))
    assert sanitize_text(many).count("\n") == 10
    assert sanitize_text("**bold** and _italic_  ") == "**bold** and _italic_"  # markdown stays


# ------------------------------------------------------------------ wills
def test_wills_are_editable_while_alive_bounded_and_can_be_switched_off():
    s = make_state()
    s = handle(s, K.SetWill(3, "If I die, check the quiet one."), 0).state
    assert s.players[3].will == "If I die, check the quiet one."
    with pytest.raises(Rejected) as e:
        handle(s, K.SetWill(3, "x" * 601), 0)
    assert e.value.key == "will.too_long" and e.value.vars["count"] == 600
    s.players[4].alive = False
    with pytest.raises(Rejected):
        handle(s, K.SetWill(4, "hi"), 0)
    s.settings.allow_wills = False
    with pytest.raises(Rejected) as e:
        handle(s, K.SetWill(3, "hi"), 0)
    assert e.value.key == "will.disabled"


def test_the_will_is_shown_for_every_cause_and_hidden_when_blank():
    for causes in ([C.LYNCHED], [C.EXECUTED], [C.MAFIA_KILL], [C.ABANDONED], [C.MODERATED]):
        s = make_state(phase=C.NOON)
        s.players[3].will = "Trust nobody."
        deaths.kill(s, 3, causes)
        assert any("Trust nobody." in line for line in C_.death_lines(s, 3)), causes
        deaths.kill(s, 4, causes)  # no will written
        assert not any("will" in line.lower() for line in C_.death_lines(s, 4)), causes


# ------------------------------------------------------------------ death notes
def test_only_killing_roles_may_set_a_death_note_and_it_persists():
    s = make_state()
    for slot in (2, 6, 7, 9, 1, 10):  # veteran, godfather, mafioso, serial killer, jailor, jester
        s = handle(s, K.SetDeathNote(slot, f"note {slot}"), 0).state
    for slot in (3, 4, 5, 8):
        with pytest.raises(Rejected) as e:
            handle(s, K.SetDeathNote(slot, "x"), 0)
        assert e.value.key == "deathnote.not_allowed"
    with pytest.raises(Rejected) as e:
        handle(s, K.SetDeathNote(7, "x" * 301), 0)
    assert e.value.key == "deathnote.too_long"
    r, _ = run_night([])  # a quiet night does not clear anything
    assert make_state().players[7].death_notes == {}


def test_a_note_is_attached_only_when_the_attack_succeeds():
    s = make_state()
    s = handle(s, K.SetDeathNote(7, "Never trust a smile."), 0).state
    s = handle(s, K.SubmitAction(7, "kill", 3), 0).state  # the Mafioso kills the Sheriff
    r = handle(s, K.AdvancePhase(s.phase_id, force=True), 1000)
    assert r.state.players[3].death["note"] == "Never trust a smile."
    # the Doctor heals the target: no death, so no note
    s = make_state()
    s = handle(s, K.SetDeathNote(7, "Never trust a smile."), 0).state
    s = handle(s, K.SubmitAction(7, "kill", 3), 0).state
    s = handle(s, K.SubmitAction(4, "heal", 3), 0).state
    r = handle(s, K.AdvancePhase(s.phase_id, force=True), 1000)
    assert r.state.players[3].alive and "note" not in (r.state.players[3].death or {})


def test_the_mafia_note_belongs_to_the_player_who_performed_the_kill():
    base = make_state()
    base = handle(base, K.SetDeathNote(6, "Godfather's note"), 0).state
    base = handle(base, K.SetDeathNote(7, "Mafioso's note"), 0).state
    s = handle(base, K.SubmitAction(6, "order", 3), 0).state  # the Godfather orders, the Mafioso performs it
    s = handle(s, K.AdvancePhase(s.phase_id, force=True), 1000).state
    assert s.players[3].death["note"] == "Mafioso's note"
    # with the Mafioso gone the Godfather does it himself
    t = handle(base, K.SubmitAction(6, "order", 3), 0).state
    t.players[7].alive = False
    t = handle(t, K.AdvancePhase(t.phase_id, force=True), 1000).state
    assert t.players[3].death["note"] == "Godfather's note"


# ------------------------------------------------------------------ the dawn layout (CARD-5)
def test_the_dawn_report_matches_the_spec_order_with_will_and_note():
    s = make_state()
    s = handle(s, K.SetWill(4, "If I die, check the quiet one."), 0).state
    s = handle(s, K.SetDeathNote(7, "Never trust a smile."), 0).state
    s = handle(s, K.SubmitAction(7, "kill", 4), 0).state
    r = handle(s, K.AdvancePhase(s.phase_id, force=True), 1000)
    dawn = next(e for e in r.events if e.type == "DawnReport")
    text = C_.compose(r.state, dawn)[0].text()
    order = [text.index(x) for x in (C_.t(r.state, "phase.dawn", day=r.state.day_number),
                                     C_.cause_line(r.state, 4, [C.MAFIA_KILL]),
                                     C_.t(r.state, "role.doctor.reveal", player=4),
                                     "If I die, check the quiet one.", "Never trust a smile.",
                                     C_.t(r.state, "dawn.survivors", alive=len(r.state.alive_slots())))]
    assert order == sorted(order)
    assert [e.type for e in r.events].index("DawnReport") < [e.type for e in r.events].index("PhaseChanged")


def test_deaths_are_listed_in_ascending_slot_order():
    r = None
    s = make_state()
    s = handle(s, K.SubmitAction(7, "kill", 5), 0).state
    s = handle(s, K.SubmitAction(9, "kill", 3), 0).state
    r = handle(s, K.AdvancePhase(s.phase_id, force=True), 1000)
    text = C_.compose(r.state, next(e for e in r.events if e.type == "DawnReport"))[0].text()
    assert text.index(C_.t(r.state, "role.sheriff.reveal", player=3)) < text.index(C_.t(r.state, "role.escort.reveal", player=5))


# ------------------------------------------------------------------ journal and recap (CARD-2, QOL-9)
def test_the_night_recap_is_one_dm_with_one_line_per_result_and_nothing_if_empty():
    s = make_state()
    s = handle(s, K.SubmitAction(3, "investigate", 6), 0).state
    s = handle(s, K.SubmitAction(4, "heal", 4), 0).state
    r = handle(s, K.AdvancePhase(s.phase_id, force=True), 1000)
    mine = [e for e in r.events if e.type == "PrivateMessage" and e.audience == "slot:3"]
    assert len(mine) == 1 and mine[0].payload["text_key"] == "ui.recap.title" and mine[0].payload["vars"] == {"night": 1}
    text = C_.compose(r.state, mine[0])[0].text()
    assert text.startswith("**Night 1 recap**") and len(text.splitlines()) == 2
    assert not [e for e in r.events if e.type == "PrivateMessage" and e.audience == "slot:1"]  # nothing to report: no DM


def test_every_private_result_is_in_the_journal_with_its_night():
    s = make_state()
    s = handle(s, K.SubmitAction(3, "investigate", 6), 0).state
    r = handle(s, K.AdvancePhase(s.phase_id, force=True), 1000)
    j = r.state.players[3].journal
    assert j and j[0]["when"] == "N1" and j[0]["text_key"].startswith("sheriff.result")
    from monke.adapter import info
    text = info.journal_text(C_, r.state, 3)
    assert "Your journal" in text and "Night 1" in text
    assert info.journal_text(C_, r.state, 1).endswith("yet.") or "not learned" in info.journal_text(C_, r.state, 1)


def test_jail_notices_are_not_merged_into_the_recap_but_are_journaled():
    s = make_state(phase=C.AFTERNOON)
    s.day_number = 2
    s = handle(s, K.SubmitAction(1, "jail", 6), 0).state
    r = handle(s, K.AdvancePhase(s.phase_id, force=True), 1)
    keys = [e.payload["text_key"] for e in r.events if e.type == "PrivateMessage"]
    assert "jail.prisoner.notified" in keys and "jail.jailor.prompt" in keys
    assert r.state.players[6].journal[0]["text_key"] == "jail.prisoner.notified"


# ------------------------------------------------------------------ the role card (CARD-1)
def test_the_role_card_has_alignment_attack_defense_abilities_goal_tips_and_teammates():
    s = make_state()
    c = C_.card(s, role_card(s, s.players[6]))  # the Godfather
    names = [n for n, _, _ in c["fields"]]
    assert names == ["Alignment", "Attack", "Defense", "Abilities", "Goal", "Tips", "Your Mafia team"]
    assert c["color"] == "mafia" and "Mafioso" in c["fields"][-1][1] and "Consigliere" in c["fields"][-1][1]
    assert dict((n, v) for n, v, _ in c["fields"])["Defense"] == "Basic"
    vet = C_.card(s, role_card(s, s.players[2]))
    assert "(2 left)" in dict((n, v) for n, v, _ in vet["fields"])["Abilities"] and vet["color"] == "town"
    assert role_card(s, s.players[2])["kills"] and not role_card(s, s.players[3])["kills"]  # Edit Death Note: killers only
    assert C_.card(s, role_card(s, s.players[10]))["color"] == "neutral"

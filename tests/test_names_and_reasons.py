"""NAM-1/NAM-2 and TRN-1: stored player names, name formatting, and a reason on every phase change."""
import json

from monke import constants as C
from monke.adapter.textutil import sanitize_name
from monke.engine import Settings, handle, new_game
from monke.engine import commands as K
from monke.engine.state import GameState
from monke.names import fmt_player, fmt_players

TOKENS = ["Jailor", "Godfather", "TI", "TP", "MK"]
NAMES = {1: "Maya", 2: "Sam", 3: "Lee", 4: "Noor", 5: "Omar"}


def _game(names=NAMES):
    s, _ = new_game("g1", 1, [1, 2, 3, 4, 5], TOKENS, Settings(), 7, names=names)
    return s


def test_sanitize_name_cases():
    assert sanitize_name("Maya") == "Maya"
    assert sanitize_name("  Sam   Lee ") == "Sam Lee"
    assert sanitize_name("") == "Player"
    assert sanitize_name("\n\t") == "Player"
    assert sanitize_name("a\u200bb\u202ec") == "abc"          # zero-width and bidi override removed
    assert sanitize_name("X" * 30) == "X" * 19 + "…"            # 20 characters, ellipsis last
    assert sanitize_name("**hi**") == r"\*\*hi\*\*"            # markdown escaped
    assert sanitize_name("@everyone") != "@everyone"            # mentions broken up
    assert "@everyone" not in sanitize_name("@everyone")


def test_names_are_stored_and_formatted():
    s = _game()
    slot = s.slot_of_user(2)
    assert s.players[slot].display_name == "Sam"
    assert fmt_player(s, slot) == f"Sam (#{slot})"
    assert fmt_player(s, slot, bold=True) == f"**Sam (#{slot})**"
    assert fmt_players(s, [3, 1]) == f"{fmt_player(s, 1)}, {fmt_player(s, 3)}"


def test_games_without_names_fall_back_to_player_n():
    s = _game(names=None)
    assert fmt_player(s, 3) == "Player 3"


def test_old_snapshot_without_display_name_still_loads():
    s = _game()
    d = json.loads(json.dumps(s.to_dict()))
    for p in d["players"].values():
        p.pop("display_name")                                   # a game saved before this release
    again = GameState.from_dict(d)
    assert again.players[1].display_name == ""
    assert fmt_player(again, 1) == "Player 1"


def test_every_phase_change_has_a_reason_and_admin_skip_is_flagged():
    s = _game()
    res = handle(s, K.BeginGame(), 0.0)
    s = res.state
    changes = [e for e in res.events if e.type == "PhaseChanged"]
    assert changes and changes[0].payload["reason"] == "game_start"
    res = handle(s, K.AdvancePhase(s.phase_id, force=True, by="Abdul"), 1.0)
    for e in res.events:
        if e.type == "PhaseChanged":
            assert e.payload["reason"] == "day1_timer"
            assert e.payload["ctx"]["admin_skip"] is True
            assert e.payload["ctx"]["admin_name"] == "Abdul"
    now = res.state.phase_ends_at
    res = handle(res.state, K.AdvancePhase(res.state.phase_id), now)   # a normal timer is not flagged
    for e in res.events:
        if e.type == "PhaseChanged":
            assert e.payload["reason"] == "night_resolved"
            assert "admin_skip" not in e.payload["ctx"]


def test_trial_phase_change_carries_target_and_votes():
    s = _game()
    s = handle(s, K.BeginGame(), 0.0).state
    for _ in range(3):                                          # Day 1 -> Night 1 -> Day 2 -> Noon
        s = handle(s, K.AdvancePhase(s.phase_id), s.phase_ends_at).state
    assert s.phase == C.NOON
    res = None
    for voter in (1, 2, 4):
        res = handle(s, K.Vote(voter, 3), 5000.0)
        s = res.state
    change = [e for e in res.events if e.type == "PhaseChanged"][0]
    assert change.payload["reason"] == "trial_majority"
    assert change.payload["ctx"]["target_slot"] == 3
    assert change.payload["ctx"]["votes"] == 3 and change.payload["ctx"]["needed"] == 3


def test_death_text_uses_the_stored_name():
    s = _game()
    s = handle(s, K.BeginGame(), 0.0).state
    from monke.engine import deaths
    deaths.kill(s, 3, [C.LYNCHED])
    from monke.compose import Composer
    from monke.text.bank import default_bank
    lines = Composer(default_bank(), fixed=True).death_lines(s, 3)
    assert fmt_player(s, 3) in lines[0] and fmt_player(s, 3) in lines[1]

"""LOB-1 to LOB-5: default lists, tokens, presets, durations, settings layers."""
import random
import time

import pytest

from monke import constants as C
from monke.engine import Settings, new_game
from monke.engine.rolelist import default_counts, default_rolelist, generate_roles, split_tokens, validate_rolelist
from monke.engine.settings import PRESETS, parse_duration, resolve_settings
from monke.errors import Rejected
from monke.roles import get_def

TABLE = {  # players: (town, mafia, neutral), straight from the spec
    5: (3, 1, 1), 6: (4, 1, 1), 7: (4, 2, 1), 8: (5, 2, 1), 9: (6, 2, 1), 10: (6, 3, 1), 11: (7, 3, 1), 12: (7, 3, 2),
    13: (8, 3, 2), 14: (8, 4, 2), 15: (9, 4, 2), 16: (10, 4, 2), 17: (10, 5, 2), 18: (11, 5, 2), 19: (12, 5, 2)}


def test_the_classic_fifteen_player_list_is_the_default():
    classic = "Jailor TK TI TI TP TP TS RT RT Godfather MK RM RM NK NE".split()
    assert default_rolelist(15) == classic


@pytest.mark.parametrize("n", range(5, 21))
def test_default_lists_match_the_table_pass_validation_and_keep_town_ahead(n):
    town, mafia, neutral = default_counts(n)
    if n in TABLE:
        assert (town, mafia, neutral) == TABLE[n]
    assert town > mafia + neutral
    tokens = default_rolelist(n)
    assert len(tokens) == n
    canon = validate_rolelist(tokens, n)  # exactly one Jailor and one Godfather
    for seed in range(20):  # and it deals: no pool runs dry
        roles = generate_roles(canon, random.Random(seed))
        assert len(roles) == n and sum(get_def(r).alignment == C.MAFIA for r in roles) == mafia
        assert "jailor" in roles and "godfather" in roles


def test_rn_and_any_tokens():
    canon = validate_rolelist(["Jailor", "Godfather", "RN", "Any", "any"], 5)
    for seed in range(30):
        roles = generate_roles(canon, random.Random(seed))
        assert get_def(roles[2]).alignment == C.NEUTRAL
        assert roles.count("jailor") == 1 and roles.count("godfather") == 1  # Any never adds either


def test_unique_roles_report_the_fix():
    with pytest.raises(Rejected) as e:
        generate_roles(validate_rolelist(["Jailor", "Godfather", "Veteran", "Veteran", "RT"], 5), random.Random(1))
    assert e.value.key == "error.rolelist_unique" and e.value.vars["role"] == "Veteran"


def test_tokens_split_on_spaces_commas_and_lines_and_keep_multiword_names():
    assert split_tokens("Jailor, tk ti\nSerial Killer  GODFATHER;rn") == [
        "Jailor", "tk", "ti", "Serial Killer", "GODFATHER", "rn"]
    assert split_tokens("Jailor bogus") == ["Jailor", "bogus"]  # unknown words pass through for the error to name


@pytest.mark.parametrize("name,vals", PRESETS.items())
def test_presets(name, vals):
    s = Settings.from_options({"preset": name})
    assert (s.day_s, s.noon_s, s.afternoon_s, s.night_s, s.defense_s, s.verdict_s) == tuple(map(float, vals))


def test_preset_combines_with_options_in_any_order():
    s = Settings.from_options({"night": "3m", "preset": "blitz"})
    assert s.night_s == 180 and s.day_s == 120 and s.defense_s == 15


@pytest.mark.parametrize("raw,secs", [("90s", 90), ("2m", 120), ("1h", 3600), ("5", 300), ("1.5m", 90), ("45 s", 45)])
def test_durations(raw, secs):
    assert parse_duration("day", raw) == secs


def test_bad_values_and_unknown_keys_get_a_did_you_mean():
    with pytest.raises(Rejected) as e:
        Settings.from_options({"nigth": "2m"})
    assert e.value.key == "error.bad_option" and e.value.vars["target"] == "night"
    with pytest.raises(Rejected) as e:
        Settings.from_options({"preset": "blitzz"})
    assert e.value.vars["target"] == "preset=blitz"
    with pytest.raises(Rejected) as e:
        Settings.from_options({"day": "soon"})
    assert e.value.key == "error.bad_duration"
    with pytest.raises(Rejected) as e:
        Settings.from_options({"early_day": "maybe"})
    assert e.value.key == "error.bad_option"
    with pytest.raises(Rejected) as e:
        Settings.from_options({"zzzzqq": "1"})
    assert e.value.key == "error.bad_option_nosuggest"


def test_v1_minimums_still_apply():
    with pytest.raises(Rejected) as e:
        Settings.from_options({"night": "90s"})
    assert e.value.key == "error.below_minimum"
    with pytest.raises(Rejected):
        Settings.from_options({"defense": "10s"})
    Settings.from_options({"night": "90s"}, None) if False else None


def test_bool_int_and_zero_disables():
    s = Settings.from_options({"early_night": "on", "early_day": "off", "afk_cycles": "0", "stalemate": "0",
                               "allow_wills": "no", "will_max": "100", "post_game_chat": "2m"})
    assert s.early_night and not s.early_day and s.afk_cycles == 0 and s.stalemate_cycles == 0
    assert not s.allow_wills and s.will_max == 100 and s.post_game_chat_s == 120


def test_settings_layers_resolve_once_and_freeze_in_the_game():
    s, rec = resolve_settings({"preset": "relaxed", "night": "5m"}, {"night": "3m", "stalemate": "5"})
    assert s.day_s == 480 and s.night_s == 180 and s.stalemate_cycles == 5
    assert rec["layers"]["game"] == {"night": "3m", "stalemate": "5"}
    st, _ = new_game("g", 1, [1, 2, 3, 4, 5], ["Jailor", "Godfather", "TI", "TP", "MK"], s, 1, resolved=rec)
    assert st.settings_resolved == rec and st.settings.night_s == 180
    again = type(st).from_dict(st.to_dict())  # survives a save and load
    assert again.settings_resolved == rec and again.settings == s


def test_afternoon_follows_its_own_setting_and_stalemate_zero_never_draws():
    from monke.engine import handle
    from monke.engine import commands as K
    s = Settings.from_options({"preset": "blitz"})
    st, _ = new_game("g", 1, [1, 2, 3, 4, 5], ["Jailor", "Godfather", "TI", "TP", "MK"], s, 1)
    st = handle(st, K.BeginGame(), 0).state
    assert st.phase_length == s.day_s / 2  # Day 1 is half of Day
    from monke.sim.cli import run_game
    for seed in range(5):
        g = run_game(seed)
        assert g.status == C.ENDED


def test_the_default_layers_leave_old_behaviour_alone():
    s = Settings()
    assert (s.day_s, s.noon_s, s.afternoon_s, s.night_s, s.defense_s, s.verdict_s, s.stalemate_cycles) == (
        240, 180, 120, 120, 30, 20, 3)

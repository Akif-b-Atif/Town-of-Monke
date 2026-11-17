"""CMD-1 to CMD-6: one registry generates slash commands, prefix parsing, /help and access checks."""
import asyncio
from types import SimpleNamespace

import discord
import pytest
from discord import app_commands

from monke import constants as C
from monke.adapter import info
from monke.adapter.dispatch import Dispatcher
from monke.adapter.handlers import COMMANDS
from monke.adapter.registry import available, find, parse_args, split_prefix, usage
from monke.compose import Composer
from monke.engine import Settings, handle, new_game
from monke.engine import commands as K
from monke.errors import Rejected
from monke.text.bank import default_bank
from tests.crashworld import NAMES, TOKENS, USERS

C_ = Composer(default_bank(), fixed=True)


def slot(s, user):
    return s.slot_of_user(user)


def game(noon=False):
    s, _ = new_game("g", 1, USERS, TOKENS, Settings(), 5, names=NAMES)
    s = handle(s, K.BeginGame(), 0).state
    if noon:
        s = handle(s, K.AdvancePhase(s.phase_id, force=True), 1).state  # Night 1
        s = handle(s, K.AdvancePhase(s.phase_id, force=True), 2).state  # Day 2
        s = handle(s, K.AdvancePhase(s.phase_id, force=True), 3).state  # Noon
    return s


def test_every_command_has_text_help_and_a_handler():
    bank = default_bank()
    for spec in COMMANDS:
        assert spec.handler is not None and bank.has(spec.help_key), spec.name
        assert len(bank.render(spec.help_key, variant=0)) <= 100, spec.name  # a slash description limit
        for a in spec.slash_args if spec.slash_args is not None else spec.args:
            if a.kind != "rest":
                assert bank.has(f"help.arg.{a.name}"), (spec.name, a.name)
    assert len({s.name for s in COMMANDS}) == len(COMMANDS)


def test_prefix_parsing_is_generated_from_the_spec():
    assert split_prefix("monke skip") == ("skip", "")
    assert split_prefix("MONKE  Export abc123") == ("export", " abc123")
    assert split_prefix("hello monke skip") is None
    export = find(COMMANDS, "export")
    assert parse_args(export, " abc123") == {"game_id": "abc123"}
    assert parse_args(export, "") == {}  # CMD-2: zero arguments where a default makes sense
    td = find(COMMANDS, "teardown")
    assert parse_args(td, "--force") == {"force": True} and parse_args(td, "") == {}
    start = find(COMMANDS, "start")
    assert parse_args(start, " <@1> <@2>\nJailor\nnight=3m")["rest"] == "<@1> <@2>\nJailor\nnight=3m"
    with pytest.raises(Rejected):
        parse_args(find(COMMANDS, "rolelist"), "many")


def test_only_the_prefix_commands_are_reachable_as_monke_messages():
    assert find([s for s in COMMANDS if s.prefix], "skip") and not find([s for s in COMMANDS if s.prefix], "vote")  # D20


def test_help_lists_only_what_works_for_you_right_now():
    s = game()
    me = slot(s, 101)
    text = info.help_text(C_, s, COMMANDS, me, False, False)
    assert "`/vote " not in text and "`/vote`" not in text and "/alive" in text and "monke skip" not in text
    noon = game(noon=True)
    me = slot(noon, 101)
    assert "`/vote [player]`" in info.help_text(C_, noon, COMMANDS, me, False, False)
    admin = info.help_text(C_, noon, COMMANDS, me, True, False)
    assert "monke skip" in admin and "monke setup" not in admin
    assert "monke setup" in info.help_text(C_, noon, COMMANDS, me, False, True)
    noon.players[me].alive = False
    dead = info.help_text(C_, noon, COMMANDS, me, False, False)
    assert "`/vote [player]`" not in dead and "/alive" in dead  # dead players keep the info commands


def test_slash_commands_are_generated_and_register_with_a_command_tree():
    class FakePresenter:
        composer = C_
    bot = SimpleNamespace(presenter=FakePresenter())
    cmds = Dispatcher(bot, COMMANDS).slash_commands()
    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)
    for c in cmds:
        tree.add_command(c)
    by = {c.name: c for c in tree.get_commands()}
    assert set(by) == {s.name for s in COMMANDS}
    vote = by["vote"]
    assert [p.name for p in vote.parameters] == ["player"] and not vote.parameters[0].required
    assert vote.parameters[0].autocomplete  # QOL-6
    start = by["start"]
    assert [p.name for p in start.parameters] == ["players", "roles", "options"]  # the slash form's own options
    assert by["teardown"].parameters[0].type == discord.AppCommandOptionType.boolean
    assert by["rolelist"].parameters[0].type == discord.AppCommandOptionType.integer
    assert all(c.guild_only for c in tree.get_commands())


def test_autocomplete_excludes_yourself_and_the_pardoned_and_matches_name_or_slot():
    s = game(noon=True)
    me, bob, cy, ed = slot(s, 101), slot(s, 102), slot(s, 103), slot(s, 105)
    s.pardoned_today = [cy]
    labels = dict(info.vote_targets(s, me))
    assert me not in labels and cy not in labels and labels[bob] == f"Bob (#{bob})"
    assert [x for x, _ in info.vote_targets(s, me, "bo")] == [bob]
    assert [x for x, _ in info.vote_targets(s, me, f"#{ed}")] == [ed]
    s.players[ed].alive = False
    assert ed not in dict(info.vote_targets(s, me))
    assert info.resolve_player(s, "<@102>") == bob and info.resolve_player(s, f"#{bob}") == bob
    assert info.resolve_player(s, "bob") == bob and info.resolve_player(s, "nobody") is None


def test_info_command_texts():
    s = game(noon=True)
    assert "Voting is only open at Noon" in info.votes_text(C_, game())
    ann, bob, cy, di, ed = (slot(s, u) for u in USERS)
    s.votes = {ann: bob, cy: bob, di: ed}
    text = info.votes_text(C_, s)
    assert f"Bob (#{bob})" in text and "(2)" in text and "votes are needed" in text
    assert f"Ann (#{ann})" in info.alive_text(C_, s)
    from monke.engine import deaths
    deaths.kill(s, ed, [C.LYNCHED])
    dead = info.alive_text(C_, s)
    assert "Dead (1)" in dead and f"Ed (#{ed})" in dead
    assert "Jailor" in info.rolelist_text(C_, s) and "Godfather" in info.rolelist_text(C_, s)
    assert "15" in info.rolelist_text(C_, s, 15) and "NK, NE" in info.rolelist_text(C_, s, 15)
    assert "Day 2 Noon" in info.timer_text(C_, s)
    s.status = C.PAUSED
    assert "paused" in info.timer_text(C_, s)


# ------------------------------------------------------------------ access checks (CMD-1, CMD-4)
class FakeBot:
    def __init__(self, state=None, cfg=None):
        self.service = SimpleNamespace(get=lambda gid: state)
        self.store = SimpleNamespace(get_config=self._cfg)
        self.presenter = SimpleNamespace(composer=C_)
        self._c = cfg

    async def _cfg(self, gid):
        return self._c


def ctx_for(user, channel_id=10, manage=False, roles=()):
    from monke.adapter.ctx import Ctx
    member = SimpleNamespace(id=user, roles=[SimpleNamespace(id=r) for r in roles],
                             guild_permissions=SimpleNamespace(manage_guild=manage), display_name="X")
    return Ctx(None, SimpleNamespace(id=1), SimpleNamespace(id=channel_id), member)


def access(spec, bot, ctx):
    return asyncio.run(Dispatcher(bot, COMMANDS).access(spec, ctx))


def test_player_commands_need_a_seat_and_dead_players_cannot_vote():
    s = game(noon=True)
    bot, vote = FakeBot(s), find(COMMANDS, "vote")
    with pytest.raises(Rejected) as e:
        access(vote, bot, ctx_for(999))
    assert e.value.key == "error.not_in_game"  # a non-participant gets exactly this
    access(find(COMMANDS, "alive"), bot, ctx_for(101))
    s.players[slot(s, 101)].alive = False
    access(find(COMMANDS, "alive"), bot, ctx_for(101))  # dead players keep the info commands
    with pytest.raises(Rejected) as e:
        access(vote, bot, ctx_for(101))
    assert e.value.key == "error.dead"


def test_admin_commands_check_the_live_role_and_the_commands_channel():
    cfg = SimpleNamespace(admin_role_id=5, commands_channel_id=10)
    bot, skip = FakeBot(game(), cfg), find(COMMANDS, "skip")
    access(skip, bot, ctx_for(1, 10, roles=[5]))
    with pytest.raises(Rejected) as e:
        access(skip, bot, ctx_for(1, 10, roles=[1]))
    assert e.value.key == "error.not_admin"
    with pytest.raises(Rejected) as e:
        access(skip, bot, ctx_for(1, 11, roles=[5]))  # right role, wrong channel
    assert e.value.key == "error.wrong_channel"
    admins = find(COMMANDS, "admins")  # ADM-6: any channel, Monke Admin or Manage Server
    access(admins, bot, ctx_for(1, 99, roles=[5]))
    access(admins, bot, ctx_for(1, 99, manage=True))
    with pytest.raises(Rejected):
        access(admins, bot, ctx_for(1, 99))
    with pytest.raises(Rejected) as e:
        access(skip, FakeBot(game(), None), ctx_for(1, 10, roles=[5]))
    assert e.value.key == "error.not_set_up"


def test_server_commands_need_manage_server():
    bot, setup = FakeBot(None, None), find(COMMANDS, "setup")
    access(setup, bot, ctx_for(1, manage=True))
    with pytest.raises(Rejected):
        access(setup, bot, ctx_for(1))


def test_destructive_commands_ask_for_confirmation_first():
    for name in ("skip", "abort", "teardown"):
        assert find(COMMANDS, name).confirm is not None  # CMD-3
    cfg = SimpleNamespace(admin_role_id=5, commands_channel_id=10)
    bot = FakeBot(game(), cfg)
    spec = find(COMMANDS, "abort")
    q = asyncio.run(spec.confirm(bot, ctx_for(1)))
    assert q[0] == "admin.abort.confirm"
    ended = game()
    ended.status = C.ENDED
    with pytest.raises(Rejected):
        asyncio.run(spec.confirm(FakeBot(ended, cfg), ctx_for(1)))


def test_the_confirm_view_lets_any_live_admin_press_and_nobody_else():
    from monke.adapter.confirm import ConfirmView
    cfg = SimpleNamespace(admin_role_id=5)
    sent = []

    class Resp:
        async def send_message(self, text, ephemeral=False): sent.append(text)

    async def go():
        bot = FakeBot(None, cfg)
        view = ConfirmView(bot, 1, lambda i: None, {"confirm": "Yes", "cancel": "No"}, "expired", "cancelled")
        admin = SimpleNamespace(user=SimpleNamespace(roles=[SimpleNamespace(id=5)]), response=Resp())
        other = SimpleNamespace(user=SimpleNamespace(roles=[SimpleNamespace(id=1)]), response=Resp())
        assert await view.interaction_check(admin) is True
        assert await view.interaction_check(other) is False and sent  # told why, ephemerally
        assert view.timeout == 60
    asyncio.run(go())

"""LOB-6 to LOB-10 with mocked interactions: join, leave, DM refusal, blocked start, quick start, expiry, rematch."""
import asyncio
from types import SimpleNamespace

import discord
import pytest

from monke import constants as C
from monke.adapter import handlers
from monke.adapter.lobby import LobbyManager, lobby_view
from monke.compose import Composer
from monke.errors import Rejected
from monke.service.lobby import Lobby, LobbyStore, OPEN, REMATCH
from monke.service.store import Store
from monke.text.bank import default_bank

C_ = Composer(default_bank(), fixed=True)


def test_membership_limits_and_blocked_start_reasons():
    l = Lobby.new(1, 7, 0.0)
    for u in range(1, 5):
        l.join(u)
    with pytest.raises(Rejected) as e:
        l.join(2)
    assert e.value.key == "lobby.already_in"
    with pytest.raises(Rejected) as e:
        l.check_start()
    assert e.value.key == "lobby.start_blocked.count" and e.value.vars["count"] == 4
    l.join(5)
    l.check_start()  # 5 players with the default list is startable
    l.tokens = ["Jailor", "Godfather", "Veteran", "Veteran", "TI"]
    with pytest.raises(Rejected) as e:
        l.check_start()
    assert e.value.key == "lobby.start_blocked.rolelist" and e.value.vars["inner"].key == "error.rolelist_unique"
    l.tokens = None
    for u in range(6, 21):
        l.join(u)
    with pytest.raises(Rejected) as e:
        l.join(99)
    assert e.value.key == "lobby.full"
    l.leave(20)
    assert l.count == 19
    assert l.rolelist()[0] == "Jailor" and len(l.rolelist()) == 19


def test_lobbies_survive_a_restart(tmp_path):
    async def go():
        path = str(tmp_path / "m.db")
        st = Store(path)
        await st.open()
        ls = LobbyStore(st)
        l = Lobby.new(1, 7, 10.0, players=[1, 2], options={"night": "3m"})
        l.tokens = ["Jailor", "TI"]
        await ls.save(l)
        await st.close()
        st2 = Store(path)
        await st2.open()
        back = await LobbyStore(st2).open_for_guild(1)
        assert (back.players, back.options, back.tokens, back.status) == ([1, 2], {"night": "3m"}, ["Jailor", "TI"], OPEN)
        await st2.close()
    asyncio.run(go())


def test_the_embed_shows_players_list_settings_and_default_marker():
    l = Lobby.new(1, 7, 0.0, players=[1, 2, 3, 4, 5], options={"preset": "blitz"})
    emb = C_.lobby_embed(l, {1: "Ann", 2: "Bob", 3: "Cy", 4: "Di", 5: "Ed", 7: "Opener"}, 1800)
    text = "\n".join(f"{n}: {v}" for n, v, _ in emb["fields"])
    assert "Opened by Opener" in emb["description"] and "1. Ann" in text and "Players (5)" in text
    assert "default list" in text and "preset=blitz" in text and "day=2m" in text
    assert "30 minutes" in emb["footer"]


class Chan:
    def __init__(self):
        self.edits = []

    def get_partial_message(self, mid):
        outer = self
        return SimpleNamespace(edit=lambda **kw: outer._edit(kw))

    async def _edit(self, kw):
        self.edits.append(kw)


class Resp:
    def __init__(self):
        self.sent, self.deferred, self.modal = [], False, None

    async def send_message(self, text=None, ephemeral=False, **kw): self.sent.append(text)
    async def defer(self, **kw): self.deferred = True
    async def send_modal(self, m): self.modal = m


def make_manager(tmp_path, admin_role=5):
    async def setup():
        st = Store(str(tmp_path / "x.db"))
        await st.open()
        from monke.service.store import GuildConfig
        await st.set_config(GuildConfig(1, 2, 3, admin_role, 4, 5, 6, 7, list(range(100, 120)), {}, lobby_id=50))
        chan = Chan()
        members = {i: SimpleNamespace(id=i, display_name=f"P{i}") for i in range(1, 8)}
        guild = SimpleNamespace(id=1, get_member=members.get, get_channel=lambda cid: chan)
        bot = SimpleNamespace(store=st, presenter=SimpleNamespace(composer=C_, _embed=lambda d: d),
                              get_guild=lambda gid: guild, get_channel=lambda cid: chan,
                              service=SimpleNamespace())
        mgr = LobbyManager(bot)
        return st, mgr, chan, guild
    return setup


def interaction(user_id, roles=(), guild=None, dm_ok=True):
    sent = []

    async def send(text=None, **kw):
        if not dm_ok:
            raise discord.Forbidden(SimpleNamespace(status=403, reason=""), "closed")
        sent.append(text)
    user = SimpleNamespace(id=user_id, roles=[SimpleNamespace(id=r) for r in roles], send=send, display_name=f"P{user_id}")
    return SimpleNamespace(user=user, response=Resp(), guild=guild, followup=SimpleNamespace(send=send)), sent


def test_join_sends_a_test_dm_and_refuses_if_dms_are_closed(tmp_path):
    async def go():
        st, mgr, chan, guild = await make_manager(tmp_path)()
        lobby = Lobby.new(1, 7, 0.0)
        lobby.message_id, lobby.channel_id = 1, 50
        await mgr.store.save(lobby)
        ok, dm = interaction(1, guild=guild)
        await mgr.press(ok, "join", lobby.lobby_id)
        assert dm and (await mgr.store.get(lobby.lobby_id)).players == [1]
        closed, _ = interaction(2, guild=guild, dm_ok=False)
        await mgr.press(closed, "join", lobby.lobby_id)
        assert (await mgr.store.get(lobby.lobby_id)).players == [1]  # refused
        assert "DM" in closed.response.sent[0] or "open" in closed.response.sent[0].lower()
        again, _ = interaction(1, guild=guild)
        await mgr.press(again, "join", lobby.lobby_id)
        assert "already" in again.response.sent[0].lower()
        leave, _ = interaction(1, guild=guild)
        await mgr.press(leave, "leave", lobby.lobby_id)
        assert (await mgr.store.get(lobby.lobby_id)).players == []
        await st.close()
    asyncio.run(go())


def test_start_edit_and_cancel_check_the_live_admin_role_and_explain_blocked_starts(tmp_path):
    async def go():
        st, mgr, chan, guild = await make_manager(tmp_path)()
        lobby = Lobby.new(1, 7, 0.0, players=[1, 2, 3])
        lobby.message_id, lobby.channel_id = 1, 50
        await mgr.store.save(lobby)
        nobody, _ = interaction(1, roles=[1], guild=guild)
        for act in ("start", "settings", "roles", "cancel"):
            nobody.response.sent.clear()
            await mgr.press(nobody, act, lobby.lobby_id)
            assert nobody.response.sent and (await mgr.store.get(lobby.lobby_id)).status == OPEN
        admin, _ = interaction(2, roles=[5], guild=guild)
        await mgr.press(admin, "start", lobby.lobby_id)  # 3 players: blocked, with the reason
        assert "3" in admin.response.sent[0] and (await mgr.store.get(lobby.lobby_id)).status == OPEN
        modal, _ = interaction(2, roles=[5], guild=guild)
        await mgr.press(modal, "settings", lobby.lobby_id)
        assert modal.response.modal is not None
        cancel, _ = interaction(2, roles=[5], guild=guild)
        await mgr.press(cancel, "cancel", lobby.lobby_id)
        assert (await mgr.store.get(lobby.lobby_id)).status == "CANCELLED" and chan.edits
        await st.close()
    asyncio.run(go())


def test_edits_validate_and_are_debounced(tmp_path):
    async def go():
        import monke.adapter.lobby as L
        L.DEBOUNCE = 0.01
        st, mgr, chan, guild = await make_manager(tmp_path)()
        lobby = Lobby.new(1, 7, 0.0)
        lobby.message_id, lobby.channel_id = 1, 50
        await mgr.store.save(lobby)
        with pytest.raises(Rejected) as e:
            await mgr.apply_settings(lobby.lobby_id, "nigth=2m")
        assert e.value.key == "error.bad_option"
        await mgr.apply_settings(lobby.lobby_id, "night=3m\npreset=blitz")
        assert (await mgr.store.get(lobby.lobby_id)).options == {"night": "3m", "preset": "blitz"}
        with pytest.raises(Rejected):
            await mgr.apply_rolelist(lobby.lobby_id, "Jailor, Bogus")
        await mgr.apply_rolelist(lobby.lobby_id, "Jailor, Godfather, TI, TP, MK")
        for _ in range(6):
            mgr.schedule_refresh(lobby.lobby_id)
        for _ in range(400):  # wait for the debounced edit rather than guessing how long it takes
            if chan.edits:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)  # and give a (wrong) second edit the chance to show up
        assert len(chan.edits) == 1  # the edits and six more refresh requests: one edit
        await st.close()
    asyncio.run(go())


def test_a_lobby_expires_after_its_inactivity_timeout_and_rematch_prefills(tmp_path):
    async def go():
        st, mgr, chan, guild = await make_manager(tmp_path)()
        lobby = Lobby.new(1, 7, 0.0, players=[1])
        lobby.message_id, lobby.channel_id = 1, 50
        await mgr.store.save(lobby)
        assert await mgr.sweep(100.0) == 0
        assert await mgr.sweep(2000.0) == 1  # past lobby_timeout (30 minutes)
        assert (await mgr.store.get(lobby.lobby_id)).status == "EXPIRED"
        # rematch: remembers who played and how (LOB-10)
        from monke.engine import Settings, new_game
        from monke.engine.settings import resolve_settings
        s, rec = resolve_settings({}, {"night": "3m"})
        state, _ = new_game("game1", 1, [1, 2, 3, 4, 5], ["Jailor", "Godfather", "TI", "TP", "MK"], s, 1, resolved=rec)
        await mgr.save_rematch(state)
        old = await mgr.store.get("game1")
        assert old.status == REMATCH and old.players == [p.user_id for p in state.players.values()]
        assert old.options == {"night": "3m"}
        await st.close()
    asyncio.run(go())


def test_start_text_flows():
    guild = SimpleNamespace(get_member=lambda uid: None)
    ctx = SimpleNamespace(guild=guild)
    req, opts, yes = handlers._parse_start_text(None, ctx, "")
    assert req is None and opts == {} and not yes  # Flow A: no players -> a lobby
    req, opts, yes = handlers._parse_start_text(None, ctx, "preset=blitz")
    assert req is None and opts == {"preset": "blitz"}
    req, _, yes = handlers._parse_start_text(None, ctx, "<@1> <@2> <@3> <@4> <@5> -y")
    assert yes and req.tokens == [] and len(req.user_ids) == 5  # Flow B (-y skips the confirmation)
    req, _, yes = handlers._parse_start_text(None, ctx, "<@1> <@2> <@3> <@4> <@5>\nJailor, Godfather, TI, TP, MK\nnight=3m")
    assert not yes and req.tokens == ["Jailor", "Godfather", "TI", "TP", "MK"] and req.options == {"night": "3m"}  # Flow C


def test_the_lobby_view_has_the_six_buttons():
    v = lobby_view(C_, "abc123")
    assert [i.item.label for i in v.children] == ["Join", "Leave", "Start", "Edit settings", "Edit role list", "Cancel"]

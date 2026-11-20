"""M17: replace, modkill, extend, settings, diagnose, the game-over embed, the recap and the replay tool."""
import asyncio
import json
import random
from types import SimpleNamespace

import pytest

from monke import constants as C
from monke.adapter import diagnose
from monke.compose import Composer
from monke.engine import Settings, handle, new_game
from monke.engine import commands as K
from monke.errors import Rejected
from monke.sim.cli import _play
from monke.sim.replay import replay
from monke.text.bank import default_bank
from tests.crashworld import NAMES, TOKENS, USERS, Clock, Proc, World, new_path
from tests.helpers import make_state

C_ = Composer(default_bank(), fixed=True)


# ------------------------------------------------------------------ extend (ADM2-3)
def test_extend_adds_time_to_the_phase_and_its_length_and_edits_the_banner():
    s = make_state()
    s.phase_ends_at, s.phase_length = 1000.0, 120.0
    r = handle(s, K.Extend(120), 10.0)
    assert r.state.phase_ends_at == 1120.0 and r.state.phase_length == 240.0
    ev = next(e for e in r.events if e.type == "PhaseExtended")
    assert C_.compose(r.state, ev)[0].effect == "banner_edit"
    with pytest.raises(Rejected):
        handle(s, K.Extend(0), 0)
    s.status = C.PAUSED
    s.admin_pause_remaining = 50.0
    assert handle(s, K.Extend(60), 0).state.admin_pause_remaining == 110.0  # a pause keeps its clock stopped


# ------------------------------------------------------------------ modkill (ADM2-2)
def test_modkill_by_day_is_immediate_and_the_role_is_revealed():
    s = make_state(phase=C.NOON)
    s.votes = {3: 4, 4: 5, 6: 4}
    r = handle(s, K.ModKill(4, "rule 3"), 0)
    died = [e for e in r.events if e.type == "PlayerDied"]
    assert died and died[0].payload["causes"] == [C.MODERATED] and died[0].payload["where"] == "day"
    assert 4 not in r.state.votes and 4 not in r.state.votes.values()  # their votes and votes on them are gone
    text = C_.compose(r.state, died[0])[0].text()
    assert "an admin" in text.lower() or "removed" in text.lower() or "moderat" in text.lower()
    assert C_.t(r.state, "role.doctor.reveal", player=4) in text


def test_modkill_at_night_is_queued_and_announced_at_dawn():
    s = make_state()
    r = handle(s, K.ModKill(3), 0)
    assert r.state.players[3].alive and r.state.modkill_queue == [3] and not r.events
    dawn = handle(r.state, K.AdvancePhase(r.state.phase_id, force=True), 1000)
    assert not dawn.state.players[3].alive and dawn.state.players[3].death["causes"] == [C.MODERATED]
    report = next(e for e in dawn.events if e.type == "DawnReport")
    assert 3 in report.payload["deaths"] and dawn.state.modkill_queue == []


def test_modkill_of_the_defendant_cancels_the_trial_and_can_end_the_game():
    s = make_state(phase=C.NOON)
    s.trial = {"defendant": 4, "verdicts": {}}
    s.phase = C.TRIAL_DEFENSE
    s.paused_remaining = 90.0
    r = handle(s, K.ModKill(4), 0)
    assert r.state.phase == C.NOON and r.state.trial is None
    with pytest.raises(Rejected):
        handle(r.state, K.ModKill(4), 0)  # already dead
    t = make_state(phase=C.NOON)
    for slot in (6, 7, 8, 9):  # remove every Mafia and the Serial Killer: Town wins
        t = handle(t, K.ModKill(slot), 0).state
    assert t.status == C.ENDED and t.winning_faction == "TOWN"


# ------------------------------------------------------------------ replace (ADM2-1)
def test_replace_keeps_state_and_journal_and_records_the_former_player():
    s = make_state()
    s.players[3].journal.append({"when": "N1", "text_key": "sheriff.result.guilty", "vars": {"target": 9}})
    s.players[3].will = "mine"
    s.players[3].display_name = "Old"
    r = handle(s, K.Replace(3, 4242, "Newcomer"), 0)
    p = r.state.players[3]
    assert (p.user_id, p.display_name, p.role_id) == (4242, "Newcomer", "sheriff")
    assert p.journal == s.players[3].journal and p.will == "mine"  # carried over unchanged
    assert p.former == [{"user_id": s.players[3].user_id, "name": "Old", "day": s.day_number, "night": s.night_number}]
    ann = [e for e in r.events if e.type == "Announcement"][0]
    text = C_.compose(r.state, ann)[0].text()
    assert "#3" in text and "Old" in text and "Newcomer" in text
    assert not any(role in text for role in ("Sheriff", "Doctor", "Jailor"))  # reveals nothing else
    assert any(e.type == "PromptRequested" and e.audience == "slot:3" for e in r.events)  # open prompts follow
    with pytest.raises(Rejected):
        handle(r.state, K.Replace(4, 4242, "x"), 0)  # the new person is already playing


def test_replace_sends_the_new_player_a_card_a_journal_and_the_banner():
    s = make_state()
    r = handle(s, K.Replace(3, 4242, "Newcomer"), 0)
    rep = next(e for e in r.events if e.type == "PlayerReplaced")
    msgs = C_.compose(r.state, rep)
    assert msgs[0].effect == "replace_roles" and msgs[0].meta == {"old": s.players[3].user_id, "new": 4242}
    assert all(m.target == "slot:3" for m in msgs)
    assert msgs[2].embed["title"].startswith("You are the")  # the role card
    assert "journal" in msgs[3].content.lower() or "learned" in msgs[3].content.lower()


# ------------------------------------------------------------------ settings and diagnose (ADM2-4, ADM2-5)
def test_diagnose_flags_each_seeded_misconfiguration_with_a_fix():
    perms = SimpleNamespace(manage_roles=True, manage_channels=True, manage_messages=True, view_channel=True,
                            send_messages=True, embed_links=True, attach_files=False, read_message_history=True,
                            use_application_commands=True)
    assert diagnose.missing_permissions(perms) == ["attach_files"]  # FIX-2: Attach Files is checked

    async def go():
        class R:
            def __init__(self, pos, perm=0):
                self.position, self.name, self.permissions = pos, "r", SimpleNamespace(value=perm)
        role = lambda pos, perm=0: R(pos, perm)
        me_perms = SimpleNamespace(**{n: True for n in diagnose.NEEDED})
        slot_roles = [role(1) for _ in range(20)]
        guild = SimpleNamespace(
            id=1, me=SimpleNamespace(guild_permissions=me_perms, top_role=role(5)),
            get_role=lambda i: ({100: role(9)} | {200 + k: r for k, r in enumerate(slot_roles)}).get(i),
            get_channel=lambda cid: None if cid == 7 else SimpleNamespace(
                overwrites_for=lambda r: SimpleNamespace(view_channel=True, send_messages=True), overwrites={}),
            default_role=object())
        cfg = SimpleNamespace(admin_role_id=100, slot_role_ids=[200 + k for k in range(20)], town_id=1, mafia_id=2,
                              jail_id=3, graveyard_id=7, commands_channel_id=5, lobby_id=6)
        assert await diagnose.check_hierarchy(None, guild, cfg) == (False, "r")  # Monke Admin sits above the bot
        ok, detail = await diagnose.check_channels(None, guild, cfg)
        assert not ok and detail == "graveyard"
        ok, detail = await diagnose.check_overwrites(None, guild, cfg)
        assert not ok and "everyone can see it" in detail and "plan is not applied" in detail
        assert (await diagnose.check_slot_roles(None, guild, cfg))[0]
        slot_roles[3] = role(1, perm=8)  # a slot role with a permission
        assert not (await diagnose.check_slot_roles(None, guild, cfg))[0]
        assert not (await diagnose.check_intents(SimpleNamespace(intents=SimpleNamespace(members=True, message_content=False)),
                                                 guild, cfg))[0]
    asyncio.run(go())
    c = Composer(default_bank(), fixed=True)
    emb = diagnose.render(c, [("channels", False, "graveyard"), ("backups", True, ""), ("debug", True, "")], True)
    assert "Fix:" in emb["description"] and "graveyard" in emb["description"] and "debug mode: ON" in emb["description"]
    assert diagnose.REPAIRABLE == ("channels", "overwrites", "slot_roles")


# ------------------------------------------------------------------ game over and the recap (POST-1, POST-2)
def play_out(seed=3, n=9):
    rng = random.Random(seed)
    s, _ = new_game("g", 1, list(range(1, n + 1)), ["Jailor", "Godfather", "Mafioso", "TI", "TP", "TK", "TS", "RT", "NK"][:n],
                    Settings(), seed, names={i: f"P{i}" for i in range(1, n + 1)})
    events, now = [], 0.0
    res = handle(s, K.BeginGame(), now)
    s, events = res.state, list(res.events)
    guard = 0
    while s.status == C.RUNNING and guard < 400:
        before = len(events)
        s = _play(s, rng, now)
        now = s.phase_ends_at
        res = handle(s, K.AdvancePhase(s.phase_id), now)
        s, events = res.state, events + list(res.events)
        guard += 1
    return s, events


def test_the_game_over_embed_lists_every_player_with_name_role_and_fate_in_town_and_lobby():
    s, events = play_out()
    over = next(e for e in events if e.type == "GameEnded")
    msgs = C_.compose(s, over)
    assert [m.target for m in msgs] == ["town", "lobby"]
    for m in msgs:
        for slot, p in s.players.items():
            assert f"P{slot}" in m.embed["description"] or f"(#{slot})" in m.embed["description"]
    assert "survived" in msgs[0].embed["description"] or any(not p.alive for p in s.players.values())
    assert msgs[1].view[0] == "rematch" and msgs[1].view[1] == s.game_id  # LOB-10: Play again
    text = msgs[0].embed["description"]
    for p in s.players.values():
        assert C_.role_name(p.role_id) in text  # the final role of every player


def test_the_recap_is_built_from_the_event_log_alone():
    s, events = play_out(seed=5)
    stored = [{"type": e.type, "payload": json.loads(json.dumps(e.payload)), "audience": e.audience} for e in events]
    entries = C_.recap(s, stored)
    kinds = [k for k, _ in entries]
    assert kinds[0] == "header" and "day" in kinds and "night" in kinds
    assert ("death" in kinds) or ("lynch" in kinds)
    text = "\n".join(t for _, t in entries)
    assert "Day 1" in text and "Night 1" in text
    short = [k for k in kinds if k in ("header", "lynch", "execute", "death")]
    assert short and len(short) <= len(kinds)


# ------------------------------------------------------------------ the replay tool (POST-4)
def service_game_data():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await a.svc.start_game(1, USERS, TOKENS, Settings(), seed=11, names=NAMES)
        from monke.engine.pacing import prompt_holders
        for _ in range(60):
            g = a.svc.get(1)
            if g.status != C.RUNNING:
                break
            if g.phase == C.NIGHT:
                for slot in prompt_holders(g):
                    opts = [t for t in g.alive_slots() if t != slot]
                    ability = next(iter(__import__("monke.engine.phases", fromlist=["x"]).prompts_for(g, slot))).ability_id
                    try:
                        await a.svc.submit(1, K.SubmitAction(slot, ability, opts[0] if ability != "alert" else None))
                    except Rejected:
                        pass
            clock.advance(7)
            await a.svc.submit(1, K.AdvancePhase(g.phase_id, force=True))
        game_id = s.game_id
        events = await a.store.load_events(game_id)
        commands = await a.store.load_commands(game_id)
        data = {"game_id": game_id, "seed": 11, "events": events, "commands": commands}
        for t in list(a.svc._bg):
            t.cancel()
        a.svc.scheduler.cancel(game_id)
        return data
    return json.loads(json.dumps(asyncio.run(go())))


def test_the_replay_tool_reproduces_a_game_played_through_the_real_service():
    data = service_game_data()
    assert any(e["type"] == "GameCreated" for e in data["events"]) and len(data["commands"]) > 3
    assert replay(data) is None  # identical, event for event


def test_the_replay_tool_names_the_first_divergence():
    data = service_game_data()
    i = next(k for k, e in enumerate(data["events"]) if e["type"] == "PhaseChanged")
    data["events"][i]["payload"]["ends_at"] += 1  # corrupt one stored event
    problem = replay(data)
    assert problem and "first divergence at event" in problem and "PhaseChanged" in problem
    old = {"events": [{"type": "RoleAssigned", "payload": {}, "audience": "slot:1"}], "commands": []}
    assert "cannot be replayed" in replay(old)
    data = service_game_data()
    data["commands"][-1]["type"] = "ModKill"  # a command the game never accepted
    data["commands"][-1]["payload"] = {"slot": 99}
    assert "rejected in the replay" in replay(data)

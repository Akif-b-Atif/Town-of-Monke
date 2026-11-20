"""REL-18: the failure matrix. One test per row F1 to F15, built on a fake Discord that outlives the 'process'."""
import asyncio
import json
import time

import pytest

from monke import constants as C
from monke.engine import Settings
from monke.engine import commands as K
from monke.errors import Rejected
from monke.service.crash import SimulatedCrash
from monke.service.instance import AlreadyRunning, InstanceGuard
from tests.crashworld import NAMES, TOKENS, USERS, Clock, Proc, World, new_path

GUILD = 1


def arm_next(proc, name):
    proc.svc.crash.arm(name, proc.svc.crash.counts[name] + 1)


async def start(proc):
    return await proc.svc.start_game(GUILD, USERS, TOKENS, Settings(), seed=5, names=NAMES)


def run(coro):
    return asyncio.run(coro)


async def settle(n=30):
    for _ in range(n):
        await asyncio.sleep(0)
        await asyncio.sleep(0.001)


async def until(cond, timeout=10.0):
    """Wait for a condition instead of a fixed number of event-loop turns: robust on a slow or busy machine."""
    waited = 0.0
    while not cond():
        await asyncio.sleep(0.005)
        waited += 0.005
        assert waited < timeout, "timed out waiting for the condition"


def dupes(world):
    texts = [p[2] for p in world.posts if p[0] == "post"]
    return sorted({t for t in texts if texts.count(t) > 1})


def test_f1_killed_during_a_phase_time_is_given_back():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        clock.advance(30)
        heartbeat = clock()
        ends_before, pid = s.phase_ends_at, s.phase_id
        await a.die()
        clock.advance(600)  # ten minutes offline: far past the phase's end
        b = Proc(a.path, world, clock)
        await b.boot(last_heartbeat=heartbeat)
        g = b.svc.get(GUILD)
        assert g.phase_id == pid and g.status == C.RUNNING  # no cascade, no phase change
        assert g.phase_ends_at == pytest.approx(clock() + (ends_before - heartbeat))  # exactly what was left
        cmds = await b.store.load_commands(g.game_id)
        assert any(c["type"] == "ShiftDeadline" for c in cmds)  # it is in the command log and the archive
        b.svc.scheduler.cancel(g.game_id)
    run(go())


def test_f2_killed_after_commit_before_discord_posts_the_missed_messages_once():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        before = len(world.posts)
        arm_next(a, "after_commit_before_render")
        with pytest.raises(SimulatedCrash):
            await a.svc.submit(GUILD, K.AdvancePhase(s.phase_id, force=True))
        assert len(world.posts) == before  # nothing reached Discord
        await a.die()
        b = await Proc(a.path, world, clock).boot(last_heartbeat=clock())
        banners = [p for p in world.posts if p[2].startswith("banner NIGHT")]
        assert len(banners) == 1 and not dupes(world)
        # and a second recovery changes nothing (REL-5)
        n = len(world.posts)
        await b.svc.recover(last_heartbeat=clock())
        assert len(world.posts) == n
        b.svc.scheduler.cancel(b.svc.get(GUILD).game_id)
    run(go())


@pytest.mark.parametrize("k", [1, 2, 3])
def test_f3_killed_halfway_through_a_transition_the_rest_is_posted_nothing_repeats(k):
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        a.svc.crash.arm("mid_render", a.svc.crash.counts["mid_render"] + k)
        with pytest.raises(SimulatedCrash):
            await a.svc.submit(GUILD, K.AdvancePhase(s.phase_id, force=True))
        posted = len(world.posts)
        await a.die()
        b = await Proc(a.path, world, clock).boot(last_heartbeat=clock())
        assert len(world.posts) > posted  # the rest arrived
        assert not dupes(world)
        assert any(p[2].startswith("prompt") for p in world.posts)
        b.svc.scheduler.cancel(b.svc.get(GUILD).game_id)
    run(go())


def test_f4_killed_while_starting_the_game_is_cancelled_and_roles_removed():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        a.svc.crash.arm("starting_after_roles")
        with pytest.raises(SimulatedCrash):
            await start(a)
        assert world.slot_roles  # roles were already handed out
        await a.die()
        b = await Proc(a.path, world, clock).boot()
        assert not world.slot_roles and b.svc.get(GUILD) is None
        assert "rel.starting_cancelled" in world.notices
        async with b.store.db.execute("SELECT COUNT(*) FROM games") as cur:
            assert (await cur.fetchone())[0] == 0
    run(go())


@pytest.mark.parametrize("point", ["archive_locked", "archive_built", "archive_uploaded", "after_purge_before_cleanup"])
def test_f5_killed_at_any_archive_step_it_resumes_never_uploads_twice_never_deletes_early(point):
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot(archive=True)
        s = await start(a)
        a.svc.crash.arm(point)
        await a.svc.submit(GUILD, K.Abort())
        await settle()
        if point != "after_purge_before_cleanup":
            assert world.purged == 0  # nothing deleted before a verified upload
        assert world.uploads <= 1
        await a.die()
        b = await Proc(a.path, world, clock).boot(archive=True, last_heartbeat=clock())
        await settle(60)
        job = await b.store.get_job(s.game_id)
        assert job["state"] == "PURGED"
        assert world.uploads == 1  # never uploaded twice
        assert world.purged >= 1 and world.separators == 1
    run(go())


def test_f6_killed_while_paused_it_stays_paused_and_gets_no_compensation():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        clock.advance(20)
        await a.svc.submit(GUILD, K.Pause("test"))
        remaining = a.svc.get(GUILD).admin_pause_remaining
        await a.die()
        clock.advance(3600)
        b = await Proc(a.path, world, clock).boot(last_heartbeat=clock() - 3600)
        g = b.svc.get(GUILD)
        assert g.status == C.PAUSED and g.admin_pause_remaining == remaining
        assert not any(c["type"] == "ShiftDeadline" for c in await b.store.load_commands(g.game_id))
    run(go())


def test_f7_offline_for_hours_the_phase_is_frozen_for_the_whole_gap():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        hb = clock()
        await a.die()
        clock.advance(5 * 3600)
        b = await Proc(a.path, world, clock).boot(last_heartbeat=hb)
        g = b.svc.get(GUILD)
        assert (g.phase, g.phase_id) == (s.phase, s.phase_id)
        assert g.phase_ends_at == pytest.approx(clock() + s.phase_length)
        b.svc.scheduler.cancel(g.game_id)
    run(go())


def test_f7b_compensation_has_a_floor_of_a_minute():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        clock.advance(s.phase_length - 5)  # 5 seconds were left
        hb = clock()
        await a.die()
        clock.advance(900)
        b = await Proc(a.path, world, clock).boot(last_heartbeat=hb)
        assert b.svc.get(GUILD).phase_ends_at == pytest.approx(clock() + 60)  # at least a minute to act
        b.svc.scheduler.cancel(s.game_id)
    run(go())


def test_f9_two_copies_the_second_refuses_to_start():
    async def go():
        clock = Clock()
        a = Proc(new_path(), World(), clock)
        await a.boot(recover=False)
        g1 = InstanceGuard(a.store, clock, pid=111, host="h", alive=lambda p: True)
        await g1.start()
        g2 = InstanceGuard(a.store, clock, pid=222, host="h", alive=lambda p: True)
        with pytest.raises(AlreadyRunning):
            await g2.start()
        await g2.start(force=True)  # --force-takeover
        # a copy that did not exit cleanly but is gone (pid dead) does not block a restart
        g3 = InstanceGuard(a.store, clock, pid=333, host="h", alive=lambda p: False)
        await g3.start()
        # a stale heartbeat (over 20 s) does not block either
        g4 = InstanceGuard(a.store, clock, pid=444, host="h", alive=lambda p: True)
        clock.advance(25)
        await g4.start()
        # and a clean exit never blocks
        await g4.heartbeat()
        await g4.stop()
        g5 = InstanceGuard(a.store, clock, pid=555, host="h", alive=lambda p: True)
        await g5.start()
        assert g5.last_heartbeat_before is not None
    run(go())


def test_f10_one_damaged_game_is_set_aside_and_the_others_keep_working():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        await a.store.db.execute(
            "INSERT INTO games(game_id,guild_id,status,phase_id,snapshot_json,schema_version,updated_at) "
            "VALUES('bad1',2,'RUNNING',1,'{not json',2,0)")
        newer = json.dumps({**s.to_dict(), "schema_version": 99, "game_id": "new1", "guild_id": 3})
        await a.store.db.execute(
            "INSERT INTO games(game_id,guild_id,status,phase_id,snapshot_json,schema_version,updated_at) "
            "VALUES('new1',3,'RUNNING',1,?,99,0)", (newer,))
        await a.store.db.commit()
        await a.die()
        b = await Proc(a.path, world, clock).boot(last_heartbeat=clock())
        assert b.svc.get(GUILD).status == C.RUNNING  # the healthy game carried on
        async with b.store.db.execute("SELECT game_id,status,snapshot_json FROM games WHERE game_id IN ('bad1','new1') "
                                      "ORDER BY game_id") as cur:
            rows = await cur.fetchall()
        assert [r[1] for r in rows] == ["QUARANTINED", "QUARANTINED"]
        assert rows[0][2] == "{not json" and json.loads(rows[1][2])["schema_version"] == 99  # data untouched
        assert world.notices.count("rel.quarantined") == 2
        b.svc.scheduler.cancel(s.game_id)
    run(go())


def test_f11_discord_down_events_are_retried_in_order_and_the_admin_is_told():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        world.fail_next = 10 ** 9
        await a.svc.submit(GUILD, K.AdvancePhase(s.phase_id, force=True))  # does not raise: it is retried
        await until(lambda: "rel.render_failed" in world.notices)  # after 10 failures
        assert "rel.render_failed" in world.notices
        assert not [p for p in world.posts if p[2].startswith("banner NIGHT")]
        world.fail_next = 0
        await until(lambda: any(p[2].startswith("banner NIGHT") for p in world.posts))
        await until(lambda: not a.svc._retrying)
        banners = [p for p in world.posts if p[2].startswith("banner")]
        assert [b[2] for b in banners][-1].startswith("banner NIGHT") and not dupes(world)
        assert await a.store.rendered_seq(s.game_id) == await a.store.max_event_seq(s.game_id)
        a.svc.scheduler.cancel(s.game_id)
    run(go())


def test_f11b_a_deleted_channel_pauses_the_game_with_a_message_and_creates_nothing():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        await a.die()
        world.missing = ["town"]
        b = await Proc(a.path, world, clock).boot(last_heartbeat=clock())
        assert b.svc.get(GUILD).status == C.PAUSED and "rel.structures_missing" in world.notices
    run(go())


def test_f12_players_who_left_are_removed_and_chat_is_recovered():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot(archive=True)
        s = await start(a)
        slot = s.slot_of_user(104)
        await a.die()
        world.members.discard(104)
        world.history["town"] = [{"ts_ms": 5, "kind": "msg", "message_id": 777, "author_user_id": 102,
                                  "author_name": "Bob", "content": "said while offline", "attachments": []}]
        b = await Proc(a.path, world, clock).boot(archive=True, last_heartbeat=clock())
        assert b.svc.get(GUILD).players[slot].state.get("inactive") and "rel.players_left" in world.notices
        rows = await b.store.load_chat(s.game_id)
        rec = [r for r in rows if r["message_id"] == 777]
        assert len(rec) == 1 and rec[0]["backfilled"] and rec[0]["author_slot"] == s.slot_of_user(102)
        await b.svc.recover(last_heartbeat=clock())  # idempotent: no second copy
        assert len([r for r in await b.store.load_chat(s.game_id) if r["message_id"] == 777]) == 1
        b.svc.scheduler.cancel(s.game_id)
    run(go())


def test_f12b_jail_gap_is_reported_when_there_is_a_prisoner():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot(archive=True)
        s = await start(a)
        g = a.svc.get(GUILD)
        g.prisoner_slot = 2
        await a.store.save_game(g)
        await a.die()
        world.history["jail"] = [{"ts_ms": 9, "kind": "msg", "message_id": 55, "author_user_id": 102,
                                  "author_name": "Bob", "content": "I am innocent", "attachments": []}]
        b = await Proc(a.path, world, clock).boot(archive=True, last_heartbeat=clock())
        assert ("jail_gap", s.game_id, "1") in world.posts
        b.svc.scheduler.cancel(s.game_id)
    run(go())


def test_f13_clean_shutdown_stops_commands_and_the_next_start_behaves_like_f1():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        await a.svc.shutdown()
        assert any(p[2] == "rel.shutdown_notice" for p in world.posts)
        with pytest.raises(Rejected) as e:
            await a.svc.submit(GUILD, K.AdvancePhase(s.phase_id, force=True))
        assert e.value.key == "error.shutting_down"
        hb = clock()
        await a.die()
        clock.advance(60)
        b = await Proc(a.path, world, clock).boot(last_heartbeat=hb)
        assert b.svc.get(GUILD).phase_id == s.phase_id
        b.svc.scheduler.cancel(s.game_id)
    run(go())


def test_f14_a_failing_background_task_is_reported_and_the_bot_keeps_running():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        seen = []
        a.svc.on_error = lambda exc, gid: seen.append(exc)

        async def boom():
            raise RuntimeError("boom")
        a.svc._spawn(boom())
        await settle()
        assert seen and isinstance(seen[0], RuntimeError)
        await a.svc.submit(GUILD, K.Pause("still alive"))  # the service still works
        assert a.svc.get(GUILD).status == C.PAUSED
    run(go())


def test_f15_a_suspended_machine_is_treated_as_downtime_without_a_restart(monkeypatch):
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await start(a)
        guard = InstanceGuard(a.store, clock, pid=1, host="h", alive=lambda p: True)
        await guard.start()
        await a.svc.heartbeat_tick(guard)
        clock.advance(10)
        await a.svc.heartbeat_tick(guard)  # a normal tick: nothing shifts
        assert a.svc.get(GUILD).phase_ends_at == s.phase_ends_at
        hb = clock()
        remaining = a.svc.get(GUILD).phase_ends_at - hb
        clock.advance(7200)  # the laptop slept for two hours
        await a.svc.heartbeat_tick(guard)
        assert a.svc.get(GUILD).phase_ends_at == pytest.approx(clock() + remaining)
        a.svc.scheduler.cancel(s.game_id)
    run(go())


def test_f15b_the_scheduler_rechecks_the_clock_in_short_slices(monkeypatch):
    from monke.service import scheduler as sched

    async def go():
        monkeypatch.setattr(sched, "SLICE", 0.01)
        clock, fired = Clock(), []

        async def on_fire(gid, pid):
            fired.append(pid)
        sc = sched.Scheduler(on_fire, clock)
        sc.arm("g", clock() + 10_000, 7)
        await asyncio.sleep(0.05)
        assert not fired
        clock.advance(20_000)  # the clock jumped: the phase must not hang
        await asyncio.sleep(0.1)
        assert fired == [7]
    run(go())


def test_f8_a_missing_database_in_a_server_that_is_already_set_up_refuses_to_run():
    from monke.service.guards import looks_like_wrong_folder
    assert looks_like_wrong_folder(False, True, False)
    assert not looks_like_wrong_folder(False, True, True)  # --new-db
    assert not looks_like_wrong_folder(True, True, False)
    assert not looks_like_wrong_folder(False, False, False)  # a first-ever start

    async def go():
        from monke.service.store import Store
        p = new_path()
        s = Store("./" + __import__("os").path.relpath(p))  # a relative spelling of the same file
        assert s.path == __import__("os").path.abspath(p)
        await s.open()
        assert not s.existed_before
        await s.close()
        s2 = Store(p)
        await s2.open()
        assert s2.existed_before
        await s2.close()
    run(go())


def test_f7c_with_compensation_off_an_overdue_phase_simply_fires_at_start():
    async def go():
        clock, world = Clock(), World()
        a = await Proc(new_path(), world, clock).boot()
        s = await a.svc.start_game(GUILD, USERS, TOKENS, Settings(downtime_compensation=False), seed=5, names=NAMES)
        hb = clock()
        await a.die()
        clock.advance(3600)
        b = await Proc(a.path, world, clock).boot(last_heartbeat=hb)
        assert not any(c["type"] == "ShiftDeadline" for c in await b.store.load_commands(s.game_id))
        assert b.svc.get(GUILD).phase_ends_at == s.phase_ends_at  # still overdue: the timer fires at once
        b.svc.scheduler.cancel(s.game_id)
    run(go())

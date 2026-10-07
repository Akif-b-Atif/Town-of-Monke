import asyncio

import pytest

from monke import constants as C
from monke.engine import Settings
from monke.engine import commands as K
from monke.errors import Rejected
from monke.service.game_service import GameService, StartAborted
from monke.service.store import Store

TOKENS = ["Jailor", "Godfather", "TI", "TP", "MK"]
USERS = [11, 12, 13, 14, 15]


class FakePresenter:
    def __init__(self, fail_dm=()):
        self.fail_dm, self.rendered, self.perms, self.roles_removed, self.admin = list(fail_dm), [], [], 0, []

    async def assign_slot_roles(self, state): pass
    async def remove_slot_roles(self, state): self.roles_removed += 1
    async def send_role_dms(self, state, events): return list(self.fail_dm)
    async def apply_permissions(self, state, force=False): self.perms.append((state.phase, state.status))
    async def render(self, state, events): self.rendered.extend(e.type for e in events)
    async def reconcile(self, state): pass
    async def cleanup(self, state): pass
    async def notify_admin(self, guild_id, text): self.admin.append(text)


def with_store(tmp_path, fn):
    """Always closes the aiosqlite connection (its thread would otherwise block interpreter exit)."""
    async def go():
        store = Store(str(tmp_path / "m.db"))
        await store.open()
        try:
            await asyncio.wait_for(fn(store), 20)
        finally:
            await store.close()
    asyncio.run(go())


def test_start_persist_advance_and_recover(tmp_path):
    async def body(store):
        pres = FakePresenter()
        svc = GameService(store, pres)
        st = await svc.start_game(1, USERS, TOKENS, Settings(), seed=5)
        assert st.status == C.RUNNING and st.phase == C.DAY_1
        assert "RosterPosted" in pres.rendered
        with pytest.raises(Rejected):
            await svc.start_game(1, USERS, TOKENS, Settings())  # one game per server
        st = await svc.submit(1, K.AdvancePhase(st.phase_id, force=True))
        assert st.phase == C.NIGHT
        svc.scheduler.cancel(st.game_id)
        svc2 = GameService(store, FakePresenter())  # "restart"
        await svc2.recover()
        assert svc2.get(1) == st
        svc2.scheduler.cancel(st.game_id)
    with_store(tmp_path, body)


def test_dm_failure_aborts_start(tmp_path):
    async def body(store):
        pres = FakePresenter(fail_dm=[13])
        svc = GameService(store, pres)
        with pytest.raises(StartAborted) as e:
            await svc.start_game(1, USERS, TOKENS, Settings(), seed=5)
        assert e.value.failed_user_ids == [13]
        assert pres.roles_removed == 1 and svc.get(1) is None
        assert await store.load_games((C.STARTING, C.RUNNING)) == []
    with_store(tmp_path, body)


def test_engine_exception_fails_closed(tmp_path, monkeypatch):
    async def body(store):
        pres = FakePresenter()
        svc = GameService(store, pres)
        await svc.start_game(1, USERS, TOKENS, Settings(), seed=5)
        import monke.service.game_service as gs
        real = gs.handle
        monkeypatch.setattr(gs, "handle", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(Rejected):
            await svc.submit(1, K.AdvancePhase(1, force=True))
        monkeypatch.setattr(gs, "handle", real)
        assert svc.get(1).status == C.PAUSED
        assert pres.admin and "paused" in pres.admin[-1]
        await svc.submit(1, K.Resume())
        assert svc.get(1).status == C.RUNNING
        svc.scheduler.cancel(svc.get(1).game_id)
    with_store(tmp_path, body)


def test_timer_fires_advance(tmp_path):
    async def body(store):
        svc = GameService(store, FakePresenter())
        st = await svc.start_game(1, USERS, TOKENS,
                                  Settings(day_s=0.2, noon_s=0.2, afternoon_s=0.2, night_s=0.2), seed=3, strict=False)
        await asyncio.sleep(0.7)
        assert svc.get(1).phase_id > st.phase_id
        await svc.submit(1, K.Abort())
    with_store(tmp_path, body)

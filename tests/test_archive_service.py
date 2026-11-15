"""ARC-3/4/6/9/10/12/13/15: recording, the fail-closed end sequence, retry, resume, prune, teardown guard.
Real Store (in memory), real GameService and ArchiveService; only the Discord side is faked."""
import asyncio
import io
import time
import zipfile

from monke import constants as C
from monke.engine import Settings
from monke.engine import commands as K
from monke.errors import Rejected
from monke.service.archive import ArchiveService
from monke.service.capture import ChatCapture
from monke.service.game_service import GameService
from monke.service.store import Store

PLAYERS = [1, 2, 3, 4, 5]
TOKENS = ["Jailor", "Godfather", "TI", "TP", "MK"]
NAMES = {1: "Maya", 2: "Sam", 3: "Lee", 4: "Noor", 5: "Omar"}


class FakePresenter:
    def __init__(self):
        self.calls, self.notices, self.fail_upload, self.uploads = [], [], False, []
        self.existing_ids = set()

    # --- the v1 presenter surface
    async def assign_slot_roles(self, state): pass
    async def remove_slot_roles(self, state): pass
    async def send_role_dms(self, state, events): return []
    async def apply_permissions(self, state, force=False, archiving=False): pass
    async def render(self, state, events): pass
    async def reconcile(self, state): pass
    async def cleanup(self, state): self.calls.append("cleanup")
    async def notify_admin(self, guild_id, text): self.notices.append(text)

    # --- the archive surface
    async def lock_for_archive(self, state): self.calls.append("lock")
    def filesize_limit(self, guild_id): return 8 * 1024 * 1024

    async def upload_archive(self, state, summary, zips):
        if self.fail_upload:
            raise RuntimeError("discord is down")
        self.calls.append("upload")
        self.uploads.append(zips)
        ids = [1000 + len(self.uploads)]
        self.existing_ids.update(ids)
        return ids, ["sha"] * len(zips)

    async def archive_messages_exist(self, guild_id, ids): return all(i in self.existing_ids for i in ids)
    async def purge_game_channels(self, guild_id): self.calls.append("purge")
    async def send_separators(self, state, summary): self.calls.append("separators")


async def _world():
    store = Store(":memory:")
    await store.open()
    pres = FakePresenter()
    cap = ChatCapture(store)
    arch = ArchiveService(store, pres, cap)
    svc = GameService(store, pres, post_game_seconds=0, archive=arch)
    return store, pres, cap, arch, svc


async def _play_to_end(svc):
    await svc.start_game(1, PLAYERS, TOKENS, Settings(), seed=5, names=NAMES, invoker_user_id=1)
    try:
        await svc.submit(1, K.Vote(1, 2))              # not noon: rejected, but still logged (ARC-4)
    except Rejected:
        pass
    while svc.get(1) is not None and svc.get(1).status == C.RUNNING:
        s = svc.get(1)
        await svc.submit(1, K.AdvancePhase(s.phase_id, force=True))
    return svc.get(1)


async def _settle(svc):
    await asyncio.gather(*list(svc._bg))


def test_end_sequence_uploads_before_purging_and_cleans_up():
    async def go():
        store, pres, cap, arch, svc = await _world()
        s = await _play_to_end(svc)
        gid = s.game_id
        cap.put({"game_id": gid, "ts_ms": int(time.time() * 1000), "channel_kind": "town", "session": "",
                 "kind": "msg", "message_id": 77, "author_user_id": 1, "author_slot": s.slot_of_user(1),
                 "author_name": "Maya", "content": "hello from the town"})
        await _settle(svc)
        job = await store.get_job(gid)
        return store, pres, svc, gid, job

    store, pres, svc, gid, job = asyncio.run(go())
    assert job["state"] == "PURGED" and job["zip_message_ids"]
    assert pres.calls == ["lock", "upload", "purge", "separators", "cleanup"]      # ARC-9 order
    assert svc.get(1) is None
    with zipfile.ZipFile(io.BytesIO(pres.uploads[0][0][1])) as z:
        assert "hello from the town" in z.read("chat/town.txt").decode()
        assert "timeline.txt" in z.namelist()


def test_commands_and_admin_actions_are_recorded():
    async def go():
        store, pres, cap, arch, svc = await _world()
        s = await _play_to_end(svc)
        await _settle(svc)
        return await store.load_commands(s.game_id), await store.load_events(s.game_id)

    commands, events = asyncio.run(go())
    assert any(not c["accepted"] and c["type"] == "Vote" for c in commands)
    assert any(c["type"] == "AdvancePhase" and c["payload"]["force"] for c in commands)
    assert all("by" not in c["payload"] for c in commands)                          # slots, not names
    types = {e["type"] for e in events}
    assert {"NightTrace", "AdminAction", "PhaseChanged"} <= types
    assert next(e for e in events if e["type"] == "AdminAction")["payload"]["command"] == "start"


def test_failed_upload_never_purges_and_export_retries():
    async def go():
        store, pres, cap, arch, svc = await _world()
        pres.fail_upload = True
        s = await _play_to_end(svc)
        await _settle(svc)
        failed = (await store.get_job(s.game_id))["state"], list(pres.calls), list(pres.notices), svc.get(1)
        pres.fail_upload = False
        msg = await svc.export(1)
        return failed, msg, (await store.get_job(s.game_id))["state"], list(pres.calls), svc.get(1)

    (state, calls, notices, game), msg, final, calls2, game2 = asyncio.run(go())
    assert state == "FAILED" and "purge" not in calls                                # fail closed (ARC-10)
    assert any("Chats were NOT deleted" in n for n in notices)
    assert game is not None                                                         # kept so export can retry
    assert final == "PURGED" and calls2.index("upload") < calls2.index("purge") and "cleared" in msg
    assert game2 is None


def test_resume_does_not_upload_twice():                                            # ARC-10
    async def go():
        store, pres, cap, arch, svc = await _world()
        s = await _play_to_end(svc)
        await _settle(svc)                                                          # the job is PURGED now
        # pretend the bot crashed right after the upload: the job says UPLOADED and the zip message still exists
        await store.save_job(s.game_id, "UPLOADED", zip_message_ids=[1001], sha256=["x"])
        pres.existing_ids.add(1001)
        pres.calls.clear()
        return await arch.run(s), list(pres.calls)

    ok, calls = asyncio.run(go())
    assert ok and "upload" not in calls and "purge" in calls


def test_export_refuses_a_running_game():                                           # ARC-12
    async def go():
        store, pres, cap, arch, svc = await _world()
        await svc.start_game(1, PLAYERS, TOKENS, Settings(), seed=5, names=NAMES)
        try:
            await svc.export(1)
        except Rejected as r:
            return r.reason

    assert asyncio.run(go()) == "Archives are only available after the game ends."


def test_next_game_waits_for_the_archive():
    async def go():
        store, pres, cap, arch, svc = await _world()
        svc.post_game_seconds = 3600                                                # still in the post-game window
        s = await _play_to_end(svc)
        try:
            await svc.start_game(1, PLAYERS, TOKENS, Settings(), seed=6, names=NAMES)
        except Rejected as r:
            return r.reason

    assert "still being archived" in asyncio.run(go())


def test_prune_only_touches_purged_games():                                         # ARC-13
    async def go():
        store, pres, cap, arch, svc = await _world()
        s = await _play_to_end(svc)
        await _settle(svc)
        row = {"ts_ms": 1, "channel_kind": "town", "kind": "msg", "content": "old"}
        await store.add_chat_rows([{**row, "game_id": s.game_id}, {**row, "game_id": "other-game"}])
        await store.prune_chat(int(time.time() * 1000))
        return await store.load_chat(s.game_id), await store.load_chat("other-game")

    purged_chat, other_chat = asyncio.run(go())
    assert purged_chat == [] and len(other_chat) == 1


def test_teardown_guard_sees_unfinished_archives():                                 # ARC-15
    async def go():
        store, pres, cap, arch, svc = await _world()
        pres.fail_upload = True
        await _play_to_end(svc)
        await _settle(svc)
        return await store.pending_archive_games(1)

    assert len(asyncio.run(go())) == 1

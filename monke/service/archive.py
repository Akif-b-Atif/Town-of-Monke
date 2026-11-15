"""ArchiveService: the end-of-game sequence (ARC-9, ARC-10, ARC-12).

Fail-closed: nothing is deleted before the zip is uploaded AND verified. Every step is recorded in
`archive_jobs`, so a restart resumes from the recorded state and never uploads the same zip twice."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from ..adapter import strings as S
from ..debug import NullSink
from ..archive.builder import archive_summary, build_archive
from ..archive.zipper import write_zips
from ..errors import Rejected

from .. import __version__ as BOT_VERSION

log = logging.getLogger("monke.archive")


class ArchiveService:
    def __init__(self, store, presenter, capture, clock=time.time, bot_version: str = BOT_VERSION,
                 retention_days: int = 7, sink=None):
        self.sink = sink or NullSink()
        self.store, self.presenter, self.capture, self.clock = store, presenter, capture, clock
        self.bot_version, self.retention_days = bot_version, retention_days
        self._locks: dict = {}

    def _lock(self, game_id: str) -> asyncio.Lock:
        return self._locks.setdefault(game_id, asyncio.Lock())

    def _stamp(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y%m%d-%H%M")

    async def _build(self, state):
        """Build the zip(s) from what is stored. Safe to repeat: the builder is deterministic."""
        gid = state.game_id
        events = await self.store.load_events(gid)
        commands = await self.store.load_commands(gid)
        chat = await self.store.load_chat(gid)
        meta = {"bot_version": self.bot_version}
        files = build_archive(state, events, commands, chat, meta)
        limit = self.presenter.filesize_limit(state.guild_id)
        zips = write_zips(files, f"monke-game-{gid}-{self._stamp()}", limit)
        return archive_summary(state, events), zips

    async def _notify(self, guild_id: int, text: str) -> None:
        try:
            await self.presenter.notify_admin(guild_id, text)
        except Exception:
            log.exception("could not notify the admin")

    async def run(self, state) -> bool:
        """Lock, build, upload, verify, purge, separators, cleanup. True once the game is PURGED."""
        gid, guild = state.game_id, state.guild_id
        async with self._lock(gid):
            job = await self.store.get_job(gid)
            if job and job["state"] == "PURGED":
                return True
            await self.store.save_job(gid, job["state"] if job else "PENDING",
                                      attempts=(job["attempts"] if job else 0) + 1)
            try:
                # 1. lock: nothing may be written between the build and the wipe
                self.sink.note("ARCHIVE", "locking channels", state)
                await self.presenter.lock_for_archive(state)
                self.capture.close(gid)
                await self.capture.flush()
                await self.store.save_job(gid, "LOCKED")
                # 2. build
                self.sink.note("ARCHIVE", "building the zip", state)
                summary, zips = await self._build(state)
                await self.store.save_job(gid, "BUILT")
                # 3. upload (skipped if a verified upload from an earlier attempt still exists)
                self.sink.note("ARCHIVE", "uploading", state)
                ids = job["zip_message_ids"] if job else []
                if ids and await self.presenter.archive_messages_exist(guild, ids):
                    await self.store.save_job(gid, "UPLOADED")
                else:
                    ids, hashes = await self.presenter.upload_archive(state, summary, zips)
                    await self.store.save_job(gid, "UPLOADED", zip_message_ids=ids, sha256=hashes)
            except Exception as exc:
                log.exception("archive failed before a verified upload (game %s); nothing was deleted", gid)
                await self.store.save_job(gid, "FAILED", error=repr(exc)[:500])
                await self._notify(guild, S.ARCHIVE_FAILED)
                return False
            # 4. purge: only ever reached after a verified upload
            self.sink.note("ARCHIVE", "purging game channels", state)
            try:
                await self.presenter.purge_game_channels(guild)
            except Exception as exc:
                log.exception("purge failed (game %s); the archive is safe in Monke Commands", gid)
                await self.store.save_job(gid, "FAILED", error=repr(exc)[:500])
                await self._notify(guild, S.ARCHIVE_PURGE_FAILED)
                return False
            # 5. separators, 6. cleanup: best effort
            try:
                await self.presenter.send_separators(state, summary)
            except Exception:
                log.exception("separators failed")
            try:
                await self.presenter.cleanup(state)
            except Exception:
                log.exception("cleanup failed")
            self.sink.note("ARCHIVE", "done: channels purged, game cleaned up", state)
            await self.store.save_job(gid, "PURGED")
            await self.store.mark_cleaned(gid)
            return True

    async def export_only(self, guild_id: int, game_id: str) -> None:
        """ARC-12: rebuild and post the zip for a finished game without touching any channel."""
        state = await self.store.load_game(game_id)
        if state is None or state.guild_id != guild_id:
            raise Rejected("I have no game with that id.")
        job = await self.store.get_job(game_id)
        if job and job["state"] == "PURGED" and self.clock() - (job["updated_at"] or 0) > self.retention_days * 86400:
            raise Rejected(f"That game is older than the {self.retention_days}-day retention window.")
        try:
            summary, zips = await self._build(state)
        except AssertionError:
            raise Rejected(S.EXPORT_LIVE_REFUSED)
        await self.presenter.upload_archive(state, summary, zips)

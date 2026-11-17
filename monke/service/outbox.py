"""Exactly-once effects and ordered output (REL-7, REL-17)."""
from __future__ import annotations

import asyncio
import itertools
from typing import Awaitable, Callable, Optional


class Retryable(Exception):
    """A Discord failure worth retrying later (HTTP 5xx, 429, a timeout). The event stays unrendered."""


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, Retryable):
        return True
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    try:
        import discord
        if isinstance(exc, discord.HTTPException):
            return exc.status == 429 or exc.status >= 500
        if isinstance(exc, (discord.ConnectionClosed, discord.GatewayNotFound)):
            return True
    except ImportError:  # pragma: no cover
        pass
    try:
        import aiohttp
        if isinstance(exc, aiohttp.ClientError):
            return True
    except ImportError:  # pragma: no cover
        pass
    return False


def _message_id(res) -> int:
    first = res[0] if isinstance(res, (list, tuple)) and res else res
    return int(getattr(first, "id", 0) or 0)


class OutboxCtx:
    """Passed to the presenter while it renders ONE event. Every message the event sends goes through `once`,
    which skips a (part, target) already recorded (a replay after a crash) and records it right after the send.
    A crash between a send and its row may post one duplicate; that is accepted (REL-7)."""

    def __init__(self, store, game_id: str, seq: int, done: dict, crash=None):
        self.store, self.game_id, self.seq, self.done, self.crash = store, game_id, seq, done, crash
        self.part = 0

    async def once(self, target: str, send: Callable[[], Awaitable]):
        part, self.part = self.part, self.part + 1
        if (part, target) in self.done:
            return None
        res = await send()
        if self.crash is not None:
            self.crash.hit("after_send_before_outbox")
        await self.store.outbox_add(self.game_id, self.seq, part, target, _message_id(res))
        if self.crash is not None:
            self.crash.hit("mid_render")
        return res


class GuildWriter:
    """All Discord writes for one guild go through one worker (REL-17).

    P0 permissions, P1 phase and death announcements, P2 DMs (at most 5 in flight), P3 cosmetic edits (coalesced:
    the latest edit with the same key wins). A lower number always runs first, so the permissions of a transition
    are in place before its announcement. 429 back-off is discord.py's own, per route."""
    P0, P1, P2, P3 = 0, 1, 2, 3

    def __init__(self, dm_concurrency: int = 5):
        self._q: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._n = itertools.count()
        self._worker: Optional[asyncio.Task] = None
        self._latest: dict = {}
        self._dm_slots = asyncio.Semaphore(dm_concurrency)
        self.max_dm_in_flight = 0
        self._dm_in_flight = 0

    async def run(self, priority: int, fn: Callable[[], Awaitable], key=None):
        fut = asyncio.get_running_loop().create_future()
        n = next(self._n)
        if priority == self.P3 and key is not None:
            self._latest[key] = n
        self._q.put_nowait((priority, n, key, fn, fut))
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._drain())
        return await fut

    async def _drain(self) -> None:
        while not self._q.empty():
            priority, n, key, fn, fut = self._q.get_nowait()
            if priority == self.P3 and key is not None and self._latest.get(key) != n:
                if not fut.done():
                    fut.set_result(None)  # a newer edit of the same thing is queued: skip this one
                continue
            if priority == self.P2:
                asyncio.create_task(self._dm(fn, fut))
                await asyncio.sleep(0)
            else:
                await self._exec(fn, fut)

    async def _dm(self, fn, fut) -> None:
        async with self._dm_slots:
            self._dm_in_flight += 1
            self.max_dm_in_flight = max(self.max_dm_in_flight, self._dm_in_flight)
            try:
                await self._exec(fn, fut)
            finally:
                self._dm_in_flight -= 1

    @staticmethod
    async def _exec(fn, fut) -> None:
        try:
            res = await fn()
        except BaseException as exc:  # SimulatedCrash included: it must reach the caller
            if not fut.done():
                fut.set_exception(exc)
            return
        if not fut.done():
            fut.set_result(res)

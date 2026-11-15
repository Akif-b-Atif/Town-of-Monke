"""ARC-3: an async queue between the Discord event handlers and SQLite, so chat never waits on the database.
Flush it on shutdown and before the archive's lock step."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

log = logging.getLogger("monke.capture")


class ChatCapture:
    def __init__(self, store, batch: int = 100):
        self.store, self.batch = store, batch
        self.queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._closed: set = set()  # game ids whose chat is sealed (archive has started)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._worker())

    def put(self, row: dict) -> None:
        if row["game_id"] not in self._closed:
            self.queue.put_nowait(row)

    def close(self, game_id: str) -> None:
        """Stop recording a game (called when the archive locks the channels)."""
        self._closed.add(game_id)

    def is_closed(self, game_id: str) -> bool:
        return game_id in self._closed

    async def flush(self) -> None:
        """Wait until everything queued so far is in the database."""
        if self._task is None or self._task.done():
            await self._drain()
        else:
            await self.queue.join()

    async def stop(self) -> None:
        await self.flush()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _drain(self) -> None:
        rows = []
        while not self.queue.empty():
            rows.append(self.queue.get_nowait())
            self.queue.task_done()
        if rows:
            await self.store.add_chat_rows(rows)

    async def _worker(self) -> None:
        while True:
            rows = [await self.queue.get()]
            while len(rows) < self.batch and not self.queue.empty():
                rows.append(self.queue.get_nowait())
            try:
                await self.store.add_chat_rows(rows)
            except Exception:
                log.exception("could not write %d chat rows", len(rows))
            finally:
                for _ in rows:
                    self.queue.task_done()

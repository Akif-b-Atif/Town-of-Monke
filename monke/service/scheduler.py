"""One asyncio task per game. It sleeps until phase_ends_at, then fires AdvancePhase(expected_phase_id).
Stale timers are harmless because the engine ignores a mismatching phase_id."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

log = logging.getLogger("monke.scheduler")


class Scheduler:
    def __init__(self, on_fire: Callable[[str, int], Awaitable[None]], clock: Callable[[], float] = time.time):
        self._on_fire = on_fire
        self._clock = clock
        self._tasks: dict = {}

    def arm(self, game_id: str, ends_at: float, phase_id: int) -> None:
        self.cancel(game_id)
        self._tasks[game_id] = asyncio.create_task(self._run(game_id, ends_at, phase_id))

    def cancel(self, game_id: str) -> None:
        t = self._tasks.pop(game_id, None)
        if t and not t.done() and t is not asyncio.current_task():
            t.cancel()

    async def _run(self, game_id: str, ends_at: float, phase_id: int) -> None:
        try:
            await asyncio.sleep(max(0.0, ends_at - self._clock()))
            await self._on_fire(game_id, phase_id)
        except asyncio.CancelledError:
            pass
        except Exception:  # pragma: no cover
            log.exception("timer for %s failed", game_id)

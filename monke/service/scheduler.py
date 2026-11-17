"""One asyncio task per game. It sleeps until phase_ends_at, then fires AdvancePhase(expected_phase_id).
Stale timers are harmless because the engine ignores a mismatching phase_id."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

log = logging.getLogger("monke.scheduler")
SLICE = 5.0  # seconds


class Scheduler:
    def __init__(self, on_fire: Callable[[str, int], Awaitable[None]], clock: Callable[[], float] = time.time,
                 on_warn: Callable[[str, int], Awaitable[None]] = None):
        self._on_fire = on_fire
        self._on_warn = on_warn
        self._clock = clock
        self._tasks: dict = {}
        self._warns: dict = {}

    def arm(self, game_id: str, ends_at: float, phase_id: int) -> None:
        self.cancel(game_id)
        self._tasks[game_id] = asyncio.create_task(self._run(game_id, ends_at, phase_id))

    def arm_warning(self, game_id: str, at: float, phase_id: int) -> None:
        """QOL-2: a second wake-up that carries the phase id; the handler ignores it if the phase has changed."""
        t = self._warns.pop(game_id, None)
        if t and not t.done() and t is not asyncio.current_task():
            t.cancel()
        if self._on_warn is not None:
            self._warns[game_id] = asyncio.create_task(self._run(game_id, at, phase_id, self._on_warn))

    def cancel(self, game_id: str) -> None:
        for table in (self._tasks, self._warns):
            t = table.pop(game_id, None)
            if t and not t.done() and t is not asyncio.current_task():
                t.cancel()

    async def _run(self, game_id: str, ends_at: float, phase_id: int, callback=None) -> None:
        callback = callback or self._on_fire
        try:
            while True:  # REL-14: short slices, rechecking the wall clock, so a sleep or clock jump cannot hang a phase
                left = ends_at - self._clock()
                if left <= 0:
                    break
                await asyncio.sleep(min(SLICE, left))
            await callback(game_id, phase_id)
        except asyncio.CancelledError:
            pass
        except Exception:  # pragma: no cover
            log.exception("timer for %s failed", game_id)

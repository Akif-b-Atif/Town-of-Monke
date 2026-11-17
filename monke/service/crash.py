"""Crash injection for tests (REL-18). The service calls `crash.hit("name")` at named points; a test arms a point
and the call raises SimulatedCrash. It derives from BaseException so no `except Exception` in the bot swallows it:
the process 'dies' right there, and the test builds a brand new service on the same database file."""
from __future__ import annotations

from collections import Counter


class SimulatedCrash(BaseException):
    def __init__(self, point: str):
        super().__init__(point)
        self.point = point


class CrashPoints:
    """Named points: after_commit_before_render, after_send_before_outbox, mid_render, starting_after_roles,
    after_purge_before_cleanup, mid_shift, and one per archive state (archive_locked, archive_built,
    archive_uploaded)."""

    def __init__(self):
        self.armed: dict = {}
        self.counts: Counter = Counter()

    def arm(self, name: str, nth: int = 1) -> "CrashPoints":
        self.armed[name] = nth
        return self

    def disarm(self) -> None:
        self.armed.clear()

    def hit(self, name: str) -> None:
        self.counts[name] += 1
        if self.armed.get(name) == self.counts[name]:
            del self.armed[name]
            raise SimulatedCrash(name)

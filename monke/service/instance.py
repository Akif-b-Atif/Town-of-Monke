"""Single-instance guard and heartbeat (REL-3)."""
from __future__ import annotations

import os
import socket
import time
import uuid
from typing import Callable, Optional

HEARTBEAT_EVERY = 5.0
STALE_AFTER = 20.0


class AlreadyRunning(Exception):
    def __init__(self, other: dict):
        super().__init__("another copy of the bot is running")
        self.other = other


def pid_alive(pid: int) -> bool:
    """Is a process with this pid running on this machine? (Never signals the process on Windows.)"""
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class InstanceGuard:
    def __init__(self, store, clock: Callable[[], float] = time.time, pid: Optional[int] = None,
                 host: Optional[str] = None, alive: Callable[[int], bool] = pid_alive):
        self.store, self.clock = store, clock
        self.pid = os.getpid() if pid is None else pid
        self.host = socket.gethostname() if host is None else host
        self.alive = alive
        self.instance_id = uuid.uuid4().hex[:12]
        self.last_heartbeat_before: Optional[float] = None  # the previous process's last sign of life (REL-6)

    async def start(self, force: bool = False) -> None:
        """Refuse to start if another instance's heartbeat is under 20 s old and it did not exit cleanly.
        A copy on this machine whose process is gone is not 'running', however fresh its heartbeat (so a
        supervisor can restart a crashed bot at once)."""
        others = await self.store.other_instances(self.instance_id)
        now = self.clock()
        for o in others:
            if o["clean_exit"] or now - o["heartbeat_at"] >= STALE_AFTER:
                continue
            if o["host"] == self.host and not self.alive(o["pid"]):
                continue
            if not force:
                raise AlreadyRunning(o)
        self.last_heartbeat_before = max((o["heartbeat_at"] for o in others), default=None)
        await self.store.instance_register(self.instance_id, self.pid, self.host, now)
        await self.store.prune_instances()

    async def heartbeat(self) -> float:
        now = self.clock()
        await self.store.instance_heartbeat(self.instance_id, now)
        return now

    async def stop(self) -> None:
        await self.store.instance_clean_exit(self.instance_id)

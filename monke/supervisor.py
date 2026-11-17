"""python -m monke --supervise (REL-11): run the bot as a child process and restart it after any non-zero exit.

Back-off 1, 2, 4 ... 60 s (reset after 5 minutes of stability). After 5 crashes in 5 minutes it stops and says why.
Exit code 0 ends supervision; Ctrl+C is forwarded to the child and ends supervision."""
from __future__ import annotations

import signal
import subprocess
import sys
import time
from typing import Callable, Optional

MAX_CRASHES = 5
WINDOW = 300.0
STABLE = 300.0


def child_command(argv: Optional[list] = None) -> list:
    argv = sys.argv[1:] if argv is None else argv
    return [sys.executable, "-m", "monke"] + [a for a in argv if a != "--supervise"]


def supervise(cmd: list, popen: Callable = subprocess.Popen, sleep: Callable = time.sleep,
              clock: Callable = time.monotonic, out: Callable = print, max_crashes: int = MAX_CRASHES,
              window: float = WINDOW, stable: float = STABLE) -> int:
    backoff, crashes = 1.0, []
    while True:
        started = clock()
        out(f"[supervisor] starting: {' '.join(cmd)}")
        proc = popen(cmd)
        try:
            code = proc.wait()
        except KeyboardInterrupt:  # Ctrl+C is forwarded and ends supervision
            try:
                proc.send_signal(signal.SIGINT)
            except Exception:
                pass
            try:
                return proc.wait(timeout=30) or 0
            except Exception:
                proc.kill()
                return 130
        if code == 0:
            out("[supervisor] the bot exited cleanly; stopping.")
            return 0
        now = clock()
        if now - started >= stable:
            backoff = 1.0  # it ran for a long time before this crash: start the back-off over
        crashes = [t for t in crashes if now - t < window] + [now]
        if len(crashes) >= max_crashes:
            out(f"[supervisor] the bot crashed {len(crashes)} times in {int(window // 60)} minutes (last exit code "
                f"{code}); giving up. Check logs/monke.log, fix the problem, then start it again.")
            return 1
        out(f"[supervisor] the bot exited with code {code}; restarting in {backoff:.0f}s")
        sleep(backoff)
        backoff = min(backoff * 2, 60.0)

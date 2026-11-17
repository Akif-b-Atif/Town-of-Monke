"""Graceful shutdown on SIGINT, SIGTERM, Windows Ctrl+C / Ctrl+Break and console close (REL-12)."""
from __future__ import annotations

import asyncio
import signal
import sys
from typing import Callable


def install_signal_handlers(loop: asyncio.AbstractEventLoop, callback: Callable[[], None]) -> None:
    """`callback` is called (once per signal) on the loop thread. It should schedule the clean shutdown."""
    names = ["SIGINT", "SIGTERM"] + (["SIGBREAK"] if sys.platform == "win32" else [])
    for name in names:
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, callback)
        except (NotImplementedError, RuntimeError):  # Windows event loops
            signal.signal(sig, lambda *_a, _cb=callback: loop.call_soon_threadsafe(_cb))
    if sys.platform == "win32":  # pragma: no cover - Windows only
        _install_console_close(loop, callback)


def _install_console_close(loop, callback) -> None:  # pragma: no cover - Windows only
    """Closing the console window sends CTRL_CLOSE_EVENT; Windows gives the process a few seconds."""
    try:
        import ctypes
        handler_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

        def handler(event):
            if event in (0, 1, 2, 5, 6):  # CTRL_C, CTRL_BREAK, CTRL_CLOSE, LOGOFF, SHUTDOWN
                loop.call_soon_threadsafe(callback)
                import time
                time.sleep(5)  # let the shutdown run before Windows ends the process
                return True
            return False
        _install_console_close.keep = handler_type(handler)  # keep a reference
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_install_console_close.keep, True)
    except Exception:
        pass

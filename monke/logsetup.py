"""Logging (REL-16): logs/monke.log rotating (5 files of 5 MB) plus the console. Every line carries the guild id,
game id, phase id and event seq. Roles and private text appear only in debug mode; the log file may hold the seed
of a crashed game, so it is a spoiler file and never goes to the console."""
from __future__ import annotations

import contextvars
import logging
import logging.handlers
import os

CTX: contextvars.ContextVar = contextvars.ContextVar("monke_log_ctx", default={})
FORMAT = "%(asctime)s %(levelname)s [guild=%(guild)s game=%(game)s phase=%(phase)s seq=%(seq)s] %(name)s: %(message)s"


def set_context(guild=None, game=None, phase=None, seq=None) -> None:
    CTX.set({"guild": guild, "game": game, "phase": phase, "seq": seq})


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = CTX.get()
        for key in ("guild", "game", "phase", "seq"):
            setattr(record, key, ctx.get(key) if ctx.get(key) is not None else "-")
        return True


def setup_logging(log_dir: str = "logs", level: int = logging.INFO, console: bool = True) -> str:
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "monke.log")
    fmt = logging.Formatter(FORMAT)
    flt = ContextFilter()
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    fileh = logging.handlers.RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8")
    fileh.setFormatter(fmt)
    fileh.addFilter(flt)
    root.addHandler(fileh)
    if console:
        con = logging.StreamHandler()
        con.setFormatter(fmt)
        con.addFilter(flt)
        root.addHandler(con)
    spoiler = logging.getLogger("monke.spoiler")  # seeds and other spoilers: the file only
    spoiler.propagate = False
    spoiler.handlers = [fileh]
    spoiler.setLevel(level)
    return path

"""Debug console (DBG-1 to DBG-7). Watch a whole game from the script's console as the all-seeing admin.

A sink is passed in; the default NullSink does nothing, so there is no global state. Output goes to stdout (and
optionally a file) only: never to Discord, the archive or the normal log file (DBG-7). One event per line:

    HH:MM:SS <game> <phase> <TAG> text

Tags: GAME PHASE VOTE ACTION TRACE DEATH DM POST PROMPT CHAT TIMER ARCHIVE RECOVER ADMIN ERROR.
Human chat prints only its length unless `chat=True` (`--debug-chat`, DBG-3)."""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

from . import constants as C
from .describe import Describer, label, state_label

TAGS = ("GAME", "PHASE", "VOTE", "ACTION", "TRACE", "DEATH", "DM", "POST", "PROMPT", "CHAT", "TIMER", "ARCHIVE",
        "RECOVER", "ADMIN", "ERROR")
BANNER = "DEBUG MODE: this console shows every role and private message. Do not share it."
_COLORS = {"GAME": "36", "PHASE": "35", "VOTE": "33", "ACTION": "32", "TRACE": "90", "DEATH": "31", "DM": "34",
           "POST": "34", "PROMPT": "34", "CHAT": "37", "TIMER": "90", "ARCHIVE": "36", "RECOVER": "36",
           "ADMIN": "33", "ERROR": "1;31"}
_SOURCE_TAG = {"PHASE": "PHASE", "VOTE": "VOTE", "VERDICT": "VOTE", "TRACE": "TRACE", "DEATH": "DEATH",
               "ADMIN": "ADMIN", "ACTION": "ACTION", "SYSTEM": "GAME"}
_ADMIN_COMMANDS = {"Abort", "Pause", "Resume", "ShiftDeadline", "Extend", "Replace", "ModKill", "Abandon"}


def one_line(text: str) -> str:
    return str(text).replace("\r", "").replace("\n", "\\n")


class NullSink:
    """Does nothing. The default everywhere."""
    enabled = False
    chat_text = False

    def bind(self, service) -> None: ...
    def game_started(self, state, now=None) -> None: ...
    def commit(self, before, after, cmd, events, now=None, deliver=False, rendered=None) -> None: ...
    def rejected(self, state, cmd, reason, now=None) -> None: ...
    def dm(self, user_id, text, now=None) -> None: ...
    def post(self, guild_id, channel_kind, text, now=None) -> None: ...
    def prompt(self, state, slot, label, options, now=None) -> None: ...
    def chat(self, state, channel_kind, slot, name, text, now=None) -> None: ...
    def note(self, tag, text, game=None, now=None) -> None: ...


class ConsoleSink(NullSink):
    enabled = True

    def __init__(self, out=None, file_path: Optional[str] = None, chat: bool = False, clock=time.time,
                 color: Optional[bool] = None):
        self.out = out if out is not None else sys.stdout
        self.file = open(file_path, "a", encoding="utf-8", buffering=1) if file_path else None
        self.chat_text, self.clock = chat, clock
        isatty = getattr(self.out, "isatty", lambda: False)()
        self.color = (isatty and not os.environ.get("NO_COLOR")) if color is None else color
        self.service = None
        self.lines: list = []  # kept for tests

    def bind(self, service) -> None:
        self.service = service

    # ------------------------------------------------------------------ output
    def emit(self, tag: str, text: str, game=None, phase: str = "-", now=None) -> str:
        t = self.clock() if now is None else now
        gid = getattr(game, "game_id", game) or "-"
        line = f"{time.strftime('%H:%M:%S', time.gmtime(t))} {gid} {phase} {tag} {one_line(text)}"
        self.lines.append(line)
        shown = f"\x1b[{_COLORS.get(tag, '0')}m{line}\x1b[0m" if self.color else line
        self._write(self.out, shown)
        if self.file is not None:
            self._write(self.file, line)
        return line

    @staticmethod
    def _write(stream, line: str) -> None:
        try:
            stream.write(line + "\n")
        except UnicodeEncodeError:  # a console that cannot show an emoji must not crash the bot
            stream.write(line.encode("ascii", "replace").decode() + "\n")
        try:
            stream.flush()
        except Exception:
            pass

    def banner(self) -> None:
        self._write(self.out, BANNER)
        if self.file is not None:
            self._write(self.file, BANNER)

    def note(self, tag, text, game=None, now=None) -> None:
        self.emit(tag, text, game, state_label(game) if hasattr(game, "phase") else "-", now)

    # ------------------------------------------------------------------ lookups
    def _find(self, user_id: int):
        if self.service is None:
            return None, None
        for g in self.service.games.values():
            slot = g.slot_of_user(user_id)
            if slot is not None:
                return g, slot
        return None, None

    # ------------------------------------------------------------------ game start (DBG-2)
    def game_started(self, state, now=None) -> None:
        ph = "Pre-game"
        d = Describer(state)
        self.emit("GAME", f"start seed={state.rng_seed} players={len(state.players)}", state, ph, now)
        self.emit("GAME", "settings " + " ".join(f"{k}={v}" for k, v in sorted(vars(state.settings).items())),
                  state, ph, now)
        self.emit("GAME", "role list " + ", ".join(state.rolelist), state, ph, now)
        from .roles import get_def
        for slot in sorted(state.players):
            p = state.players[slot]
            r = get_def(p.role_id)
            self.emit("GAME", f"table #{slot:02d} {p.display_name or 'Player'} {r.name} {r.alignment}", state, ph, now)

    # ------------------------------------------------------------------ commands and their events
    def commit(self, before, after, cmd, events, now=None, deliver=False, rendered=None) -> None:
        """`rendered` ({event seq: [Msg]}) lets the simulator print what would have been delivered."""
        d = Describer(after)
        kind = type(cmd).__name__
        ph_before = state_label(before)
        row = {"type": kind, "payload": _payload(cmd), "accepted": True}
        if kind == "SubmitAction":
            for _src, text in d.command_lines(row):
                self.emit("ACTION", text, after, ph_before, now)
        elif kind == "AdvancePhase":
            if getattr(cmd, "force", False):
                self.emit("ADMIN", f"skip: phase advanced early by {getattr(cmd, 'by', '') or 'an admin'}",
                          after, ph_before, now)
        elif kind in ("SetWill", "SetDeathNote"):  # DBG-2: wills and death notes are printed
            self.emit("ACTION", f"{d.who(getattr(cmd, 'slot', None))} set their {'will' if kind == 'SetWill' else 'death note'}: "
                                f"{getattr(cmd, 'text', '')!r}", after, ph_before, now)
        elif kind in _ADMIN_COMMANDS:
            self.emit("ADMIN", f"{kind} {row['payload']}", after, ph_before, now)
        trace_steps = [s for e in events if e.type == "NightTrace" for s in e.payload.get("steps", [])]
        ph = ph_before  # events before a PhaseChanged belong to the phase that just ended
        for e in events:
            if e.type == "PhaseChanged":
                ph = label(e.payload["phase"], e.payload["day_number"], e.payload["night_number"])[0]
            self._event(d, after, e, ph, trace_steps, now, deliver, (rendered or {}).get(e.seq))

    def _event(self, d, state, e, ph, trace_steps, now, deliver, msgs=None) -> None:
        t, p = e.type, e.payload
        ed = {"type": t, "payload": p, "audience": e.audience, "seq": e.seq}
        if deliver and msgs is not None:  # simulator: print the messages the presenter would deliver
            for m in msgs:
                if m.target.startswith("slot:"):
                    who = d.who(int(m.target.split(":")[1]))
                    tag = "PROMPT" if m.view and m.view[0] == "prompt" else "DM"
                    self.emit(tag, f"{who} <- '{m.text()}'", state, ph, now)
                elif m.effect != "purge_jail" and not m.meta.get("admin_only"):
                    self.emit("POST", f"{m.target} '{m.text()}'", state, ph, now)
        if t in ("ActionRecorded", "PromptRequested", "RoleAssigned", "PrivateMessage"):
            return
        if t == "Announcement":
            if e.audience == "admin":
                for src, text in d.event_lines(ed):
                    self.emit(_SOURCE_TAG.get(src, "GAME"), text, state, ph, now)
            return
        if t == "PlayerDied":
            killers = sorted({s["actor"] for s in trace_steps if s["step"] == "attack" and s["target"] == p["slot"]
                              and s["outcome"] == "success" and s["actor"] is not None})
            by = f" by {', '.join(d.who(k) for k in killers)}" if killers else ""
            self.emit("DEATH", f"{d.who(p['slot'])} died: {', '.join(p.get('causes', []))}{by}; role revealed",
                      state, ph, now)
            return
        for src, text in d.event_lines(ed):
            self.emit(_SOURCE_TAG.get(src, "GAME"), text, state, ph, now)

    def rejected(self, state, cmd, reason, now=None) -> None:
        d = Describer(state)
        row = {"type": type(cmd).__name__, "payload": _payload(cmd), "accepted": False, "reason": reason}
        for src, text in d.command_lines(row):
            self.emit(_SOURCE_TAG.get(src, "GAME"), text, state, state_label(state), now)

    # ------------------------------------------------------------------ delivery (DBG-6)
    def dm(self, user_id, text, now=None) -> None:
        g, slot = self._find(user_id)
        who = Describer(g).who(slot) if g is not None else f"user {user_id}"
        self.emit("DM", f"{who} <- '{text}'", g, state_label(g) if g else "-", now)

    def post(self, guild_id, channel_kind, text, now=None) -> None:
        g = self.service.get(guild_id) if self.service is not None else None
        self.emit("POST", f"{channel_kind} '{text}'", g, state_label(g) if g else "-", now)

    def prompt(self, state, slot, label, options, now=None) -> None:
        d = Describer(state)
        self.emit("PROMPT", f"{d.who(slot)} <- {label} options={[d.who(s) for s in options]}", state,
                  state_label(state), now)

    # ------------------------------------------------------------------ human chat (DBG-3)
    def chat(self, state, channel_kind, slot, name, text, now=None) -> None:
        who = f"#{slot:02d} {name}" if slot is not None else f"{name} (not a player)"
        body = f": {text}" if self.chat_text else f" ({len(text)} chars)"
        self.emit("CHAT", f"{who} in {channel_kind}{body}", state, state_label(state), now)


def _payload(cmd) -> dict:
    import dataclasses
    d = dataclasses.asdict(cmd) if dataclasses.is_dataclass(cmd) else {}
    d.pop("by", None)
    return d


def make_sink(enabled: bool = False, file_path: Optional[str] = None, chat: bool = False, **kw) -> NullSink:
    if not (enabled or file_path):
        return NullSink()
    sink = ConsoleSink(file_path=file_path, chat=chat, **kw)
    sink.banner()
    return sink

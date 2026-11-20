"""ARC-7: build_archive() is pure (no Discord, no I/O, no clock) and deterministic: the same inputs always
give byte-identical files. Zip writing lives in zipper.py.

Inputs are plain data: the final GameState, the stored event rows, the stored command rows, the stored
chat rows and a small `meta` dict. Output is {path_in_zip: bytes}."""
from __future__ import annotations

import bisect
import json

from .. import constants as C
from ..describe import Describer, faction_title, fmt_ts, label as _label  # noqa: F401  (DBG-5)
from ..roles import get_def
from .channels import CHANNEL_KINDS, filename_for

LOGGING_NOTICE = "Game channels are logged for the post-game archive."  # ARC-14

# Events that only matter to the archive's JSON, not to the readable timeline.
_SKIP_IN_TIMELINE = {"ActionRecorded", "PromptRequested"}
_VOTE_TYPES = {"VoteUpdated", "TrialStarted", "VerdictOpened", "VerdictRecorded", "VerdictsRevealed"}


class _Ctx:
    def __init__(self, state, events, commands, chat_rows, meta):
        self.state, self.events, self.commands, self.chat, self.meta = state, events, commands, chat_rows, meta
        self.gid = state.game_id
        self.d = Describer(state)
        # phase marks, in event order
        marks = []
        for e in events:
            if e["type"] == "PhaseChanged":
                p = e["payload"]
                lab, kind, num = _label(p["phase"], p["day_number"], p["night_number"])
                marks.append((e["ts_ms"], lab, kind, num))
            elif e["type"] == "GameEnded":
                marks.append((e["ts_ms"], "Post-game", "post", 0))
        self.marks = marks
        self._mark_ts = [m[0] for m in marks]

    def who(self, slot) -> str:
        return self.d.who(slot)

    def phase_at(self, ts_ms: int):
        i = bisect.bisect_right(self._mark_ts, ts_ms) - 1
        if i < 0:
            return "Pre-game", "pre", 0
        return self.marks[i][1], self.marks[i][2], self.marks[i][3]

    def audience_slot(self, audience: str):
        return self.d.audience_slot(audience)


def _header(ctx, title: str) -> str:
    return f"Town of Monke - game {ctx.gid}\n{title}\nAll times UTC\n\n"


def _line(ts_ms, label, src, text) -> str:
    return f"[{fmt_ts(ts_ms)}] [{label}] [{src}] {text}"


# ---------------------------------------------------------------------------------------- events
def _trace_text(ctx, step: dict) -> str:
    return ctx.d.trace_text(step)


def _event_lines(ctx, e) -> list:
    return ctx.d.event_lines(e)


def _command_lines(ctx, c) -> list:
    return ctx.d.command_lines(c)


def _chat_text(ctx, row, originals) -> str:
    if row["kind"] == "bot":
        who_ = "BOT"
    elif row.get("author_slot") is not None:
        who_ = ctx.who(row["author_slot"])
    else:
        who_ = f"{row.get('author_name') or 'unknown'} (not a player)"
    att = [a.get("filename", "file") for a in (row.get("attachments") or [])]
    suffix = f" [attachments: {', '.join(att)}]" if att else ""
    kind = row["kind"]
    if kind in ("edit", "delete"):
        orig = originals.get(row.get("message_id"))
        if orig is not None:
            who_ = "BOT" if orig["kind"] == "bot" else (
                ctx.who(orig["author_slot"]) if orig.get("author_slot") is not None
                else f"{orig.get('author_name') or 'unknown'} (not a player)")
        if kind == "edit":
            return f"{who_}: {row['content']} (edited)"
        text = orig["content"] if orig is not None else "(original text was not captured)"
        return f"[deleted] {who_}: {text}"
    recovered = " (recovered)" if row.get("backfilled") else ""  # REL-9: read back after a restart
    return f"{who_}: {row['content']}{suffix}{recovered}"


# ---------------------------------------------------------------------------------------- summary
def _fate(p) -> str:
    if p.alive:
        return "survived"
    d = p.death or {}
    return f"died {d.get('day_or_night', '?')} ({'/'.join(d.get('causes', []))})"


def archive_summary(state, events) -> dict:
    """Small dict for the upload embed and the DM separators."""
    rows = []
    for slot in sorted(state.players):
        p = state.players[slot]
        d = get_def(p.role_id)
        rows.append({"slot": slot, "name": p.display_name or "Player", "role": d.name, "alignment": d.alignment,
                     "fate": _fate(p), "winner": slot in state.winners,
                     "former": [f.get("name") or "Player" for f in p.former]})  # ADM2-1: replaced players
    ts = [e["ts_ms"] for e in events] or [0]
    return {"game_id": state.game_id, "winner": faction_title(state.winning_faction), "reason": state.end_reason or "",
            "days": state.day_number, "duration_s": max(0, (max(ts) - min(ts)) // 1000), "players": rows}


# ---------------------------------------------------------------------------------------- build
def build_archive(state, events: list, commands: list, chat_rows: list, meta: dict) -> dict:
    """-> {path: bytes}. ARC-16: never for a live game (tests pass meta['allow_live'])."""
    assert meta.get("allow_live") or state.status not in (C.RUNNING, C.PAUSED), "archive of a live game"
    ctx = _Ctx(state, events, commands, chat_rows, meta)
    originals = {r["message_id"]: r for r in chat_rows if r["kind"] in ("msg", "bot") and r.get("message_id")}
    files: dict = {}

    # --- merged timeline entries: (ts, group, idx, label, source, text)
    entries: list = []
    current = "Pre-game"
    for e in sorted(events, key=lambda x: x["seq"]):
        if e["type"] == "PhaseChanged":
            current = _label(e["payload"]["phase"], e["payload"]["day_number"], e["payload"]["night_number"])[0]
        elif e["type"] == "GameEnded":
            current = "Post-game"
        if e["type"] in _SKIP_IN_TIMELINE:
            continue
        # a PhaseChanged line is labelled with the phase it starts; everything before it keeps the old label
        for i, (src, text) in enumerate(_event_lines(ctx, e)):
            entries.append((e["ts_ms"], 2, e["seq"] * 1000 + i, current, src, text, e))
    for c in commands:
        for i, (src, text) in enumerate(_command_lines(ctx, c)):
            entries.append((c["ts_ms"], 1, c["seq"] * 1000 + i, ctx.phase_at(c["ts_ms"])[0], src, text, c))
    chat_lines: dict = {}
    for r in chat_rows:
        text = _chat_text(ctx, r, originals)
        src = f"CHAT:{r['channel_kind']}"
        lab = ctx.phase_at(r["ts_ms"])[0]
        entries.append((r["ts_ms"], 0, r["id"] if r.get("id") else 0, lab, src, text, r))
        path = filename_for(r["channel_kind"], r.get("session") or "")
        chat_lines.setdefault(path, []).append(_line(r["ts_ms"], lab, src, text))
    entries.sort(key=lambda x: (x[0], x[1], x[2]))
    timeline = [_line(ts, lab, src, text) for ts, _g, _i, lab, src, text, _o in entries]
    files["timeline.txt"] = (_header(ctx, "Timeline: everything, merged in time order")
                             + "\n".join(timeline) + "\n").encode()

    # --- chat files (every game-scope channel always gets a file)
    for kind in CHANNEL_KINDS.values():
        if kind.scope == "game":
            chat_lines.setdefault(kind.filename, [])
    for path, lines in sorted(chat_lines.items()):
        title = "Chat: " + path.split("/")[-1].rsplit(".", 1)[0]
        files[path] = (_header(ctx, title) + ("\n".join(lines) if lines else "(no messages)") + "\n").encode()

    # --- abilities per night / day
    nights = sorted({m[3] for m in ctx.marks if m[2] == "night"})
    days = sorted({m[3] for m in ctx.marks if m[2] == "day"})
    by_seq = sorted(events, key=lambda x: x["seq"])
    for n in nights:
        sec = ["== Actions submitted or changed =="]
        for c in commands:
            if c["type"] == "SubmitAction" and ctx.phase_at(c["ts_ms"])[1:] == ("night", n):
                sec += [_line(c["ts_ms"], f"Night {n}", s_, t_) for s_, t_ in _command_lines(ctx, c)]
        if len(sec) == 1:
            sec.append("(none)")
        sec += ["", "== Night trace (what the game did, in order) =="]
        results = ["", "== Results delivered to players =="]
        in_results = False
        got_trace = False
        for e in by_seq:
            if e["type"] == "NightTrace" and e["payload"].get("night") == n:
                got_trace, in_results = True, True
                sec += [_line(e["ts_ms"], f"Night {n}", "TRACE", _trace_text(ctx, s_)) for s_ in e["payload"]["steps"]]
            elif in_results and e["type"] == "PhaseChanged":
                in_results = False
            elif in_results and e["type"] == "PrivateMessage":
                results.append(_line(e["ts_ms"], f"Night {n}", "SYSTEM",
                                     f"to {ctx.who(ctx.audience_slot(e['audience']))}: {ctx.d.text(e['payload'])}"))
        if not got_trace:
            sec.append("(the night had not been resolved)")
        if len(results) == 2:
            results.append("(none)")
        files[f"abilities/night_{n:02d}.txt"] = (_header(ctx, f"Abilities, night {n}")
                                                 + "\n".join(sec + results) + "\n").encode()
    for d in days:
        sec = []
        for c in commands:
            if c["type"] == "SubmitAction" and ctx.phase_at(c["ts_ms"])[1:] == ("day", d):
                sec += [_line(c["ts_ms"], ctx.phase_at(c["ts_ms"])[0], s_, t_) for s_, t_ in _command_lines(ctx, c)]
        files[f"abilities/day_{d:02d}.txt"] = (_header(ctx, f"Abilities, day {d} (jail selections and other day actions)")
                                               + ("\n".join(sec) if sec else "(none)") + "\n").encode()

    # --- votes and trials
    vt = []
    cur = "Pre-game"
    for e in by_seq:
        if e["type"] == "PhaseChanged":
            cur = _label(e["payload"]["phase"], e["payload"]["day_number"], e["payload"]["night_number"])[0]
        if e["type"] in _VOTE_TYPES:
            vt += [_line(e["ts_ms"], cur, s_, t_) for s_, t_ in _event_lines(ctx, e)]
    for c in commands:
        if not c.get("accepted", True) and c["type"] in ("Vote", "Verdict"):
            vt += [_line(c["ts_ms"], ctx.phase_at(c["ts_ms"])[0], s_, t_) for s_, t_ in _command_lines(ctx, c)]
    files["votes_and_trials.txt"] = (_header(ctx, "Votes, trials and verdicts")
                                     + ("\n".join(vt) if vt else "(no votes were cast)") + "\n").encode()

    # --- README
    summ = archive_summary(state, events)
    rd = [_header(ctx, "README"), LOGGING_NOTICE, "",
          f"Result: {summ['winner']} ({summ['reason']}) after day {summ['days']}",
          f"Bot version: {meta.get('bot_version', '?')}", f"Seed: {state.rng_seed}", "",
          "Players", "slot  name                  role              alignment  fate                          winner"]
    for r in summ["players"]:
        who_ = r["name"] + (f" (replaced {', '.join(r['former'])})" if r.get("former") else "")
        rd.append(f"{r['slot']:>4}  {who_:<20}  {r['role']:<16}  {r['alignment']:<9}  {r['fate']:<28}  "
                  f"{'yes' if r['winner'] else 'no'}")
    s = state.settings
    rd += ["", "Role list: " + ", ".join(state.rolelist), "",
           "Settings: " + ", ".join(f"{k}={v}" for k, v in sorted(vars(s).items())), "",
           "Files", "  timeline.txt           everything merged in time order",
           "  chat/                  each game channel (jail has one file per night)",
           "  abilities/             night and day actions, the night trace, results delivered",
           "  votes_and_trials.txt   every vote, trial and verdict",
           "  data/game.json         structured data for replay"]
    files["README.txt"] = ("\n".join(rd) + "\n").encode()

    # --- structured data
    data = {"game_id": state.game_id, "seed": state.rng_seed, "settings": state.to_dict()["settings"],
            "rolelist": list(state.rolelist), "players": summ["players"], "result": {
                "winner": summ["winner"], "reason": summ["reason"], "days": summ["days"]},
            "commands": commands, "events": events, "bot_version": meta.get("bot_version")}
    files["data/game.json"] = json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False).encode()
    return files

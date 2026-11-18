"""One description module (DBG-5). Pure: no Discord, no I/O, no clock.

The post-game archive and the debug console both turn engine events, commands and night-trace steps into
text with the functions in this file, so the two can never disagree."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from . import constants as C
from .roles import get_def


def fmt_ts(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def label(phase: str, day: int, night: int):
    """(label, kind, number) of a phase, e.g. ('Day 3 Noon', 'day', 3)."""
    if phase == C.NIGHT:
        return f"Night {night}", "night", night
    suffix = {C.NOON: " Noon", C.TRIAL_DEFENSE: " Defense", C.TRIAL_VERDICT: " Verdict",
              C.AFTERNOON: " Afternoon"}.get(phase, "")
    return f"Day {day}{suffix}", "day", day


def faction_title(faction) -> str:
    return {"DRAW": "Draw", "ABORTED": "Aborted"}.get(faction, (faction or "Unknown").replace("_", " ").title())


def state_label(state) -> str:
    """The label of the phase a live game is in."""
    if state is None or state.phase in (C.NO_PHASE, C.PHASE_ENDED):
        return "Pre-game" if state is None or state.phase == C.NO_PHASE else "Post-game"
    return label(state.phase, state.day_number, state.night_number)[0]


class Describer:
    """Text for one game. `state` supplies names and roles (every person prints as '#04 Sam (Godfather)')."""

    def __init__(self, state, bank=None):
        from .compose import Composer
        from .names import fmt_player
        from .text.bank import default_bank
        self.state = state
        # variant 0 of the shipped text: the archive and the console word a key the same way every time
        self.composer = Composer(bank or default_bank(), namer=lambda st, slot, bold=False: fmt_player(st, slot),
                                 fixed=True)

    def text(self, p: dict) -> str:
        """The words of an Announcement or PrivateMessage payload (a text key, or old-style stored text)."""
        if "text_key" in p:
            try:
                head = self.composer.t(self.state, p["text_key"], **(p.get("vars") or {}))
                items = [self.composer.t(self.state, i["text_key"], **(i.get("vars") or {})) for i in p.get("items", [])]
                return "\n".join([head] + items)
            except Exception:
                return f"[{p['text_key']}]"
        return p.get("text", "")

    def who(self, slot) -> str:
        if slot is None:
            return "-"
        p = self.state.players.get(slot)
        if p is None:
            return f"#{int(slot):02d}"
        return f"#{slot:02d} {p.display_name or 'Player'} ({get_def(p.role_id).name})"

    @staticmethod
    def audience_slot(audience: str) -> Optional[int]:
        if audience and audience.startswith("slot:"):
            return int(audience.split(":")[1])
        return None

    # ------------------------------------------------------------------ night trace
    def trace_text(self, step: dict) -> str:
        d = step.get("detail") or {}
        extra = " ".join(f"{k}={v}" for k, v in sorted(d.items()) if v is not None)
        return (f"{step['step']}: {self.who(step.get('actor'))} -> {self.who(step.get('target'))}: "
                f"{step.get('outcome', '')} {extra}").rstrip()

    # ------------------------------------------------------------------ events
    def event_lines(self, e: dict) -> list:
        """[(source, text)] for one stored event (a dict with type, payload, audience)."""
        t, p, aud = e["type"], e["payload"], e.get("audience", "")
        w = self.who
        if t == "PhaseChanged":
            lab = label(p["phase"], p["day_number"], p["night_number"])[0]
            return [("PHASE", f"{lab} begins [{p.get('reason', '?')}], ends {fmt_ts(int(p['ends_at'] * 1000))}")]
        if t == "Announcement":
            return [("ADMIN" if aud == "admin" else "SYSTEM", self.text(p))]
        if t == "PrivateMessage":
            return [("SYSTEM", f"to {w(self.audience_slot(aud))}: {self.text(p)}")]
        if t == "DawnReport":
            died = ", ".join(w(x) for x in p.get("deaths", [])) or "nobody"
            return [("SYSTEM", f"Dawn of day {p.get('day')}: {died} died, {p.get('alive')} alive")]
        if t == "PlayerDied":
            return [("DEATH", f"{w(p['slot'])} died ({', '.join(p.get('causes', []))})")]
        if t == "VoteUpdated":
            if p.get("target") is None:
                return [("VOTE", f"{w(p['voter'])} withdrew their vote")]
            return [("VOTE", f"{w(p['voter'])} voted for {w(p['target'])} ({p.get('count')}/{p.get('threshold')})")]
        if t == "TrialStarted":
            return [("VERDICT", f"Trial begins: {w(p['defendant'])} has {int(p.get('defense_s', 0))}s to defend")]
        if t == "VerdictOpened":
            return [("VERDICT", f"Verdict opens on {w(p['defendant'])}")]
        if t == "VerdictRecorded":
            return [("VERDICT", f"{w(self.audience_slot(aud))} votes {p.get('verdict')}")]
        if t == "VerdictsRevealed":
            out = [("VERDICT", f"Result on {w(p['defendant'])}: {p.get('guilty')} guilty, {p.get('innocent')} innocent")]
            out += [("VERDICT", f"  {w(v['slot'])}: {v['verdict']}") for v in p.get("votes", [])]
            return out
        if t == "RoleAssigned":
            return [("SYSTEM", f"{w(p['slot'])} is {p.get('role')} ({p.get('alignment')})")]
        if t == "RosterPosted":
            return [("SYSTEM", "Roster: " + ", ".join(f"#{r['slot']:02d}" for r in p.get("roster", []))
                     + "; role list: " + ", ".join(p.get("rolelist", [])))]
        if t == "JailStarted":
            return [("SYSTEM", f"Jail: {w(p['jailor'])} jails {w(p['prisoner'])}")]
        if t == "JailEnded":
            return [("SYSTEM", f"Jail ends: prisoner {w(p['prisoner'])}")]
        if t == "StatusChanged":
            return [("SYSTEM", f"Game status: {p.get('status')}")]
        if t == "GameEnded":
            return [("SYSTEM", f"Game over: {faction_title(p.get('faction'))} ({p.get('reason')})")]
        if t == "AdminAction":
            who_ = w(p["slot"]) if p.get("slot") is not None else "not a player"
            return [("ADMIN", f"user {p.get('user_id')} ({who_}) ran `{p.get('command')}` {p.get('args', '')}".rstrip())]
        if t == "NightTrace":
            return [("TRACE", self.trace_text(s)) for s in p.get("steps", [])]
        return []

    # ------------------------------------------------------------------ commands
    def command_lines(self, c: dict) -> list:
        t, p, ok = c["type"], c.get("payload") or {}, c.get("accepted", True)
        w = self.who
        if t == "SubmitAction":
            tgt = w(p.get("target_slot")) if p.get("target_slot") is not None else "nobody"
            msg = f"{w(p.get('actor_slot'))} chose {p.get('ability_id')} -> {tgt} (active={p.get('active', True)})"
            return [("ACTION", msg if ok else f"REJECTED: {msg}: {c.get('reason')}")]
        if not ok:
            src = {"Vote": "VOTE", "Verdict": "VERDICT"}.get(t, "SYSTEM")
            return [(src, f"REJECTED {t} {json.dumps(p, sort_keys=True)}: {c.get('reason')}")]
        if t == "AdvancePhase" and p.get("force"):
            return [("SYSTEM", "phase advanced early by an admin command")]
        if t in ("Abort", "Resume", "Pause", "Abandon", "BeginGame"):
            return [("SYSTEM", f"command {t} {json.dumps(p, sort_keys=True)}")]
        return []  # accepted votes, verdicts and timer advances are already visible as events

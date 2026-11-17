"""Message composition: engine events -> plain `Msg` data, through the text system. Pure (no Discord).

The Discord presenter turns each Msg into a post or a DM; the simulator, the debug console and the tests read the
same Msgs, so a missing text key or a bad placeholder fails a test instead of a live game (TXT-5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from . import constants as C
from .engine import events as E
from .names import fmt_player
from .roles import get_def
from .roles.registry import has_role
from .text.bank import TextBank

CAUSE_KEYS = {C.MAFIA_KILL: "mafia", C.SERIAL_KILLER: "serial_killer", C.VETERAN: "veteran", C.EXECUTED: "jailor",
              C.HAUNTED: "jester_haunt", C.LYNCHED: "lynched", C.ABANDONED: "abandoned", C.MODERATED: "moderated"}
FACTION_KEYS = {"TOWN": "town", "MAFIA": "mafia", "SERIAL_KILLER": "sk", "DRAW": "draw", "ABORTED": "aborted"}
ALIGN_KEYS = {C.TOWN: "town", C.MAFIA: "mafia", C.NEUTRAL: "neutral"}
COLORS = {"town": 0x2ECC71, "mafia": 0xE74C3C, "neutral": 0x95A5A6, "system": 0x3498DB, "death": 0x992D22,
          "gold": 0xC27C0E}
PHASE_LINES = {C.DAY_1: "phase.day1", C.NOON: "phase.noon", C.AFTERNOON: "phase.afternoon", C.NIGHT: "phase.night"}
PHASE_TITLES = {C.DAY: "ui.title.day", C.TRIAL_DEFENSE: "ui.title.defense", C.TRIAL_VERDICT: "ui.title.verdict"}


@dataclass
class Msg:
    target: str  # town | mafia | jail | graveyard | commands | slot:<n>
    content: str = ""
    embed: Optional[dict] = None  # {title, description, color, fields: [(name, value, inline)], footer}
    view: Optional[tuple] = None  # ('verdict', game_id, token) | ('prompt', payload, names)
    mentions: bool = False  # only the Graveyard welcome may ping (XC-3)
    effect: Optional[str] = None  # 'banner' | 'pin' | 'purge_jail'
    meta: dict = field(default_factory=dict)

    def text(self) -> str:
        """Everything readable in the message, for logs and tests."""
        parts = [self.content] if self.content else []
        if self.embed:
            e = self.embed
            parts += [x for x in (e.get("title"), e.get("description")) if x]
            parts += [f"{n}: {v}" for n, v, _ in e.get("fields", [])]
            if e.get("footer"):
                parts.append(e["footer"])
        return "\n".join(parts)


class Composer:
    def __init__(self, bank: TextBank, namer: Optional[Callable] = None, fixed: bool = False):
        self.bank = bank
        self.fixed = fixed  # True: always variant 0, for the archive and debug console, which must be repeatable
        self.namer = namer or (lambda state, slot, bold=False: fmt_player(state, slot, bold=bold))

    # ------------------------------------------------------------------ text helpers
    def name(self, state, slot) -> str:
        return self.namer(state, slot)

    def t(self, state, key: str, **vars) -> str:
        """Render a key for this game: slots become 'Maya (#3)', role ids become role names, durations words."""
        gid = getattr(state, "game_id", None)
        vals = self._prep(state, vars)
        return self.bank.render(key, game=gid, variant=0 if self.fixed else None,
                                resolve=(lambda s: self.name(state, s)) if state is not None else None, **vals)

    def _prep(self, state, vars: dict) -> dict:
        v = dict(vars)
        if "role_id" in v:
            v["role"] = self.role_name(v.pop("role_id"))
        t = v.get("time")
        if isinstance(t, (int, float)) and not isinstance(t, bool):
            v["time"] = self.duration(t)
        elif isinstance(t, dict):
            v["time"] = self.when(t)
        c = v.get("causes")
        if c in (C.KIND_DAY, C.KIND_NIGHT):
            v["causes"] = self.bank.render("ui.phase.night" if c == C.KIND_NIGHT else "ui.phase.day")
        return v

    def role_name(self, role_id: str) -> str:
        key = f"role.{role_id}.name"
        if self.bank.has(key):
            return self.bank.render(key, variant=0)
        return get_def(role_id).name if has_role(role_id) else role_id

    def duration(self, seconds: float) -> str:
        s = max(0, int(round(seconds)))
        if s < 90:
            n, unit = s, "second" if s == 1 else "seconds"
        elif s < 5400:
            n = round(s / 60)
            unit = "minute" if n == 1 else "minutes"
        else:
            n = round(s / 3600)
            unit = "hour" if n == 1 else "hours"
        return self.bank.render(f"ui.duration.{unit}", variant=0, count=n)

    def when(self, w: dict) -> str:
        kind = w.get("when", "day")
        return self.bank.render(f"ui.when.{kind}", variant=0, day=w.get("day", 0), night=w.get("night", 0))

    def error(self, rej, state=None) -> str:
        """The text of a Rejected: what is wrong and how to fix it (QOL-11)."""
        return self.t(state, rej.key, **rej.vars)

    # ------------------------------------------------------------------ banner (TRN-3)
    def _transition(self, state, reason: str, ctx: dict) -> str:
        d = ctx.get("day", state.day_number)
        n = ctx.get("night", state.night_number)
        target = ctx.get("target_slot")
        if reason in ("game_start", "night_resolved", "trial_majority"):
            return ""
        simple = {"day1_timer": "transition.day1_timer", "day_timer": "transition.day_timer",
                  "defense_timer": "transition.defense_timer", "skip_early": "transition.skip_early",
                  "noon_no_trial": "noon.no_trial", "noon_timeout_after_pardon": "noon.no_trial",
                  "three_innocent": "trial.three_innocent"}
        if reason in simple:
            return self.t(state, simple[reason])
        if reason == "afternoon_timer":
            return self.t(state, "transition.afternoon_timer", night=n)
        if reason == "verdict_guilty":
            return self.t(state, "trial.guilty", target=target, count=ctx.get("guilty", 0), needed=ctx.get("innocent", 0))
        if reason == "verdict_pardon":
            return self.t(state, "trial.pardon", target=target)
        return self.t(state, "transition.unknown")

    def banner(self, state, p: dict, variants: Optional[dict] = None) -> tuple:
        """-> (text, {key: variant index}). Passing the variants back re-renders the same wording (for edits)."""
        ctx = p.get("ctx") or {}
        variants = dict(variants or {})
        phase = p["phase"]
        lines = []
        tl = self._transition(state, p.get("reason", ""), ctx)
        if ctx.get("admin_skip"):
            tl = (self.t(state, "transition.admin_skip", name=ctx.get("admin_name") or "Admin") + " " + tl).strip()
        if tl:
            lines += [tl, ""]
        gid = getattr(state, "game_id", None)
        vars_ = {"day": p["day_number"], "night": p["night_number"], "time": f"<t:{int(p['ends_at'])}:t>"}
        key = PHASE_LINES.get(phase) or PHASE_TITLES.get(phase)
        if key:
            i, text = self.bank.render_variant(key, gid, variants.get(key),
                                               resolve=lambda s: self.name(state, s), **vars_)
            variants[key] = i
            lines.append(text)
        lines.append(self.t(state, "ui.banner.status", rel=f"<t:{int(p['ends_at'])}:R>", alive=len(state.alive_slots())))
        if phase == C.NOON and ctx.get("needed") is not None:
            lines.append(self.t(state, "ui.banner.votes", needed=ctx["needed"]))
        return "\n".join(lines), variants

    # ------------------------------------------------------------------ deaths and the dawn report (CARD-5)
    def cause_line(self, state, slot: int, causes: list) -> str:
        if len(causes) == 1:
            return self.t(state, f"death.cause.{CAUSE_KEYS[causes[0]]}", player=slot)
        names = [self.bank.render(f"ui.cause.{CAUSE_KEYS[c]}", variant=0) for c in causes]
        return self.t(state, "death.cause.multiple", player=slot, causes=self.bank.render("ui.join.and", variant=0).join(names))

    def death_lines(self, state, slot: int) -> list:
        p = state.players[slot]
        d = p.death or {"causes": []}
        out = [self.cause_line(state, slot, d["causes"]),
               self.t(state, f"role.{p.role_id}.reveal", player=slot)]
        if d.get("will"):
            out.append(self.t(state, "death.will", player=slot, will=d["will"]))
        if d.get("note"):
            out.append(self.t(state, "death.note", note=d["note"]))
        return out

    def dawn(self, state, p: dict) -> str:
        lines = [self.t(state, "phase.dawn", day=p["day"])]
        deaths = sorted(p.get("deaths") or [])
        if not deaths:
            lines.append(self.t(state, "dawn.no_deaths"))
        for slot in deaths:
            lines.append("")
            lines += self.death_lines(state, slot)
        lines.append("")
        lines.append(self.t(state, "dawn.survivors", alive=p["alive"]))
        if p.get("stalemate_warning"):
            lines.append(self.t(state, "dawn.stalemate_warning", count=p.get("quiet", 0)))
        return "\n".join(lines)

    # ------------------------------------------------------------------ prompts and role cards
    def ability_label(self, state, role_id: str, ability_id: str, uses_left=None) -> str:
        return self.t(state, f"ability.{role_id}.{ability_id}.label", count=uses_left if uses_left is not None else 0)

    def prompt(self, state, p: dict, current: Optional[str] = None) -> str:
        label = self.ability_label(state, p["role_id"], p["ability_id"], p.get("uses_left"))
        when = self.t(state, "ui.prompt.tonight" if p["phase_kind"] == C.KIND_NIGHT else "ui.prompt.today")
        deadline = (self.t(state, "ui.prompt.deadline_night", rel=f"<t:{int(p['ends_at'])}:R>")
                    if p["phase_kind"] == C.KIND_NIGHT else self.t(state, "ui.prompt.deadline_day"))
        text = f"**{label}** ({when})\n{deadline}"
        if current is None:
            if p["kind"] == "toggle" and p.get("current_active") is not None:
                current = self.t(state, "ui.prompt.on" if p["current_active"] else "ui.prompt.off")
            elif p.get("current_target") is not None:
                current = self.name(state, p["current_target"])
        if current:
            text += f"\n\n{self.t(state, 'ui.prompt.current')}: **{current}**"
        return text

    def card(self, state, c: dict) -> dict:
        rid = c["role_id"]
        align = ALIGN_KEYS[c["alignment"]]
        wiki = self.bank.render(f"role.{rid}.wiki", variant=0)
        abilities = []
        for a in c["abilities"]:
            abilities.append(self.ability_label(state, rid, a["id"], a.get("uses_left")))
        fields = [(self.t(state, "ui.card.alignment"), self.t(state, f"ui.align.{align}"), True),
                  (self.t(state, "ui.card.attack"), self.t(state, f"ui.level.{c['attack']}"), True),
                  (self.t(state, "ui.card.defense"), self.t(state, f"ui.level.{c['defense']}"), True)]
        if abilities:
            fields.append((self.t(state, "ui.card.abilities"), "\n".join(abilities), False))
        fields.append((self.t(state, "ui.card.goal"), self.t(state, f"role.{rid}.goal", wiki=wiki), False))
        fields.append((self.t(state, "ui.card.tips"), self.t(state, f"role.{rid}.tips", wiki=wiki), False))
        if c.get("teammates"):
            fields.append((self.t(state, "ui.card.team"), "\n".join(
                self.t(state, "ui.card.teammate", player=m["slot"], role_id=m["role_id"]) for m in c["teammates"]), False))
        return {"title": self.t(state, "ui.card.title", role_id=rid),
                "description": self.t(state, f"role.{rid}.intro", wiki=wiki), "color": align, "fields": fields}

    # ------------------------------------------------------------------ events -> messages
    def compose(self, state, e) -> list:
        fn = getattr(self, f"_e_{e.type}", None)
        return fn(state, e) if fn else []

    def _e_PhaseChanged(self, state, e):
        text, variants = self.banner(state, e.payload)
        out = [Msg("town", text, effect="banner", meta={"variants": variants, "phase_id": e.payload["phase_id"]})]
        if e.payload["phase"] == C.NOON:  # CMD-5: a vote panel; its tally is edited, not reposted
            from .adapter.info import tally_embed
            names = {s: self.name(state, s) for s in state.alive_slots()}
            view = ("panel", state.game_id, e.payload["phase_id"], names, self.t(state, "panel.placeholder"),
                    self.t(state, "ui.button.unvote"))
            out.append(Msg("town", embed=tally_embed(self, state), view=view, effect="panel",
                           meta={"phase_id": e.payload["phase_id"]}))
        return out

    def _e_DawnReport(self, state, e):
        return [Msg("town", self.dawn(state, e.payload))]

    def _e_Announcement(self, state, e):
        p = e.payload
        text = self.t(state, p["text_key"], **p.get("vars", {})) if "text_key" in p else p.get("text", "")
        aud = e.audience
        if aud == E.PUBLIC:
            return [Msg("town", text)]
        if aud.startswith("alignment:"):
            return [Msg("mafia", text)]
        if aud.startswith("slot:"):
            return [Msg(aud, text)]
        return [Msg("commands", text, meta={"admin_only": True})]

    _e_PrivateMessage = _e_Announcement

    def _e_PlayerDied(self, state, e):
        p = e.payload
        out = []
        if p.get("where") == "day":
            lines = self.death_lines(state, p["slot"])
            lines[0] = f"{self.t(state, 'ui.emoji.death')} {lines[0]}"
            out.append(Msg("town", embed={"description": "\n".join(lines), "color": "death"}))
        uid = p.get("user_id")
        out.append(Msg("graveyard", self.t(state, "graveyard.welcome", player=f"<@{uid}>"), mentions=True))
        if p.get("first_death"):
            out.append(Msg("graveyard", self.t(state, "graveyard.rules"), effect="pin"))
        return out

    def _e_VoteUpdated(self, state, e):
        p = e.payload
        if p["target"] is None:
            if p.get("previous") is None:
                return []
            return [Msg("town", self.t(state, "vote.remove", player=p["voter"], target=p["previous"]))]
        if p.get("previous") is not None and p["previous"] != p["target"]:
            return [Msg("town", self.t(state, "vote.change", player=p["voter"], target=p["target"],
                                       previous=p["previous"], count=p["count"], needed=p["threshold"]))]
        return [Msg("town", self.t(state, "vote.cast", player=p["voter"], target=p["target"], count=p["count"],
                                   needed=p["threshold"]))]

    def _e_TrialStarted(self, state, e):
        p, d = e.payload, e.payload["defendant"]
        lines = [self.t(state, "trial.start", target=d), self.t(state, "trial.defense", target=d, time=p["defense_s"])]
        if p.get("voters"):
            lines.append(self.t(state, "ui.trial.voters", players=p["voters"]))
        return [Msg("town", "\n".join(lines))]

    def _e_VerdictOpened(self, state, e):
        p = e.payload
        text = self.t(state, "trial.verdict", target=p["defendant"], time=state.settings.verdict_s)
        labels = {v: self.t(state, f"ui.button.{v}") for v in (C.GUILTY, C.INNOCENT, C.ABSTAIN)}
        return [Msg("town", text, view=("verdict", p["game_id"], p["token"], labels))]

    def _e_VerdictsRevealed(self, state, e):
        p = e.payload
        groups = []
        for verdict, key in ((C.GUILTY, "guilty"), (C.INNOCENT, "innocent"), (C.ABSTAIN, "abstain")):
            slots = [v["slot"] for v in p["votes"] if v["verdict"] == verdict]
            players = self.name_list(state, slots) if slots else self.t(state, "ui.verdict.none")
            groups.append(self.t(state, f"ui.verdict.{key}", count=len(slots), players=players))
        title = self.t(state, "trial.reveal", count=p["guilty"], needed=p["innocent"])
        return [Msg("town", embed={"title": title, "description": "\n".join(groups), "color": "system"})]

    def name_list(self, state, slots) -> str:
        return ", ".join(self.name(state, s) for s in sorted(slots))

    def _e_RosterPosted(self, state, e):
        p = e.payload
        players = "\n".join(self.t(state, "ui.role.list.line", slot=r["slot"], name=self._plain(state, r["slot"]))
                            for r in p["roster"])
        roles = ", ".join(self.role_name(t) if has_role(t) else t for t in p["rolelist"])
        header = self.t(state, "game.rolelist.header", count=len(p["roster"])).replace("**", "")
        emb = {"title": self.t(state, "ui.roster.title"), "description": self.t(state, "game.start.public"),
               "color": "gold", "footer": self.t(state, "ui.game_logged"),
               "fields": [(self.t(state, "ui.roster.players"), players, False), (header, roles, False)]}
        return [Msg("town", embed=emb)]

    def _plain(self, state, slot) -> str:
        p = state.players.get(slot)
        return (p.display_name if p and p.display_name else f"Player {slot}")

    def _e_GameEnded(self, state, e):
        p = e.payload
        k = FACTION_KEYS.get(p["faction"], "draw")
        if p["faction"] == "ABORTED":
            desc = [self.t(state, "admin.aborted")]
        else:
            desc = [self.t(state, f"end.{k}")]
            if any(r["role_id"] == "jester" and r["slot"] in p["winners"] for r in p["roles"]):
                desc.append(self.t(state, "end.jester"))
        win = self.t(state, "ui.emoji.winner")
        lines = []
        for r in p["roles"]:
            line = self.t(state, "ui.end.line", player=r["slot"], role_id=r["role_id"], fate=self.fate(state, r["slot"]))
            if not r["alive"]:
                line += f" {self.t(state, 'ui.emoji.death')}"
            if r["slot"] in p["winners"]:
                line += f" {win}"
            lines.append(line)
        emb = {"title": self.t(state, f"ui.end.title.{k}"), "description": "\n".join(desc + [""] + lines),
               "color": "gold", "footer": self.t(state, "ui.end.footer", reason=p["reason"], day=p["days"])}
        return [Msg("town", embed=emb)]

    def fate(self, state, slot: int) -> str:
        """How a player ended, for the game-over list: survived, or who killed them and when."""
        p = state.players[slot]
        if p.alive or not p.death:
            return self.t(state, "ui.fate.survived")
        join = self.bank.render("ui.join.and", variant=0)
        causes = join.join(self.bank.render(f"ui.cause.{CAUSE_KEYS[x]}", variant=0) for x in p.death["causes"])
        kind, n = p.death["day_or_night"][0], int(p.death["day_or_night"][1:] or 0)
        when = self.t(state, "ui.when.night" if kind == "N" else "ui.when.day", night=n, day=n)
        return self.t(state, "ui.fate.died", causes=causes, when=when)

    def _e_RoleAssigned(self, state, e):
        return [Msg(e.audience, embed=self.card(state, e.payload), meta={"card": True})]

    def _e_PromptRequested(self, state, e):
        p = e.payload
        names = {s: self.name(state, s) for s in p["options"]}
        label = self.ability_label(state, p["role_id"], p["ability_id"], p.get("uses_left"))
        view = ("prompt", p, names, label, self.t(state, "ui.prompt.do_nothing"))
        return [Msg(e.audience, self.prompt(state, p), view=view, meta={"token": p["token"], "label": label})]

    def _e_JailStarted(self, state, e):
        return [Msg("jail", self.t(state, "jail.channel.open"))]

    def _e_JailEnded(self, state, e):
        return [Msg("jail", effect="purge_jail")]

    def _e_StatusChanged(self, state, e):
        if e.payload["status"] == C.PAUSED:
            return [Msg("commands", self.t(state, "admin.game_paused"), meta={"notice": True})]
        return []

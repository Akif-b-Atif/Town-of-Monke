"""Info command texts and player lookup (QOL-5, QOL-6). Pure: they take a Composer and a GameState."""
from __future__ import annotations

import re
from typing import Optional

from .. import constants as C
from ..compose import CAUSE_KEYS
from ..engine import voting
from ..engine.rolelist import default_rolelist
from ..roles.registry import has_role
from .registry import CommandSpec, available, usage

_PHASE_NAMES = {C.DAY_1: "day_1", C.DAY: "day", C.NOON: "noon", C.TRIAL_DEFENSE: "defense", C.TRIAL_VERDICT: "verdict",
                C.AFTERNOON: "afternoon", C.NIGHT: "night"}


def resolve_player(state, raw) -> Optional[int]:
    """A slot number ('3', '#3'), a mention or user id, or a name (exact, then unique prefix). None if no match."""
    raw = str(raw).strip()
    m = re.fullmatch(r"<@!?(\d+)>", raw)
    if m:
        return state.slot_of_user(int(m.group(1)))
    m = re.fullmatch(r"#?(\d{1,2})", raw)
    if m and int(m.group(1)) in state.players:
        return int(m.group(1))
    if raw.isdigit():
        return state.slot_of_user(int(raw))
    low = raw.lower()
    exact = [s for s, p in state.players.items() if p.display_name.lower() == low]
    if len(exact) == 1:
        return exact[0]
    pre = [s for s, p in state.players.items() if p.display_name.lower().startswith(low)] if low else []
    return pre[0] if len(pre) == 1 else None


def vote_targets(state, caller_slot: Optional[int], typed: str = "") -> list:
    """QOL-6: living players except yourself and anyone pardoned today, matching the typed text against name or slot.
    -> [(slot, label)] where the label is 'Maya (#3)'."""
    typed = (typed or "").strip().lower().lstrip("#")
    out = []
    for slot in state.alive_slots():
        if slot == caller_slot or slot in state.pardoned_today:
            continue
        name = state.players[slot].display_name or f"Player {slot}"
        if typed and typed not in name.lower() and typed not in str(slot):
            continue
        out.append((slot, f"{name} (#{slot})"))
    return out[:25]


def _phase_name(c, state) -> str:
    key = _PHASE_NAMES.get(state.phase)
    if key is None:
        return state.phase
    return c.t(state, f"ui.phasename.{key}", day=state.day_number, night=state.night_number)


def alive_text(c, state) -> str:
    alive = state.alive_slots()
    lines = [c.t(state, "info.alive.header", count=len(alive))] + [c.name(state, s) for s in alive]
    dead = sorted(s for s, p in state.players.items() if not p.alive)
    if dead:
        lines += ["", c.t(state, "info.alive.dead_header", count=len(dead))]
        for s in dead:
            p = state.players[s]
            d = p.death or {"causes": [], "day_or_night": "D0"}
            causes = c.bank.render("ui.join.and", variant=0).join(
                c.bank.render(f"ui.cause.{CAUSE_KEYS[x]}", variant=0) for x in d["causes"])
            day = re.sub(r"\D", "", d.get("day_or_night", "")) or "0"
            lines.append(c.t(state, "info.alive.dead_line", player=s, role_id=p.role_id, causes=causes, day=day))
    return "\n".join(lines)


def votes_tally(c, state) -> str:
    """The lines of the tally, grouped by target, most votes first."""
    groups: dict = {}
    for voter, target in state.votes.items():
        groups.setdefault(target, []).append(voter)
    if not groups:
        return c.t(state, "info.votes.none")
    rows = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    lines = [c.t(state, "info.votes.line", target=t, count=len(v), players=c.name_list(state, v)) for t, v in rows]
    lines.append(c.t(state, "info.votes.needed", needed=voting.threshold(len(state.alive_slots()))))
    return "\n".join(lines)


def votes_text(c, state) -> str:
    if state.phase != C.NOON or state.status != C.RUNNING:
        return c.t(state, "info.votes.closed")
    return votes_tally(c, state)


def tally_embed(c, state) -> dict:
    return {"title": c.t(state, "info.votes.header"), "description": votes_tally(c, state), "color": "system"}


def rolelist_text(c, state, n: Optional[int] = None) -> str:
    """The game's public role list, or the default list for `n` players."""
    if n is not None:
        tokens, head = default_rolelist(n), c.t(state, "info.rolelist.default", count=n)
    else:
        tokens, head = state.rolelist, c.t(state, "info.rolelist.header", count=len(state.rolelist))
    names = [c.role_name(t) if has_role(t) else t for t in tokens]
    return head + "\n" + ", ".join(names)


def timer_text(c, state) -> str:
    if state.status == C.ENDED:
        return c.t(state, "info.timer.over")
    name = _phase_name(c, state)
    if state.status == C.PAUSED:
        return c.t(state, "info.timer.paused", phase=name)
    return c.t(state, "info.timer.running", phase=name, rel=f"<t:{int(state.phase_ends_at)}:R>")


def help_text(c, state, specs: list, slot: Optional[int], is_admin: bool, is_manager: bool) -> str:
    groups = {"player": [], "admin": [], "manage_server": []}
    for sp in specs:
        if available(sp, state, slot, is_admin, is_manager):
            groups["player" if sp.who == "player" else "admin" if sp.who in ("admin", "admin_any") else "manage_server"].append(sp)
    lines = [c.t(state, "help.header")]
    for group, title in (("player", "help.group.player"), ("admin", "help.group.admin"), ("manage_server", "help.group.server")):
        if groups[group]:
            lines += ["", c.t(state, title)]
            lines += [c.t(state, "help.line", usage=usage(sp), text=c.t(state, sp.help_key)) for sp in groups[group]]
    if len(lines) == 1:
        return c.t(state, "help.nothing")
    return "\n".join(lines)

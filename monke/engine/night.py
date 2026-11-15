"""Night resolution: one fixed pipeline N0..N12 (spec section 8). Iteration is always in ascending
slot order. Attacks are evaluated simultaneously against pre-attack state."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .. import constants as C
from ..names import fmt_player
from ..roles import get_def, get_handler
from . import deaths
from . import events as E
from .state import Action

_VISIT_ABILITIES = {"investigate", "heal", "roleblock", "kill", "mafia_kill"}


@dataclass
class Visit:
    actor: int
    target: int
    ability: str


@dataclass
class Attack:
    attacker: int
    target: int
    level: int
    cause: str
    success: bool = False
    reason: str = ""


@dataclass
class NightResult:
    deaths: list = field(default_factory=list)  # [(slot, causes)]
    death_events: list = field(default_factory=list)


def _find(s, role_id: str):
    for p in s.players.values():
        if p.role_id == role_id and p.alive:
            return p
    return None


def resolve(s, events: list) -> NightResult:
    players = s.players
    notes: dict = {}

    def note(slot: int, text: str) -> None:
        notes.setdefault(slot, []).append(text)

    trace: list = []  # ARC-5: ordered, structured steps. Data only; the archive builder writes the English.

    def T(step: str, actor=None, target=None, outcome: str = "", **detail) -> None:
        trace.append({"step": step, "actor": actor, "target": target, "outcome": outcome, "detail": detail})

    def atk(attacker: int, target: int, cause: str) -> Attack:
        return Attack(attacker, target, get_def(players[attacker].role_id).attack_level, cause)

    # N0 Freeze: latest action per player; drop dead actors (except a Jester ghost) and bad targets.
    actions: dict = {}
    for slot, act in sorted(s.night_actions.items()):
        p = players.get(slot)
        if p is None:
            continue
        h = get_handler(p.role_id)
        ab = h.ability(act.ability_id)
        if ab is None or not h.can_act(s, p, ab):
            continue
        if act.target_slot is not None:
            t = players.get(act.target_slot)
            if t is None or not t.alive:
                continue
        actions[slot] = act

    # N1 Jail
    prisoner = s.prisoner_slot if (s.prisoner_slot is not None and players[s.prisoner_slot].alive) else None
    cancelled: set = set()
    jailor = _find(s, "jailor")
    exec_by: Optional[int] = None
    if prisoner is not None:
        cancelled.add(prisoner)
        if jailor and not jailor.state.get("jailor_exec_disabled"):
            a = actions.get(jailor.slot)
            if a and a.ability_id == "execute" and a.active:
                exec_by = jailor.slot
        T("jail", jailor.slot if jailor else None, prisoner, "jailed", execute=exec_by is not None)

    # N2 Roleblock
    sk_counter: dict = {}
    for slot, act in sorted(actions.items()):
        if act.ability_id != "roleblock" or act.target_slot is None:
            continue
        if slot in cancelled:
            T("roleblock", slot, act.target_slot, "actor_cancelled")
            continue
        t = act.target_slot
        if t == prisoner:
            T("roleblock", slot, t, "target_in_jail")
            continue  # the visit fails at N5
        tdef = get_def(players[t].role_id)
        if tdef.rb_immune:
            note(slot, "Your target's role cannot be roleblocked.")
            T("roleblock", slot, t, "immune")
            continue
        cancelled.add(t)
        T("roleblock", slot, t, "blocked")
        note(t, "Someone occupied your night. You were roleblocked!")
        if tdef.id == "serial_killer":
            sk_counter.setdefault(t, []).append(slot)

    # N3 Mafia kill chain (6.4): exactly one Mafia kill per night.
    gf, mf = _find(s, "godfather"), _find(s, "mafioso")
    order = None
    if gf and gf.slot in actions and gf.slot not in cancelled:
        a = actions[gf.slot]
        if a.ability_id == "order" and a.target_slot is not None:
            order = a.target_slot
    mf_ok = bool(mf) and mf.slot not in cancelled and not mf.state.get("inactive")
    executor = target = None
    if order is not None:
        executor, target = (mf.slot, order) if mf_ok else (gf.slot, order)
    elif mf_ok:
        a = actions.get(mf.slot)
        if a and a.ability_id == "kill" and a.target_slot is not None:
            executor, target = mf.slot, a.target_slot
    for p in (gf, mf):
        if p and p.slot in actions and actions[p.slot].ability_id in ("order", "kill"):
            del actions[p.slot]
    if executor is not None:
        actions[executor] = Action(executor, "mafia_kill", target)
    T("mafia_chain", executor, target,
      "godfather_order" if order is not None else ("mafioso_choice" if executor is not None else "no_kill"),
      godfather=gf.slot if gf else None, mafioso=mf.slot if mf else None, mafioso_available=mf_ok)

    # N4 Alerts
    alert: set = set()
    for slot, a in sorted(actions.items()):
        if a.ability_id == "alert" and a.active and slot not in cancelled:
            p = players[slot]
            if p.state.get("alerts_left", 0) > 0:
                p.state["alerts_left"] -= 1
                alert.add(slot)
                T("alert", slot, None, "on_alert")

    # N5 Visits (visits to the prisoner fail; Jailor and haunts are not visits)
    visits: list = []
    for slot, a in sorted(actions.items()):
        if slot in cancelled or a.ability_id not in _VISIT_ABILITIES or a.target_slot is None:
            continue
        if prisoner is not None and a.target_slot == prisoner:
            note(slot, "Your target was in jail.")
            T("visit", slot, a.target_slot, "target_in_jail", ability=a.ability_id)
            continue
        visits.append(Visit(slot, a.target_slot, a.ability_id))
        T("visit", slot, a.target_slot, "ok", ability=a.ability_id)

    # N6 Alert shots
    attacks: list = []
    for v in visits:
        if v.target in alert:
            attacks.append(atk(v.target, v.actor, C.VETERAN))

    # N7 Heals
    heals: dict = {}
    for v in visits:
        if v.ability == "heal":
            heals.setdefault(v.target, []).append(v.actor)
            T("heal", v.actor, v.target, "healing")
            if v.actor == v.target:
                players[v.actor].state["self_heals_left"] -= 1

    # N8 Attacks
    for v in visits:
        if v.ability == "mafia_kill":
            attacks.append(atk(v.actor, v.target, C.MAFIA_KILL))
        elif v.ability == "kill":
            attacks.append(atk(v.actor, v.target, C.SERIAL_KILLER))
    for sk, escorts in sorted(sk_counter.items()):
        for e in escorts:
            attacks.append(atk(sk, e, C.SERIAL_KILLER))
    if prisoner is not None and players[prisoner].role_id == "serial_killer" and jailor:
        attacks.append(atk(prisoner, jailor.slot, C.SERIAL_KILLER))
    if exec_by is not None:
        attacks.append(atk(exec_by, prisoner, C.EXECUTED))
    for slot, a in sorted(actions.items()):
        if a.ability_id == "haunt" and slot not in cancelled and a.target_slot is not None:
            attacks.append(atk(slot, a.target_slot, C.HAUNTED))
            players[slot].state["haunt_available"] = False

    died: dict = {}
    saved: set = set()
    attacked: set = set()
    for a in attacks:
        t = players[a.target]
        d = get_def(t.role_id)
        attacked.add(a.target)
        if a.level >= 3:
            ok = True
        elif heals.get(a.target):
            ok, a.reason = False, "saved"
            saved.add(a.target)
        else:
            defense = max(d.defense_level, d.alert_defense if a.target in alert else 0)
            ok = a.level > defense
            if not ok:
                a.reason = "strong"
        a.success = ok
        T("attack", a.attacker, a.target, "success" if ok else (a.reason or "failed"), cause=a.cause, level=a.level)
        if ok:
            causes = died.setdefault(a.target, [])
            if a.cause not in causes:
                causes.append(a.cause)

    # N9 Investigate
    for v in visits:
        if v.ability != "investigate":
            continue
        tdef = get_def(players[v.target].role_id)
        if players[v.actor].role_id == "consigliere":
            note(v.actor, f"Your target, {fmt_player(s, v.target)}, is the {tdef.name}.")
            T("investigate", v.actor, v.target, "role_revealed", role=tdef.name)
        else:
            note(v.actor, f"Your target, {fmt_player(s, v.target)}, seems {tdef.sheriff_result}.")
            T("investigate", v.actor, v.target, "result", role=tdef.name, result=tdef.sheriff_result)

    # N10 Feedback
    for a in attacks:
        if not a.success and a.level < 3:
            if a.reason == "saved":
                note(a.attacker, "Your target was attacked but healed, so they survived.")
            else:
                note(a.attacker, "Your target was too strong to kill.")
    for v in visits:
        if v.ability == "heal" and v.target in attacked:
            note(v.actor, "Your patient was attacked tonight!")
    for t in sorted(saved):
        if t not in died:
            note(t, "You were attacked but somebody nursed you back to health!")

    # N11 Apply deaths (simultaneous)
    result = NightResult()
    for slot in sorted(died):
        causes = died[slot]
        result.death_events.append(deaths.kill(s, slot, causes))
        result.deaths.append((slot, causes))
        T("death", slot, None, "died", causes=list(causes))
        if C.EXECUTED in causes and get_def(players[slot].role_id).alignment == C.TOWN and exec_by is not None:
            players[exec_by].state["jailor_exec_disabled"] = True
    for slot in sorted(players):
        p = players[slot]
        if p.alive and p.state.get("inactive"):
            result.death_events.append(deaths.kill(s, slot, [C.ABANDONED]))
            result.deaths.append((slot, [C.ABANDONED]))
            T("death", slot, None, "died", causes=[C.ABANDONED])

    events.append(E.ev(E.T.NIGHT_TRACE, E.ADMIN, night=s.night_number, steps=trace))
    if s.prisoner_slot is not None:
        events.append(E.ev(E.T.JAIL_ENDED, E.ADMIN, prisoner=s.prisoner_slot))
    s.night_actions = {}
    s.pending_jail_slot = None
    s.prisoner_slot = None

    for slot in sorted(notes):
        for text in notes[slot]:
            events.append(E.ev(E.T.PRIVATE, E.to_slot(slot), text=text))
    return result

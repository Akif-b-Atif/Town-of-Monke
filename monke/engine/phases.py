"""engine.handle(state, command, now) -> Result. Deterministic; no Discord, no I/O."""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass

from .. import constants as C
from ..errors import Rejected
from ..roles import get_def, get_handler
from ..roles.registry import has_role
from . import commands as K
from . import deaths, night, voting, wincheck
from . import events as E
from .rolelist import assign, generate_roles, validate_rolelist
from .rolecard import role_card
from .settings import Settings
from .state import Action, GameState, Player


@dataclass
class Result:
    state: GameState
    events: list


# ---------------------------------------------------------------- helpers
def _finalize(s: GameState, events: list) -> None:
    for e in events:
        s.event_log_seq += 1
        e.seq = s.event_log_seq


def _announce(events: list, text: str, audience: str = E.PUBLIC) -> None:
    events.append(E.ev(E.T.ANNOUNCEMENT, audience, text=text))


def _enter(s: GameState, phase: str, now: float, duration: float, events: list) -> None:
    s.phase = phase
    s.phase_id += 1
    s.phase_ends_at = now + duration
    events.append(E.ev(E.T.PHASE_CHANGED, phase=phase, phase_id=s.phase_id, ends_at=s.phase_ends_at,
                       day_number=s.day_number, night_number=s.night_number))


def prompts_for(s: GameState, slot: int) -> list:
    p = s.players.get(slot)
    if p is None or s.status != C.RUNNING:
        return []
    if s.phase == C.NIGHT:
        kind = C.KIND_NIGHT
    elif s.phase in C.DAY_PHASES:
        kind = C.KIND_DAY
    else:
        return []
    return get_handler(p.role_id).prompts(s, p, kind)


def prompt_event(s: GameState, p: Player, prompt) -> E.Event:
    cur_target = cur_active = None
    if prompt.ability_id == "jail":
        cur_target = s.pending_jail_slot
    else:
        a = s.night_actions.get(p.slot)
        if a and a.ability_id == prompt.ability_id:
            cur_target, cur_active = a.target_slot, a.active
    return E.ev(E.T.PROMPT, E.to_slot(p.slot), game_id=s.game_id, ability_id=prompt.ability_id,
                kind=prompt.kind, options=list(prompt.options), label=prompt.label,
                phase_kind=prompt.phase_kind, token=s.token_for(prompt.phase_kind),
                current_target=cur_target, current_active=cur_active)


def _emit_prompts(s: GameState, events: list) -> None:
    for slot in sorted(s.players):
        for pr in prompts_for(s, slot):
            events.append(prompt_event(s, s.players[slot], pr))


def _end_game(s: GameState, outcome: wincheck.Outcome, events: list) -> None:
    s.status = C.ENDED
    s.phase = C.PHASE_ENDED
    s.phase_id += 1
    s.winning_faction, s.end_reason = outcome.faction, outcome.reason
    s.winners = sorted(set(s.winners) | set(outcome.winners))
    roles = [{"slot": p.slot, "user_id": p.user_id, "role_id": p.role_id, "role": get_def(p.role_id).name,
              "alive": p.alive} for p in sorted(s.players.values(), key=lambda x: x.slot)]
    events.append(E.ev(E.T.GAME_ENDED, faction=outcome.faction, reason=outcome.reason,
                       winners=list(s.winners), roles=roles, days=s.day_number))


# ---------------------------------------------------------------- game creation
def new_game(game_id: str, guild_id: int, user_ids: list, tokens: list, settings: Settings,
             seed: int, strict: bool = True):
    """Validate and create a STARTING game. Emits one RoleAssigned event per player."""
    settings.validate(strict)
    if len(set(user_ids)) != len(user_ids):
        raise Rejected("Every player must be a distinct user.")
    canon = validate_rolelist(tokens, len(user_ids))
    rng = random.Random(seed)
    roles = generate_roles(canon, rng)
    assignment = assign(list(user_ids), roles, rng)
    s = GameState(game_id=game_id, guild_id=guild_id, settings=settings, rolelist=list(canon), rng_seed=seed)
    for slot, uid, role in assignment:
        s.players[slot] = Player(slot, uid, role)
    for p in s.players.values():
        p.state = get_handler(p.role_id).init_state(s, p)
    s.save_rng(rng)
    events = [E.ev(E.T.ROLE_ASSIGNED, E.to_slot(slot), **role_card(s, s.players[slot]))
              for slot in sorted(s.players)]
    _finalize(s, events)
    return s, events


# ---------------------------------------------------------------- phase transitions
def _begin(s: GameState, now: float, events: list) -> None:
    s.status = C.RUNNING
    s.day_number = 1
    names = [get_def(t).name if has_role(t) else t for t in s.rolelist]
    events.append(E.ev(E.T.ROSTER, roster=[{"slot": p.slot, "user_id": p.user_id}
                                           for p in sorted(s.players.values(), key=lambda x: x.slot)],
                       rolelist=names))
    _enter(s, C.DAY_1, now, s.settings.day_s / 2, events)
    _announce(events, "Day 1 begins. There is no voting on the first day. The Jailor may choose a prisoner.")
    _emit_prompts(s, events)


def _enter_noon(s: GameState, now: float, events: list, duration: float = None) -> None:
    s.votes = {}
    _enter(s, C.NOON, now, duration if duration is not None else s.settings.noon_s, events)
    need = voting.threshold(len(s.alive_slots()))
    _announce(events, f"Voting is open. {need} votes are needed to put someone on trial.")


def _enter_afternoon(s: GameState, now: float, events: list) -> None:
    s.votes, s.trial, s.paused_remaining = {}, None, None
    _enter(s, C.AFTERNOON, now, s.settings.day_s / 2, events)


def _start_night(s: GameState, now: float, events: list) -> None:
    s.night_number += 1
    s.votes, s.trial, s.paused_remaining = {}, None, None
    jailor = next((p for p in s.players.values() if p.role_id == "jailor"), None)
    pr = s.pending_jail_slot
    if pr is not None and not (s.players[pr].alive and jailor is not None and jailor.alive):
        pr = None
    s.prisoner_slot = pr
    s.night_actions = {}
    _enter(s, C.NIGHT, now, s.settings.night_s, events)
    _announce(events, f"Night {s.night_number} falls.")
    if pr is not None:
        events.append(E.ev(E.T.JAIL_STARTED, E.ADMIN, prisoner=pr, jailor=jailor.slot))
        events.append(E.ev(E.T.PRIVATE, E.to_slot(pr), text="You have been hauled off to jail! Speak with the Jailor in the Jail channel."))
        events.append(E.ev(E.T.PRIVATE, E.to_slot(jailor.slot),
                           text=f"You jailed Player {pr}. Messages you send me here are relayed anonymously."))
    _emit_prompts(s, events)


def _start_trial(s: GameState, defendant: int, now: float, events: list) -> None:
    s.paused_remaining = max(1.0, s.phase_ends_at - now)
    s.trial = {"defendant": defendant, "verdicts": {}}
    _enter(s, C.TRIAL_DEFENSE, now, s.settings.defense_s, events)
    events.append(E.ev(E.T.TRIAL_STARTED, defendant=defendant, defense_s=s.settings.defense_s))


def _start_verdict(s: GameState, now: float, events: list) -> None:
    _enter(s, C.TRIAL_VERDICT, now, s.settings.verdict_s, events)
    events.append(E.ev(E.T.VERDICT_OPENED, defendant=s.trial["defendant"], game_id=s.game_id,
                       token=str(s.phase_id), ends_at=s.phase_ends_at))


def _resolve_verdict(s: GameState, now: float, events: list) -> None:
    d = s.trial["defendant"]
    verdicts = s.trial["verdicts"]
    eligible = sorted(sl for sl, p in s.players.items() if p.alive and sl != d)
    votes = {sl: verdicts.get(sl, C.ABSTAIN) for sl in eligible}
    guilty = [sl for sl, v in votes.items() if v == C.GUILTY]
    innocent = [sl for sl, v in votes.items() if v == C.INNOCENT]
    events.append(E.ev(E.T.VERDICTS_REVEALED, defendant=d, votes=[{"slot": k, "verdict": v} for k, v in votes.items()],
                       guilty=len(guilty), innocent=len(innocent)))
    s.trial, s.votes = None, {}
    if len(guilty) > len(innocent):
        events.append(deaths.kill(s, d, [C.LYNCHED]))
        s.death_this_cycle = True
        p = s.players[d]
        if p.role_id == "jester":
            p.state["haunt_available"] = True
            p.state["haunt_targets"] = list(guilty)
            if d not in s.winners:
                s.winners.append(d)
            _announce(events, f"The Jester (Player {d}) wins! The game continues.")
        outcome = wincheck.check(s)
        if outcome:
            _end_game(s, outcome, events)
            return
        _enter_afternoon(s, now, events)
        return
    s.innocent_verdicts_today += 1
    s.pardoned_today.append(d)
    _announce(events, f"Player {d} was pardoned.")
    if s.innocent_verdicts_today >= 3:
        _announce(events, "The town has pardoned three people today. No more trials.")
        _enter_afternoon(s, now, events)
    else:
        rem = s.paused_remaining or 10.0
        s.paused_remaining = None
        _enter_noon(s, now, events, duration=max(1.0, rem))


def _dawn(s: GameState, now: float, events: list) -> None:
    res = night.resolve(s, events)
    if res.deaths:
        s.death_this_cycle = True
    s.quiet_cycles = 0 if s.death_this_cycle else s.quiet_cycles + 1
    s.death_this_cycle = False
    s.day_number += 1
    s.innocent_verdicts_today, s.pardoned_today, s.votes, s.trial = 0, [], {}, None
    _enter(s, C.DAY, now, s.settings.day_s, events)
    _announce(events, f"Day {s.day_number} dawns.")
    if res.death_events:
        events.extend(res.death_events)
    else:
        _announce(events, "Nobody died last night.")
    outcome = wincheck.check(s)
    if outcome is None and s.quiet_cycles >= s.settings.stalemate_cycles:
        outcome = wincheck.Outcome("DRAW", [], f"{s.quiet_cycles} full cycles passed with no deaths")
    if outcome:
        _end_game(s, outcome, events)
        return
    _emit_prompts(s, events)


def _advance(s: GameState, cmd: K.AdvancePhase, now: float, events: list) -> None:
    if s.status != C.RUNNING or cmd.expected_phase_id != s.phase_id:
        return  # stale timer: harmless
    if not cmd.force and now < s.phase_ends_at - 1.0:
        return  # a timer from before a pause/resume
    ph = s.phase
    if ph == C.DAY_1:
        _start_night(s, now, events)
    elif ph == C.DAY:
        _enter_noon(s, now, events)
    elif ph == C.NOON:
        _enter_afternoon(s, now, events)
    elif ph == C.TRIAL_DEFENSE:
        _start_verdict(s, now, events)
    elif ph == C.TRIAL_VERDICT:
        _resolve_verdict(s, now, events)
    elif ph == C.AFTERNOON:
        _start_night(s, now, events)
    elif ph == C.NIGHT:
        _dawn(s, now, events)


def _submit_action(s: GameState, cmd: K.SubmitAction, now: float, events: list) -> None:
    p = s.players.get(cmd.actor_slot)
    if p is None:
        raise Rejected("You are not in this game.")
    h = get_handler(p.role_id)
    ab = h.ability(cmd.ability_id)
    if ab is None:
        raise Rejected("Your role has no such ability.")
    h.validate(s, p, ab, cmd.target_slot, cmd.active)
    if ab.phase == C.KIND_DAY:
        if ab.id == "jail":
            s.pending_jail_slot = cmd.target_slot
    else:
        cleared = (ab.targeting == "toggle" and not cmd.active) or (ab.targeting == "single" and cmd.target_slot is None)
        if cleared:
            s.night_actions.pop(cmd.actor_slot, None)
        else:
            s.night_actions[cmd.actor_slot] = Action(cmd.actor_slot, ab.id, cmd.target_slot, cmd.active, now)
    events.append(E.ev(E.T.ACTION_RECORDED, E.to_slot(cmd.actor_slot), ability_id=ab.id,
                       target=cmd.target_slot, active=cmd.active))


# ---------------------------------------------------------------- entry point
def handle(state: GameState, cmd, now: float) -> Result:
    """Apply one command to a copy of `state`. Raises Rejected (state untouched) or returns the result."""
    s = copy.deepcopy(state)
    events: list = []
    if isinstance(cmd, K.AdvancePhase):
        _advance(s, cmd, now, events)
    elif isinstance(cmd, K.Abort):
        if s.status == C.ENDED:
            raise Rejected("The game has already ended.")
        _end_game(s, wincheck.Outcome("ABORTED", [], cmd.reason), events)
    elif s.status == C.ENDED:
        raise Rejected("The game has ended.")
    elif isinstance(cmd, K.BeginGame):
        if s.status != C.STARTING:
            raise Rejected("The game has already started.")
        _begin(s, now, events)
    elif isinstance(cmd, K.Resume):
        if s.status != C.PAUSED:
            raise Rejected("The game is not paused.")
        s.status = C.RUNNING
        s.phase_ends_at = now + (s.admin_pause_remaining or 1.0)
        s.admin_pause_remaining = None
        events.append(E.ev(E.T.STATUS, status=C.RUNNING))
        _announce(events, "The game has resumed.")
    elif isinstance(cmd, K.Pause):
        if s.status == C.RUNNING:
            s.admin_pause_remaining = max(1.0, s.phase_ends_at - now)
            s.status = C.PAUSED
            events.append(E.ev(E.T.STATUS, status=C.PAUSED, reason=cmd.reason))
            _announce(events, "The game is paused.")
    elif isinstance(cmd, K.Abandon):
        p = s.players.get(cmd.slot)
        if p is None:
            raise Rejected("No such player.")
        if p.alive and not p.state.get("inactive"):
            p.state["inactive"] = True
            events.append(E.ev(E.T.ANNOUNCEMENT, E.ADMIN, text=f"Player {cmd.slot} left the server and will die at the next dawn."))
    elif s.status == C.PAUSED:
        raise Rejected("The game is paused.")
    elif s.status == C.STARTING:
        raise Rejected("The game hasn't started yet.")
    elif isinstance(cmd, K.Vote):
        defendant = voting.cast_vote(s, cmd.voter_slot, cmd.target_slot, events)
        if defendant is not None:
            _start_trial(s, defendant, now, events)
    elif isinstance(cmd, K.Verdict):
        voting.cast_verdict(s, cmd.voter_slot, cmd.verdict, events)
    elif isinstance(cmd, K.SubmitAction):
        _submit_action(s, cmd, now, events)
    else:
        raise TypeError(f"Unknown command {cmd!r}")
    _finalize(s, events)
    return Result(s, events)

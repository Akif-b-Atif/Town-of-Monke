"""Simulator: plays full games with fake players who submit random valid inputs.
Usage: python -m monke.sim.cli --games 1000 --seed 0"""
from __future__ import annotations

import argparse
import json
import random

from .. import constants as C
from ..engine import Settings, handle, new_game, prompts_for
from ..engine import commands as K
from ..engine.state import GameState
from ..errors import Rejected
from ..roles import get_def

_POOL = ["RT", "RM", "TK", "TI", "TP", "TS", "MK", "MS", "NK", "NE"]


def random_tokens(n: int, rng: random.Random) -> list:
    from ..engine.rolelist import generate_roles, validate_rolelist
    while True:
        toks = ["Jailor", "Godfather"] + [rng.choice(_POOL) for _ in range(n - 2)]
        try:
            generate_roles(validate_rolelist(toks, n), random.Random(0))
            return toks
        except Rejected:
            continue


def _check_reasons(events: list) -> None:
    """TRN-1: every PhaseChanged event carries a reason code and a ctx dict."""
    for e in events:
        if e.type == "PhaseChanged":
            assert e.payload.get("reason"), f"phase change without a reason: {e.payload}"
            assert isinstance(e.payload.get("ctx"), dict), "phase change without ctx"


def _check_invariants(s: GameState) -> None:
    again = GameState.from_dict(json.loads(json.dumps(s.to_dict())))
    assert again == s, "state does not round-trip through JSON"
    for p in s.players.values():
        if not p.alive:
            assert p.death and p.death["causes"], f"dead player {p.slot} has no cause"


class _Driver:
    """Applies commands for the simulator. Every emitted event is rendered through the real text system with a
    strict bank, so a missing key or a bad placeholder fails the run (TXT-5). Reports to the debug sink (DBG-1)."""

    def __init__(self, sink=None, seed: int = 0):
        from ..compose import Composer
        from ..text.bank import default_bank
        self.sink = sink
        self.composer = Composer(default_bank(rng=random.Random(seed), strict=True))

    def render(self, before, after, cmd, events, now) -> None:
        rendered = {e.seq: self.composer.compose(after, e) for e in events}
        if self.sink is not None:
            self.sink.commit(before, after, cmd, events, now=now, deliver=True, rendered=rendered)

    def __call__(self, s: GameState, cmd, now: float) -> GameState:
        res = handle(s, cmd, now)
        self.render(s, res.state, cmd, res.events, now)
        return res.state


def _play(s: GameState, rng: random.Random, now: float, drv: "_Driver" = None) -> GameState:
    drv = drv or _Driver()
    if s.phase in C.DAY_PHASES and s.phase not in (C.NOON, C.TRIAL_VERDICT):
        for slot in sorted(s.players):
            for pr in prompts_for(s, slot):
                if rng.random() < 0.5:
                    s = drv(s, K.SubmitAction(slot, pr.ability_id, rng.choice(pr.options)), now)
    elif s.phase == C.NIGHT:
        # a dead non-ghost player must be unable to act
        for p in s.players.values():
            if not p.alive and p.role_id != "jester":
                ab = get_def(p.role_id).abilities[0]
                try:
                    handle(s, K.SubmitAction(p.slot, ab.id, s.alive_slots()[0]), now)
                    raise AssertionError("dead player was allowed to act")
                except Rejected:
                    pass
                break
        for slot in sorted(s.players):
            for pr in prompts_for(s, slot):
                r = rng.random()
                if r < 0.15:
                    continue
                if pr.kind == "toggle":
                    s = drv(s, K.SubmitAction(slot, pr.ability_id, None, active=rng.random() < 0.5), now)
                else:
                    s = drv(s, K.SubmitAction(slot, pr.ability_id, rng.choice(pr.options)), now)
    elif s.phase == C.NOON:
        if rng.random() < 0.7:
            alive = s.alive_slots()
            focus = rng.choice([a for a in alive if a not in s.pardoned_today] or alive)
            for v in alive:
                if s.phase != C.NOON:
                    break
                if v != focus and focus not in s.pardoned_today and rng.random() < 0.8:
                    s = drv(s, K.Vote(v, focus), now)
    elif s.phase == C.TRIAL_VERDICT:
        d = s.trial["defendant"]
        bias = rng.random()
        for v in s.alive_slots():
            if v != d:
                verdict = C.GUILTY if rng.random() < bias else rng.choice([C.INNOCENT, C.ABSTAIN])
                s = drv(s, K.Verdict(v, verdict), now)
    return s


def run_game(seed: int, n: int = None, sink=None) -> GameState:
    rng = random.Random(seed)
    n = n or rng.randint(C.MIN_PLAYERS, C.MAX_PLAYERS)
    tokens = random_tokens(n, rng)
    names = {1000 + i: f"Sim{i + 1}" for i in range(n)}
    s, role_events = new_game(f"{seed:06x}", 1, [1000 + i for i in range(n)], tokens, Settings(), seed,
                              names=names)
    drv = _Driver(sink, seed)
    if sink is not None:
        sink.game_started(s, now=0.0)
    drv.render(s, s, K.BeginGame(), role_events, 0.0)
    assert sum(p.role_id == "jailor" for p in s.players.values()) == 1
    assert sum(p.role_id == "godfather" for p in s.players.values()) == 1
    now = 0.0
    res = handle(s, K.BeginGame(), now)
    drv.render(s, res.state, K.BeginGame(), res.events, now)
    s = res.state
    _check_reasons(res.events)
    steps = 0
    while s.status != C.ENDED:
        steps += 1
        assert steps < 3000, "game did not terminate"
        s = _play(s, rng, now, drv)
        now = s.phase_ends_at
        res = handle(s, K.AdvancePhase(s.phase_id), now)
        drv.render(s, res.state, K.AdvancePhase(s.phase_id), res.events, now)
        s = res.state
        _check_reasons(res.events)
        _check_invariants(s)
    assert s.winning_faction in ("TOWN", "MAFIA", "SERIAL_KILLER", "DRAW")
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--players", type=int, default=None, help="fixed player count (default: random 5-20)")
    ap.add_argument("--debug", action="store_true", help="print every event of every game, like the bot's debug console")
    ap.add_argument("--debug-chat", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    sink = None
    if a.debug:
        from ..debug import make_sink
        sink = make_sink(True)
    tally: dict = {}
    for i in range(a.games):
        s = run_game(a.seed + i, a.players, sink)
        tally[s.winning_faction] = tally.get(s.winning_faction, 0) + 1
    print(f"{a.games} games OK. Outcomes: {tally}")


if __name__ == "__main__":
    main()

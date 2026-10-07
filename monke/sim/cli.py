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


def _check_invariants(s: GameState) -> None:
    again = GameState.from_dict(json.loads(json.dumps(s.to_dict())))
    assert again == s, "state does not round-trip through JSON"
    for p in s.players.values():
        if not p.alive:
            assert p.death and p.death["causes"], f"dead player {p.slot} has no cause"


def _play(s: GameState, rng: random.Random, now: float) -> GameState:
    if s.phase in C.DAY_PHASES and s.phase not in (C.NOON, C.TRIAL_VERDICT):
        for slot in sorted(s.players):
            for pr in prompts_for(s, slot):
                if rng.random() < 0.5:
                    s = handle(s, K.SubmitAction(slot, pr.ability_id, rng.choice(pr.options)), now).state
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
                    s = handle(s, K.SubmitAction(slot, pr.ability_id, None, active=rng.random() < 0.5), now).state
                else:
                    s = handle(s, K.SubmitAction(slot, pr.ability_id, rng.choice(pr.options)), now).state
    elif s.phase == C.NOON:
        if rng.random() < 0.7:
            alive = s.alive_slots()
            focus = rng.choice([a for a in alive if a not in s.pardoned_today] or alive)
            for v in alive:
                if s.phase != C.NOON:
                    break
                if v != focus and focus not in s.pardoned_today and rng.random() < 0.8:
                    s = handle(s, K.Vote(v, focus), now).state
    elif s.phase == C.TRIAL_VERDICT:
        d = s.trial["defendant"]
        bias = rng.random()
        for v in s.alive_slots():
            if v != d:
                verdict = C.GUILTY if rng.random() < bias else rng.choice([C.INNOCENT, C.ABSTAIN])
                s = handle(s, K.Verdict(v, verdict), now).state
    return s


def run_game(seed: int, n: int = None) -> GameState:
    rng = random.Random(seed)
    n = n or rng.randint(C.MIN_PLAYERS, C.MAX_PLAYERS)
    tokens = random_tokens(n, rng)
    s, _ = new_game(f"sim{seed}", 1, [1000 + i for i in range(n)], tokens, Settings(), seed)
    assert sum(p.role_id == "jailor" for p in s.players.values()) == 1
    assert sum(p.role_id == "godfather" for p in s.players.values()) == 1
    now = 0.0
    s = handle(s, K.BeginGame(), now).state
    steps = 0
    while s.status != C.ENDED:
        steps += 1
        assert steps < 3000, "game did not terminate"
        s = _play(s, rng, now)
        now = s.phase_ends_at
        s = handle(s, K.AdvancePhase(s.phase_id), now).state
        _check_invariants(s)
    assert s.winning_faction in ("TOWN", "MAFIA", "SERIAL_KILLER", "DRAW")
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    tally: dict = {}
    for i in range(a.games):
        s = run_game(a.seed + i)
        tally[s.winning_faction] = tally.get(s.winning_faction, 0) + 1
    print(f"{a.games} games OK. Outcomes: {tally}")


if __name__ == "__main__":
    main()

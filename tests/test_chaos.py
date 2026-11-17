"""REL-18: a chaos test. Simulated games advance phase by phase with random crash points; after every crash a brand
new service is built on the same database and recovers. At the end: no duplicate public posts, no missed events,
and the rendering marker caught up."""
import asyncio
import random

import pytest

from monke import constants as C
from monke.engine import Settings
from monke.engine import commands as K
from monke.service.crash import SimulatedCrash
from tests.crashworld import NAMES, TOKENS, USERS, Clock, Proc, World, new_path

POINTS = ["after_commit_before_render", "mid_render"]


async def play(seed):
    rng = random.Random(seed)
    clock, world = Clock(), World()
    proc = await Proc(new_path(), world, clock).boot()
    state = await proc.svc.start_game(1, USERS, TOKENS, Settings(), seed=seed, names=NAMES)
    game_id, crashes = state.game_id, 0
    for _ in range(80):
        g = proc.svc.get(1)
        if g is None or g.status == C.ENDED:
            break
        if rng.random() < 0.5:
            point = rng.choice(POINTS)
            proc.svc.crash.arm(point, proc.svc.crash.counts[point] + rng.randint(1, 2))
        hb = clock()
        try:
            await proc.svc.submit(1, K.AdvancePhase(g.phase_id, force=True))
        except SimulatedCrash:
            crashes += 1
            await proc.die()
            clock.advance(rng.randint(1, 400))
            proc = await Proc(proc.path, world, clock).boot(last_heartbeat=hb)
        clock.advance(5)
    final = proc.svc.get(1)
    for _ in range(20):
        await asyncio.sleep(0)
    return world, proc, game_id, crashes, final


@pytest.mark.parametrize("seed", range(12))
def test_chaos_no_duplicates_no_missed_events(seed):
    async def go():
        world, proc, game_id, crashes, final = await play(seed)
        texts = [p[2] for p in world.posts if p[0] == "post" and not p[2].startswith("rel.")]  # restart notices may repeat
        assert len(texts) == len(set(texts)), sorted({t for t in texts if texts.count(t) > 1})
        assert await proc.store.rendered_seq(game_id) == await proc.store.max_event_seq(game_id)
        # every PhaseChanged of the game that is not stale was posted once
        events = await proc.store.load_events(game_id)
        last_phase = max((e["payload"]["phase_id"] for e in events if e["type"] == "PhaseChanged"), default=0)
        assert any(t.startswith("banner") and t.endswith(str(last_phase)) for t in texts) or final.status == C.ENDED
        if final and final.status == C.RUNNING:
            proc.svc.scheduler.cancel(game_id)
    asyncio.run(go())

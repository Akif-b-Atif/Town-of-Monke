"""python -m monke.sim.replay data/game.json (POST-4): re-run the seed and the command log through the engine and check
that the events are identical, printing the first divergence. This is the main tool for bug reports: any reported game
can be reproduced from its archive (the zip holds data/game.json)."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from ..engine import Settings, handle, new_game
from ..engine import commands as K
from ..errors import Rejected

SKIP_TYPES = {"AdminAction"}  # appended by the service, not by the engine


def _canon(e: dict) -> str:
    p = json.loads(json.dumps(e["payload"], sort_keys=True))
    ctx = p.get("ctx")
    if isinstance(ctx, dict):
        ctx.pop("admin_name", None)  # an admin's name is not kept in the command log
    return json.dumps({"type": e["type"], "audience": e.get("audience"), "payload": p}, sort_keys=True)


def replay(data: dict) -> Optional[str]:
    """-> None if the replay matches, otherwise a description of the first divergence."""
    stored = [e for e in data["events"] if e["type"] not in SKIP_TYPES]
    created = next((e for e in stored if e["type"] == "GameCreated"), None)
    if created is None:
        return "this archive has no GameCreated event (it was written before v1.1), so it cannot be replayed"
    c = created["payload"]
    state, events = new_game(c["game_id"], c["guild_id"], c["user_ids"], c["tokens"], Settings(**c["settings"]),
                             c["seed"], strict=False, names={int(k): v for k, v in c["names"].items()},
                             resolved=c["resolved"])
    produced = [{"type": e.type, "payload": e.payload, "audience": e.audience} for e in events
                if e.type == "GameCreated"]  # private role cards are not part of the stored log
    for row in data["commands"]:
        if not row.get("accepted", True):
            continue
        try:
            cmd = getattr(K, row["type"])(**(row.get("payload") or {}))
            res = handle(state, cmd, row["ts_ms"] / 1000)
        except Rejected as e:
            return f"command {row['type']} at {row['ts_ms']} was accepted in the game but rejected in the replay ({e.key})"
        state = res.state
        produced += [{"type": e.type, "payload": e.payload, "audience": e.audience} for e in res.events]
    for i, (want, got) in enumerate(zip(stored, produced)):
        if _canon(want) != _canon(got):
            return (f"first divergence at event {i} ({want['type']}):\n  archive: {_canon(want)}\n  replay:  {_canon(got)}")
    if len(stored) != len(produced):
        return f"the archive has {len(stored)} events but the replay produced {len(produced)}"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m monke.sim.replay", description=__doc__.split("\n")[0])
    ap.add_argument("path", help="data/game.json from an archive zip")
    a = ap.parse_args(argv)
    with open(a.path, encoding="utf-8") as f:
        data = json.load(f)
    problem = replay(data)
    if problem:
        print("DIVERGED:", problem)
        return 1
    print(f"OK: {len(data['events'])} events and {len(data['commands'])} commands replay identically "
          f"(game {data['game_id']}, seed {data['seed']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

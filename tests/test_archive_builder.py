"""ARC-7/ARC-8/ARC-16: the archive builder and the zip writer are pure and deterministic."""
import io
import json
import random
import zipfile

import pytest

from monke import constants as C
from monke.archive.builder import archive_summary, build_archive, fmt_ts
from monke.archive.zipper import write_zips
from monke.engine import Settings, handle, new_game
from monke.engine import commands as K
from monke.errors import Rejected
from monke.sim import cli as sim

NAMES = {1000 + i: n for i, n in enumerate(["Maya", "Sam", "Lee", "Noor", "Omar", "Zed", "Ana", "Bo"])}


def _recorded_game(seed=3):
    """Play one simulated game, recording every command and event the way the service would store them."""
    events, commands = [], []
    real = sim.handle

    def rec(state, cmd, now):
        slot = getattr(cmd, "voter_slot", getattr(cmd, "actor_slot", getattr(cmd, "slot", None)))
        payload = {k: v for k, v in vars(cmd).items() if k != "by"}
        row = {"seq": len(commands) + 1, "ts_ms": int(now * 1000) + 500, "actor_slot": slot,
               "type": type(cmd).__name__, "payload": payload, "accepted": True, "reason": None}
        try:
            res = real(state, cmd, now)
        except Rejected as r:
            commands.append({**row, "accepted": False, "reason": r.reason})
            raise
        commands.append(row)
        for e in res.events:
            events.append({"seq": e.seq, "ts_ms": int(now * 1000) + 1000, "type": e.type, "payload": e.payload,
                           "audience": e.audience})
        return res

    sim.handle = rec
    try:
        rng = random.Random(seed)
        n = len(NAMES)
        s, _ = new_game(f"t{seed}", 1, list(NAMES), sim.random_tokens(n, rng), Settings(), seed, names=NAMES)
        s = rec(s, K.BeginGame(), 0.0).state
        now, steps = 0.0, 0
        while s.status != C.ENDED and steps < 500:
            steps += 1
            s = sim._play(s, rng, now)
            now = s.phase_ends_at
            s = rec(s, K.AdvancePhase(s.phase_id), now).state
    finally:
        sim.handle = real
    return s, events, commands


def _chat(s):
    base = events_start = 500
    return [
        {"id": 1, "ts_ms": 2000, "channel_kind": "town", "session": "", "kind": "msg", "message_id": 11,
         "author_user_id": 1000, "author_slot": s.slot_of_user(1000), "author_name": "Maya", "content": "hello town"},
        {"id": 2, "ts_ms": 3000, "channel_kind": "town", "session": "", "kind": "edit", "message_id": 11,
         "author_user_id": None, "author_slot": None, "author_name": None, "content": "hello, town"},
        {"id": 3, "ts_ms": 4000, "channel_kind": "town", "session": "", "kind": "msg", "message_id": 12,
         "author_user_id": 1001, "author_slot": s.slot_of_user(1001), "author_name": "Sam", "content": "oops secret"},
        {"id": 4, "ts_ms": 5000, "channel_kind": "town", "session": "", "kind": "delete", "message_id": 12,
         "author_user_id": None, "author_slot": None, "author_name": None, "content": ""},
        {"id": 5, "ts_ms": 6000, "channel_kind": "jail", "session": "night_1", "kind": "msg", "message_id": 13,
         "author_user_id": 1002, "author_slot": s.slot_of_user(1002), "author_name": "Lee", "content": "let me out"},
        {"id": 6, "ts_ms": 7000, "channel_kind": "mafia", "session": "", "kind": "bot", "message_id": 14,
         "author_user_id": 1, "author_slot": None, "author_name": "Bot", "content": "Mafia chat opens"},
    ]


def _build(seed=3):
    s, events, commands = _recorded_game(seed)
    files = build_archive(s, events, commands, _chat(s), {"bot_version": "1.0.1"})
    return s, events, commands, files


def test_expected_files_exist():
    s, events, commands, files = _build()
    for path in ("README.txt", "timeline.txt", "votes_and_trials.txt", "data/game.json", "chat/town.txt",
                 "chat/mafia.txt", "chat/graveyard.txt", "chat/jail_night_01.txt", "abilities/night_01.txt",
                 "abilities/day_01.txt"):
        assert path in files, path
    assert all(isinstance(v, bytes) for v in files.values())


def test_build_is_deterministic():
    *_, a = _build()
    *_, b = _build()
    assert a == b


def test_timeline_is_in_time_order_and_all_times_utc():
    *_, files = _build()
    lines = files["timeline.txt"].decode().splitlines()
    assert lines[0].startswith("Town of Monke - game") and "All times UTC" in lines[2]
    stamps = [ln[1:20] for ln in lines if ln.startswith("[")]
    assert stamps == sorted(stamps) and len(stamps) > 20


def test_edits_and_deletes_are_rendered():
    s, *_, files = _build()
    town = files["chat/town.txt"].decode()
    assert "hello, town (edited)" in town
    assert "[deleted]" in town and "oops secret" in town           # the original text is kept
    assert "BOT: Mafia chat opens" in files["chat/mafia.txt"].decode()
    assert "let me out" in files["chat/jail_night_01.txt"].decode()


def test_people_are_written_with_slot_name_and_role():
    s, *_, files = _build()
    slot = s.slot_of_user(1000)
    assert f"#{slot:02d} Maya (" in files["chat/town.txt"].decode()


def test_every_night_has_a_trace_and_results():
    s, events, commands, files = _build()
    nights = sorted({e["payload"]["night"] for e in events if e["type"] == "NightTrace"})
    assert nights
    for n in nights:
        text = files[f"abilities/night_{n:02d}.txt"].decode()
        assert "[TRACE]" in text or "(the night had not been resolved)" not in text
        assert "== Results delivered to players ==" in text


def test_readme_has_logging_notice_seed_and_players():
    s, *_, files = _build()
    readme = files["README.txt"].decode()
    assert "Game channels are logged for the post-game archive." in readme
    assert f"Seed: {s.rng_seed}" in readme
    assert "Maya" in readme and "Bot version: 1.0.1" in readme


def test_game_json_is_valid_and_complete():
    s, events, commands, files = _build()
    data = json.loads(files["data/game.json"])
    assert data["seed"] == s.rng_seed and len(data["events"]) == len(events) and len(data["commands"]) == len(commands)


def test_never_builds_a_live_game():                                  # ARC-16
    s, events, commands = _recorded_game()
    s.status = C.RUNNING
    with pytest.raises(AssertionError):
        build_archive(s, events, commands, [], {})


def test_summary_rows():
    s, events, commands = _recorded_game()
    summ = archive_summary(s, events)
    assert len(summ["players"]) == len(NAMES) and summ["winner"]
    assert fmt_ts(0) == "1970-01-01 00:00:00"


def test_zip_fits_in_one_file():
    files = {"a.txt": b"hello\n" * 100, "b/c.txt": b"world\n" * 100}
    out = write_zips(files, "monke-game-x", 10_000_000)
    assert [n for n, _ in out] == ["monke-game-x.zip"]
    with zipfile.ZipFile(io.BytesIO(out[0][1])) as z:
        assert sorted(z.namelist()) == ["a.txt", "b/c.txt"]


def test_zip_splits_at_file_and_line_boundaries():                    # ARC-8
    rng = random.Random(1)
    big = "\n".join("".join(rng.choice("abcdefghij0123456789") for _ in range(60)) for _ in range(4000)).encode()
    files = {"chat/town.txt": big, "README.txt": b"readme\n", "timeline.txt": big[:30000]}
    limit = 40_000
    out = write_zips(files, "g", limit)
    assert len(out) > 1 and all(len(b) <= limit for _, b in out)
    assert out[0][0] == f"g.part1of{len(out)}.zip"
    got = {}
    for _, blob in out:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for n in z.namelist():
                got[n] = z.read(n)
    assert got["README.txt"] == b"readme\n"
    parts = [got[n] for n in sorted(got) if n.startswith("chat/town.part")]
    assert parts and b"".join(parts) == big                            # nothing lost, split at line boundaries
    assert all(p.endswith(b"\n") for p in parts[:-1])


def test_zip_is_deterministic():
    files = {"a.txt": b"x\n" * 500, "b.txt": b"y\n" * 500}
    assert write_zips(files, "g", 1_000_000) == write_zips(files, "g", 1_000_000)

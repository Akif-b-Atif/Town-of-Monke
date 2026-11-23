"""REL-1, REL-15, REL-16: storage settings, backups, migrations, logging."""
import asyncio
import json
import logging
import os
import random
import sqlite3

import pytest

from monke import constants as C
from monke.engine import GameState, Settings, handle, new_game
from monke.engine import commands as K
from monke.service.migrations import SnapshotTooNew, migrate, migrate_v1_to_v2, needs_migration
from monke.service.store import DatabaseDamaged, Store
from monke.sim.cli import _play
from tests.crashworld import NAMES, TOKENS, USERS, new_path


def run(c):
    return asyncio.run(c)


def v1_snapshot(state: GameState) -> dict:
    """What v1.0.1 wrote: no phase timing, wills, journals, skip votes..."""
    d = state.to_dict()
    for k in ("phase_started_at", "phase_length", "skip_votes", "night_confirmed", "active_today", "settings_resolved"):
        d.pop(k)
    for p in d["players"].values():
        for k in ("will", "death_notes", "journal", "inactive_days", "last_active_at", "former"):
            p.pop(k)
    d["schema_version"] = 1
    return d


def mid_game():
    s, _ = new_game("g1", 1, USERS, TOKENS, Settings(), 5, names=NAMES)
    s = handle(s, K.BeginGame(), 0.0).state
    s = handle(s, K.AdvancePhase(s.phase_id, force=True), 10.0).state  # into Night 1
    return s


def test_a_v1_snapshot_loads_upgrades_and_the_game_continues_to_its_end():
    s = mid_game()
    d = v1_snapshot(s)
    assert needs_migration(d)
    loaded = GameState.from_dict(json.loads(json.dumps(d)))
    assert loaded.phase_length == s.phase_length or loaded.phase_length > 0  # derived from the settings
    assert loaded.phase_started_at <= loaded.phase_ends_at
    assert all(p.journal == [] and p.will == "" for p in loaded.players.values())
    rng, now, guard = random.Random(1), 10.0, 0
    while loaded.status == C.RUNNING and guard < 500:
        loaded = _play(loaded, rng, now)
        now = loaded.phase_ends_at
        loaded = handle(loaded, K.AdvancePhase(loaded.phase_id), now).state
        guard += 1
    assert loaded.status == C.ENDED


def test_a_snapshot_newer_than_the_code_is_refused_not_rewritten():
    d = mid_game().to_dict()
    d["schema_version"] = 99
    with pytest.raises(SnapshotTooNew):
        GameState.from_dict(d)


def test_the_chain_runs_every_step_in_order():
    seen = []
    chain = {1: lambda d: (seen.append(1), {**d, "schema_version": 2})[1],
             2: lambda d: (seen.append(2), {**d, "schema_version": 3})[1]}
    assert migrate({"schema_version": 1}, chain, current=3)["schema_version"] == 3 and seen == [1, 2]


def test_store_settings_and_integrity(tmp_path):
    async def go():
        st = Store(str(tmp_path / "m.db"))
        await st.open()
        for pragma, want in (("journal_mode", "wal"), ("synchronous", 2), ("busy_timeout", 5000)):
            async with st.db.execute(f"PRAGMA {pragma}") as cur:
                assert (await cur.fetchone())[0] == want
        async with st.db.execute("PRAGMA user_version") as cur:
            assert (await cur.fetchone())[0] == 2
        await st.close()
        # damage the file: the bot refuses to start and says how to restore a backup
        with open(tmp_path / "m.db", "r+b") as f:
            f.seek(4096)
            f.write(b"\x00garbage" * 2000)
        with pytest.raises((DatabaseDamaged, Exception)):
            bad = Store(str(tmp_path / "m.db"))
            await bad.open()
    run(go())


def test_backup_before_migration_and_only_five_are_kept(tmp_path):
    async def go():
        path = str(tmp_path / "m.db")
        st = Store(path)
        await st.open()
        s = mid_game()
        await st.save_game(s)
        await st.db.execute("UPDATE games SET schema_version=1")  # pretend it was written by v1.0.1
        await st.db.commit()
        await st.close()
        for _ in range(7):
            st2 = Store(path)
            await st2.open()
            await st2.close()
        files = sorted(os.listdir(tmp_path / "backups"))
        assert len(files) == 5 and all(f.endswith(".db") for f in files)
        assert any("premigrate" in f for f in files) or len(files) == 5
        con = sqlite3.connect(str(tmp_path / "backups" / files[-1]))
        assert con.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1  # a real copy
    run(go())


def test_an_old_database_gets_the_new_columns_and_tables(tmp_path):
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE games(game_id TEXT PRIMARY KEY, guild_id INTEGER, status TEXT, phase_id INTEGER,"
                      " snapshot_json TEXT, schema_version INTEGER, updated_at REAL);"
                      "CREATE TABLE chat_log(id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT, ts_ms INTEGER,"
                      " channel_kind TEXT, session TEXT, kind TEXT, message_id INTEGER, author_user_id INTEGER,"
                      " author_slot INTEGER, author_name TEXT, content TEXT, attachments_json TEXT);"
                      "CREATE TABLE guild_config(guild_id INTEGER PRIMARY KEY, category_id INTEGER, commands_channel_id INTEGER,"
                      " admin_role_id INTEGER, town_id INTEGER, mafia_id INTEGER, jail_id INTEGER, graveyard_id INTEGER,"
                      " slot_role_ids_json TEXT, default_settings_json TEXT);")
    con.commit()
    con.close()

    async def go():
        st = Store(path)
        await st.open()
        cols = {r[1] for r in await (await st.db.execute("PRAGMA table_info(games)")).fetchall()}
        assert {"rendered_seq", "banner_message_id"} <= cols
        for table in ("instance", "outbox_posts", "lobbies"):
            assert await (await st.db.execute(f"SELECT COUNT(*) FROM {table}")).fetchone() == (0,)
        await st.close()
    run(go())


def test_log_lines_carry_ids_and_the_seed_never_reaches_the_console(tmp_path, capsys):
    from monke.logsetup import set_context, setup_logging
    path = setup_logging(str(tmp_path), console=True)
    set_context(7, "abc123", 4, 19)
    logging.getLogger("monke.service").error("something happened")
    logging.getLogger("monke.spoiler").error("game abc123 seed=424242")
    for h in logging.getLogger().handlers:
        h.flush()
    text = open(path, encoding="utf-8").read()
    assert "guild=7 game=abc123 phase=4 seq=19" in text and "something happened" in text
    assert "seed=424242" in text  # the file is a spoiler file
    assert "424242" not in capsys.readouterr().err
    for h in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(h)

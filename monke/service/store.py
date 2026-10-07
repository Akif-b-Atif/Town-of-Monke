"""SQLite persistence (aiosqlite): guild_config, games (snapshots), game_events (append-only log)."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

import aiosqlite

from ..engine.state import GameState

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config(
  guild_id INTEGER PRIMARY KEY, category_id INTEGER, commands_channel_id INTEGER, admin_role_id INTEGER,
  town_id INTEGER, mafia_id INTEGER, jail_id INTEGER, graveyard_id INTEGER,
  slot_role_ids_json TEXT, default_settings_json TEXT);
CREATE TABLE IF NOT EXISTS games(
  game_id TEXT PRIMARY KEY, guild_id INTEGER, status TEXT, phase_id INTEGER,
  snapshot_json TEXT, schema_version INTEGER, updated_at REAL);
CREATE TABLE IF NOT EXISTS game_events(
  game_id TEXT, seq INTEGER, ts REAL, type TEXT, payload_json TEXT, audience TEXT,
  PRIMARY KEY(game_id, seq));
"""


@dataclass
class GuildConfig:
    guild_id: int
    category_id: int
    commands_channel_id: int
    admin_role_id: int
    town_id: int
    mafia_id: int
    jail_id: int
    graveyard_id: int
    slot_role_ids: list = field(default_factory=list)  # index 0 = slot 1
    default_settings: dict = field(default_factory=dict)


class Store:
    def __init__(self, path: str):
        self.path = path
        self.db: Optional[aiosqlite.Connection] = None

    async def open(self) -> None:
        self.db = await aiosqlite.connect(self.path)
        await self.db.executescript(SCHEMA)
        await self.db.commit()

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    # ---- games ----
    async def save_game(self, state: GameState, events: list = (), db_status: Optional[str] = None) -> None:
        """Snapshot and events in ONE transaction."""
        now = time.time()
        await self.db.execute(
            "INSERT INTO games(game_id,guild_id,status,phase_id,snapshot_json,schema_version,updated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(game_id) DO UPDATE SET status=excluded.status, "
            "phase_id=excluded.phase_id, snapshot_json=excluded.snapshot_json, updated_at=excluded.updated_at",
            (state.game_id, state.guild_id, db_status or state.status, state.phase_id,
             json.dumps(state.to_dict()), 1, now))
        for e in events:
            await self.db.execute(
                "INSERT OR IGNORE INTO game_events(game_id,seq,ts,type,payload_json,audience) VALUES(?,?,?,?,?,?)",
                (state.game_id, e.seq, now, e.type, json.dumps(e.payload), e.audience))
        await self.db.commit()

    async def load_games(self, statuses: tuple) -> list:
        q = ",".join("?" * len(statuses))
        async with self.db.execute(f"SELECT snapshot_json FROM games WHERE status IN ({q})", statuses) as cur:
            rows = await cur.fetchall()
        return [GameState.from_dict(json.loads(r[0])) for r in rows]

    async def delete_game(self, game_id: str) -> None:
        await self.db.execute("DELETE FROM game_events WHERE game_id=?", (game_id,))
        await self.db.execute("DELETE FROM games WHERE game_id=?", (game_id,))
        await self.db.commit()

    async def mark_cleaned(self, game_id: str) -> None:
        await self.db.execute("UPDATE games SET status='CLEANED' WHERE game_id=?", (game_id,))
        await self.db.commit()

    # ---- guild config ----
    async def get_config(self, guild_id: int) -> Optional[GuildConfig]:
        async with self.db.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,)) as cur:
            r = await cur.fetchone()
        if not r:
            return None
        return GuildConfig(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                           json.loads(r[8] or "[]"), json.loads(r[9] or "{}"))

    async def set_config(self, c: GuildConfig) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO guild_config VALUES(?,?,?,?,?,?,?,?,?,?)",
            (c.guild_id, c.category_id, c.commands_channel_id, c.admin_role_id, c.town_id, c.mafia_id,
             c.jail_id, c.graveyard_id, json.dumps(c.slot_role_ids), json.dumps(c.default_settings)))
        await self.db.commit()

    async def delete_config(self, guild_id: int) -> None:
        await self.db.execute("DELETE FROM guild_config WHERE guild_id=?", (guild_id,))
        await self.db.commit()

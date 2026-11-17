"""SQLite persistence (aiosqlite): guild_config, games (snapshots), game_events (append-only log)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

import aiosqlite

from ..engine.state import SCHEMA_VERSION, GameState
from .migrations import needs_migration

log = logging.getLogger("monke.store")
DB_VERSION = 2  # PRAGMA user_version: tracks table changes (REL-15)
KEEP_BACKUPS = 5

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
CREATE TABLE IF NOT EXISTS chat_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT, ts_ms INTEGER, channel_kind TEXT, session TEXT,
  kind TEXT, message_id INTEGER, author_user_id INTEGER, author_slot INTEGER, author_name TEXT,
  content TEXT, attachments_json TEXT);
CREATE INDEX IF NOT EXISTS idx_chat_log_game ON chat_log(game_id, ts_ms);
CREATE TABLE IF NOT EXISTS game_commands(
  game_id TEXT, seq INTEGER, ts_ms INTEGER, actor_slot INTEGER, type TEXT, payload_json TEXT,
  accepted INTEGER, reject_reason TEXT, PRIMARY KEY(game_id, seq));
CREATE TABLE IF NOT EXISTS archive_jobs(
  game_id TEXT PRIMARY KEY, state TEXT, attempts INTEGER, zip_message_ids_json TEXT, sha256_json TEXT,
  error TEXT, updated_at REAL);
"""


V2_TABLES = """
CREATE TABLE IF NOT EXISTS instance(
  instance_id TEXT PRIMARY KEY, pid INTEGER, host TEXT, started_at REAL, heartbeat_at REAL, clean_exit INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS outbox_posts(
  game_id TEXT, seq INTEGER, part INTEGER, target TEXT, message_id INTEGER, PRIMARY KEY(game_id, seq, part, target));
CREATE TABLE IF NOT EXISTS lobbies(
  lobby_id TEXT PRIMARY KEY, guild_id INTEGER, channel_id INTEGER, message_id INTEGER, opener_user_id INTEGER,
  players_json TEXT, settings_json TEXT, tokens_json TEXT, status TEXT, created_at REAL, updated_at REAL);
"""
V2_ALTERS = (
    "ALTER TABLE games ADD COLUMN rendered_seq INTEGER DEFAULT 0",
    "ALTER TABLE games ADD COLUMN banner_message_id INTEGER",
    "ALTER TABLE chat_log ADD COLUMN backfilled INTEGER DEFAULT 0",
    "ALTER TABLE guild_config ADD COLUMN lobby_id INTEGER",
    "ALTER TABLE guild_config ADD COLUMN server_settings_json TEXT",
    "ALTER TABLE guild_config ADD COLUMN flavour_path TEXT",
)


class DatabaseDamaged(Exception):
    """PRAGMA quick_check failed (REL-1): refuse to start and say how to restore a backup."""


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
    lobby_id: Optional[int] = None  # LOB-6
    server_settings: dict = field(default_factory=dict)  # ADM2-4
    flavour_path: Optional[str] = None


class Store:
    def __init__(self, path: str, backup_dir: Optional[str] = None):
        self.in_memory = path == ":memory:"
        self.path = path if self.in_memory else os.path.abspath(path)  # REL-2: same file from any folder
        self.backup_dir = backup_dir or os.path.join(os.path.dirname(self.path), "backups")
        self.db: Optional[aiosqlite.Connection] = None
        self.existed_before = False  # did the file exist before this launch? (REL-2)

    async def open(self, backup: bool = True) -> None:
        self.existed_before = (not self.in_memory) and os.path.exists(self.path) and os.path.getsize(self.path) > 0
        self.db = await aiosqlite.connect(self.path)
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA synchronous=FULL")
        await self.db.execute("PRAGMA busy_timeout=5000")
        async with self.db.execute("PRAGMA quick_check") as cur:
            rows = [r[0] for r in await cur.fetchall()]
        if rows != ["ok"]:
            await self.db.close()
            raise DatabaseDamaged(
                f"The database {self.path} failed its integrity check ({'; '.join(rows)[:200]}). Copy the newest file "
                f"from {self.backup_dir} over it while the bot is stopped, then start again.")
        await self.db.executescript(SCHEMA)
        await self.db.commit()
        async with self.db.execute("PRAGMA user_version") as cur:
            version = (await cur.fetchone())[0]
        if backup and self.existed_before and not self.in_memory:
            await self.backup("start" if version >= DB_VERSION and not await self._has_old_snapshots() else "premigrate")
        if version < DB_VERSION:
            await self._upgrade_tables(version)

    async def _has_old_snapshots(self) -> bool:
        async with self.db.execute("SELECT COUNT(*) FROM games WHERE COALESCE(schema_version,1) < ?",
                                   (SCHEMA_VERSION,)) as cur:
            return (await cur.fetchone())[0] > 0

    async def _upgrade_tables(self, version: int) -> None:
        """PRAGMA user_version tracks table changes; snapshots migrate on load (service/migrations.py)."""
        if version < 2:
            for stmt in V2_ALTERS:
                try:
                    await self.db.execute(stmt)
                except sqlite3.OperationalError as e:  # a column that already exists is fine
                    if "duplicate column" not in str(e):
                        raise
            await self.db.executescript(V2_TABLES)
        await self.db.execute(f"PRAGMA user_version={DB_VERSION}")
        await self.db.commit()

    async def backup(self, label: str = "start") -> Optional[str]:
        """REL-1: a copy with SQLite's backup API (safe while the database is in use). Keeps the newest 5."""
        os.makedirs(self.backup_dir, exist_ok=True)
        dest = os.path.join(self.backup_dir, f"monke-{time.strftime('%Y%m%d-%H%M%S')}-{label}.db")
        n = 0
        while os.path.exists(dest):
            n += 1
            dest = dest[:-3] + f"-{n}.db"

        def _copy():
            src, dst = sqlite3.connect(self.path), sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        try:
            await asyncio.to_thread(_copy)
        except Exception:
            log.exception("backup failed")
            return None
        files = sorted(f for f in os.listdir(self.backup_dir) if f.startswith("monke-") and f.endswith(".db"))
        for old in files[:-KEEP_BACKUPS]:
            try:
                os.remove(os.path.join(self.backup_dir, old))
            except OSError:
                pass
        return dest

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    # ---- games ----
    async def save_game(self, state: GameState, events: list = (), db_status: Optional[str] = None,
                        commands: list = ()) -> None:
        """Snapshot, events and the command that caused them in ONE transaction (ARC-4)."""
        now = time.time()
        await self.db.execute(
            "INSERT INTO games(game_id,guild_id,status,phase_id,snapshot_json,schema_version,updated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(game_id) DO UPDATE SET status=excluded.status, "
            "phase_id=excluded.phase_id, snapshot_json=excluded.snapshot_json, schema_version=excluded.schema_version, "
            "updated_at=excluded.updated_at",
            (state.game_id, state.guild_id, db_status or state.status, state.phase_id,
             json.dumps(state.to_dict()), SCHEMA_VERSION, now))
        for e in events:
            await self.db.execute(
                "INSERT OR IGNORE INTO game_events(game_id,seq,ts,type,payload_json,audience) VALUES(?,?,?,?,?,?)",
                (state.game_id, e.seq, now, e.type, json.dumps(e.payload), e.audience))
        for c in commands:
            await self._insert_command(state.game_id, c)
        await self.db.commit()

    # ---- commands (ARC-4) ----
    async def _insert_command(self, game_id: str, c: dict) -> None:
        async with self.db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM game_commands WHERE game_id=?",
                                   (game_id,)) as cur:
            (seq,) = await cur.fetchone()
        await self.db.execute(
            "INSERT INTO game_commands(game_id,seq,ts_ms,actor_slot,type,payload_json,accepted,reject_reason) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (game_id, seq, c["ts_ms"], c.get("actor_slot"), c["type"], json.dumps(c.get("payload") or {}),
             1 if c.get("accepted", True) else 0, c.get("reason")))

    async def log_command(self, game_id: str, c: dict) -> None:
        """A command on its own (a rejected one changes no state, so there is no snapshot to pair it with)."""
        await self._insert_command(game_id, c)
        await self.db.commit()

    async def load_commands(self, game_id: str) -> list:
        async with self.db.execute(
                "SELECT seq,ts_ms,actor_slot,type,payload_json,accepted,reject_reason FROM game_commands "
                "WHERE game_id=? ORDER BY seq", (game_id,)) as cur:
            rows = await cur.fetchall()
        return [{"seq": r[0], "ts_ms": r[1], "actor_slot": r[2], "type": r[3], "payload": json.loads(r[4] or "{}"),
                 "accepted": bool(r[5]), "reason": r[6]} for r in rows]

    async def load_events(self, game_id: str) -> list:
        async with self.db.execute(
                "SELECT seq,ts,type,payload_json,audience FROM game_events WHERE game_id=? ORDER BY seq",
                (game_id,)) as cur:
            rows = await cur.fetchall()
        return [{"seq": r[0], "ts_ms": int(round(r[1] * 1000)), "type": r[2], "payload": json.loads(r[3] or "{}"),
                 "audience": r[4]} for r in rows]

    # ---- chat log (ARC-3) ----
    async def add_chat_rows(self, rows: list) -> None:
        if not rows:
            return
        await self.db.executemany(
            "INSERT INTO chat_log(game_id,ts_ms,channel_kind,session,kind,message_id,author_user_id,author_slot,"
            "author_name,content,attachments_json,backfilled) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [(r["game_id"], r["ts_ms"], r["channel_kind"], r.get("session") or "", r["kind"], r.get("message_id"),
              r.get("author_user_id"), r.get("author_slot"), r.get("author_name"), r.get("content") or "",
              json.dumps(r.get("attachments") or []), 1 if r.get("backfilled") else 0) for r in rows])
        await self.db.commit()

    async def load_chat(self, game_id: str) -> list:
        async with self.db.execute(
                "SELECT id,ts_ms,channel_kind,session,kind,message_id,author_user_id,author_slot,author_name,content,"
                "attachments_json,COALESCE(backfilled,0) FROM chat_log WHERE game_id=? ORDER BY ts_ms, id",
                (game_id,)) as cur:
            rows = await cur.fetchall()
        return [{"id": r[0], "ts_ms": r[1], "channel_kind": r[2], "session": r[3], "kind": r[4], "message_id": r[5],
                 "author_user_id": r[6], "author_slot": r[7], "author_name": r[8], "content": r[9],
                 "attachments": json.loads(r[10] or "[]"), "backfilled": bool(r[11])} for r in rows]

    # ---- archive jobs (ARC-9, ARC-10) ----
    async def get_job(self, game_id: str) -> Optional[dict]:
        async with self.db.execute(
                "SELECT state,attempts,zip_message_ids_json,sha256_json,error,updated_at FROM archive_jobs "
                "WHERE game_id=?", (game_id,)) as cur:
            r = await cur.fetchone()
        if not r:
            return None
        return {"game_id": game_id, "state": r[0], "attempts": r[1] or 0, "zip_message_ids": json.loads(r[2] or "[]"),
                "sha256": json.loads(r[3] or "[]"), "error": r[4], "updated_at": r[5]}

    async def save_job(self, game_id: str, state: str, *, attempts: Optional[int] = None,
                       zip_message_ids: Optional[list] = None, sha256: Optional[list] = None,
                       error: Optional[str] = None, now: Optional[float] = None) -> dict:
        """Upsert; fields you leave out keep their old value. `error` is cleared unless you pass one."""
        cur = await self.get_job(game_id) or {"attempts": 0, "zip_message_ids": [], "sha256": []}
        job = {"game_id": game_id, "state": state,
               "attempts": cur["attempts"] if attempts is None else attempts,
               "zip_message_ids": cur["zip_message_ids"] if zip_message_ids is None else zip_message_ids,
               "sha256": cur["sha256"] if sha256 is None else sha256,
               "error": error, "updated_at": time.time() if now is None else now}
        await self.db.execute(
            "INSERT OR REPLACE INTO archive_jobs(game_id,state,attempts,zip_message_ids_json,sha256_json,error,"
            "updated_at) VALUES(?,?,?,?,?,?,?)",
            (game_id, state, job["attempts"], json.dumps(job["zip_message_ids"]), json.dumps(job["sha256"]),
             error, job["updated_at"]))
        await self.db.commit()
        return job

    async def pending_archive_games(self, guild_id: int) -> list:
        """Games of this server whose archive is not finished (ARC-15: teardown refuses while any exist)."""
        async with self.db.execute(
                "SELECT g.game_id, g.status, j.state FROM games g LEFT JOIN archive_jobs j ON j.game_id=g.game_id "
                "WHERE g.guild_id=? AND g.status IN ('ENDED') AND COALESCE(j.state,'') != 'PURGED'",
                (guild_id,)) as cur:
            rows = await cur.fetchall()
        return [{"game_id": r[0], "status": r[1], "job_state": r[2]} for r in rows]

    async def load_game(self, game_id: str) -> Optional[GameState]:
        async with self.db.execute("SELECT snapshot_json FROM games WHERE game_id=?", (game_id,)) as cur:
            r = await cur.fetchone()
        return GameState.from_dict(json.loads(r[0])) if r else None

    async def latest_game_id(self, guild_id: int) -> Optional[str]:
        async with self.db.execute(
                "SELECT game_id FROM games WHERE guild_id=? ORDER BY updated_at DESC LIMIT 1", (guild_id,)) as cur:
            r = await cur.fetchone()
        return r[0] if r else None

    async def prune_chat(self, older_than_ms: int) -> int:
        """ARC-13: drop chat_log and game_commands rows of PURGED games older than the cutoff.
        Snapshots and game_events are kept."""
        sub = "SELECT game_id FROM archive_jobs WHERE state='PURGED'"
        n = 0
        for table in ("chat_log", "game_commands"):
            async with self.db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE ts_ms < ? AND game_id IN ({sub})", (older_than_ms,)) as cur:
                n += (await cur.fetchone())[0]
            await self.db.execute(f"DELETE FROM {table} WHERE ts_ms < ? AND game_id IN ({sub})", (older_than_ms,))
        await self.db.commit()
        return n

    async def load_games(self, statuses: tuple) -> list:
        return (await self.load_games_report(statuses))[0]

    async def load_games_report(self, statuses: tuple) -> tuple:
        """-> (states, failures). A snapshot that cannot be read, or is newer than the code, is set aside
        (status QUARANTINED, data untouched) so one bad record never blocks the others (REL-4, F10)."""
        q = ",".join("?" * len(statuses))
        async with self.db.execute(
                f"SELECT game_id,guild_id,status,snapshot_json FROM games WHERE status IN ({q})", statuses) as cur:
            rows = await cur.fetchall()
        states, failures = [], []
        for game_id, guild_id, status, snap in rows:
            try:
                states.append(GameState.from_dict(json.loads(snap)))
            except Exception as exc:
                log.error("game %s could not be loaded (%r); setting it aside", game_id, exc)
                await self.db.execute("UPDATE games SET status='QUARANTINED' WHERE game_id=?", (game_id,))
                failures.append({"game_id": game_id, "guild_id": guild_id, "was": status, "error": repr(exc)})
        if failures:
            await self.db.commit()
        return states, failures

    # ---- rendering marker and outbox (REL-7) ----
    async def rendered_seq(self, game_id: str) -> int:
        async with self.db.execute("SELECT COALESCE(rendered_seq,0) FROM games WHERE game_id=?", (game_id,)) as cur:
            r = await cur.fetchone()
        return r[0] if r else 0

    async def set_rendered_seq(self, game_id: str, seq: int) -> None:
        await self.db.execute("UPDATE games SET rendered_seq=MAX(COALESCE(rendered_seq,0), ?) WHERE game_id=?",
                              (seq, game_id))
        await self.db.commit()

    async def max_event_seq(self, game_id: str) -> int:
        async with self.db.execute("SELECT COALESCE(MAX(seq),0) FROM game_events WHERE game_id=?", (game_id,)) as cur:
            return (await cur.fetchone())[0]

    async def next_event(self, game_id: str, after_seq: int) -> Optional[dict]:
        async with self.db.execute(
                "SELECT seq,ts,type,payload_json,audience FROM game_events WHERE game_id=? AND seq>? "
                "ORDER BY seq LIMIT 1", (game_id, after_seq)) as cur:
            r = await cur.fetchone()
        if not r:
            return None
        return {"seq": r[0], "ts_ms": int(round(r[1] * 1000)), "type": r[2], "payload": json.loads(r[3] or "{}"),
                "audience": r[4]}

    async def outbox_add(self, game_id: str, seq: int, part: int, target: str, message_id: int = 0) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO outbox_posts(game_id,seq,part,target,message_id) VALUES(?,?,?,?,?)",
            (game_id, seq, part, target, message_id or 0))
        await self.db.commit()

    async def outbox_for(self, game_id: str, seq: int) -> dict:
        """-> {(part, target): message_id} for one event."""
        async with self.db.execute("SELECT part,target,message_id FROM outbox_posts WHERE game_id=? AND seq=?",
                                   (game_id, seq)) as cur:
            return {(r[0], r[1]): r[2] for r in await cur.fetchall()}

    async def outbox_messages(self, game_id: str, seqs: list) -> list:
        """-> [(seq, target, message_id)] for the given events (used to expire prompts, QOL-8)."""
        if not seqs:
            return []
        q = ",".join("?" * len(seqs))
        async with self.db.execute(
                f"SELECT seq,target,message_id FROM outbox_posts WHERE game_id=? AND seq IN ({q}) AND message_id>0",
                (game_id, *seqs)) as cur:
            return [(r[0], r[1], r[2]) for r in await cur.fetchall()]

    async def set_banner_message(self, game_id: str, message_id: Optional[int]) -> None:
        await self.db.execute("UPDATE games SET banner_message_id=? WHERE game_id=?", (message_id, game_id))
        await self.db.commit()

    async def banner_message(self, game_id: str) -> Optional[int]:
        async with self.db.execute("SELECT banner_message_id FROM games WHERE game_id=?", (game_id,)) as cur:
            r = await cur.fetchone()
        return r[0] if r else None

    async def last_chat_message_id(self, game_id: str, channel_kind: str) -> Optional[int]:
        async with self.db.execute(
                "SELECT MAX(message_id) FROM chat_log WHERE game_id=? AND channel_kind=? AND message_id IS NOT NULL",
                (game_id, channel_kind)) as cur:
            return (await cur.fetchone())[0]

    # ---- instances (REL-3) ----
    async def instance_register(self, instance_id: str, pid: int, host: str, now: float) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO instance(instance_id,pid,host,started_at,heartbeat_at,clean_exit) "
            "VALUES(?,?,?,?,?,0)", (instance_id, pid, host, now, now))
        await self.db.commit()

    async def instance_heartbeat(self, instance_id: str, now: float) -> None:
        await self.db.execute("UPDATE instance SET heartbeat_at=? WHERE instance_id=?", (now, instance_id))
        await self.db.commit()

    async def instance_clean_exit(self, instance_id: str) -> None:
        await self.db.execute("UPDATE instance SET clean_exit=1 WHERE instance_id=?", (instance_id,))
        await self.db.commit()

    async def other_instances(self, instance_id: str) -> list:
        async with self.db.execute(
                "SELECT instance_id,pid,host,started_at,heartbeat_at,clean_exit FROM instance "
                "WHERE instance_id != ? ORDER BY heartbeat_at DESC", (instance_id,)) as cur:
            return [{"instance_id": r[0], "pid": r[1], "host": r[2], "started_at": r[3], "heartbeat_at": r[4],
                     "clean_exit": bool(r[5])} for r in await cur.fetchall()]

    async def prune_instances(self, keep: int = 20) -> None:
        await self.db.execute(
            "DELETE FROM instance WHERE instance_id NOT IN (SELECT instance_id FROM instance "
            "ORDER BY heartbeat_at DESC LIMIT ?)", (keep,))
        await self.db.commit()

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
                           json.loads(r[8] or "[]"), json.loads(r[9] or "{}"),
                           lobby_id=r[10], server_settings=json.loads(r[11] or "{}"), flavour_path=r[12])

    async def set_config(self, c: GuildConfig) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO guild_config(guild_id,category_id,commands_channel_id,admin_role_id,town_id,"
            "mafia_id,jail_id,graveyard_id,slot_role_ids_json,default_settings_json,lobby_id,server_settings_json,"
            "flavour_path) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c.guild_id, c.category_id, c.commands_channel_id, c.admin_role_id, c.town_id, c.mafia_id,
             c.jail_id, c.graveyard_id, json.dumps(c.slot_role_ids), json.dumps(c.default_settings), c.lobby_id,
             json.dumps(c.server_settings), c.flavour_path))
        await self.db.commit()

    async def delete_config(self, guild_id: int) -> None:
        await self.db.execute("DELETE FROM guild_config WHERE guild_id=?", (guild_id,))
        await self.db.commit()

"""The lobby model (LOB-7 to LOB-10). Pure: no Discord. Lobbies live in the `lobbies` table so they survive restarts."""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Optional

from .. import constants as C
import random

from ..engine.rolelist import default_rolelist, generate_roles, validate_rolelist
from ..errors import Rejected

OPEN, STARTED, CANCELLED, EXPIRED, REMATCH = "OPEN", "STARTED", "CANCELLED", "EXPIRED", "REMATCH"


@dataclass
class Lobby:
    lobby_id: str
    guild_id: int
    opener_user_id: int
    channel_id: int = 0
    message_id: int = 0
    players: list = field(default_factory=list)  # user ids, in the order they joined
    options: dict = field(default_factory=dict)  # per-game overrides, key -> text (LOB-5)
    tokens: Optional[list] = None  # None: the default list for the number of players
    status: str = OPEN
    created_at: float = 0.0
    updated_at: float = 0.0

    @classmethod
    def new(cls, guild_id: int, opener: int, now: float, players=None, options=None) -> "Lobby":
        return cls(secrets.token_hex(5), guild_id, opener, players=list(players or []), options=dict(options or {}),
                   created_at=now, updated_at=now)

    @property
    def count(self) -> int:
        return len(self.players)

    def rolelist(self) -> list:
        """The role list that would be used: the edited one, else the default for this many players."""
        if self.tokens:
            return list(self.tokens)
        return default_rolelist(self.count) if C.MIN_PLAYERS <= self.count <= C.MAX_PLAYERS else []

    def is_default_list(self) -> bool:
        return not self.tokens

    # ---- membership ----
    def join(self, user_id: int) -> None:
        if user_id in self.players:
            raise Rejected("lobby.already_in")
        if self.count >= C.MAX_PLAYERS:
            raise Rejected("lobby.full")
        self.players.append(user_id)

    def leave(self, user_id: int) -> None:
        if user_id not in self.players:
            raise Rejected("error.not_in_game")
        self.players.remove(user_id)

    def check_start(self) -> None:
        """Start is enabled at 5 to 20 players with a valid list; otherwise say what is wrong (LOB-7)."""
        if not C.MIN_PLAYERS <= self.count <= C.MAX_PLAYERS:
            raise Rejected("lobby.start_blocked.count", count=self.count)
        try:
            canon = validate_rolelist(self.rolelist(), self.count)
            generate_roles(canon, random.Random(0))  # unique roles and exhausted pools are caught here
        except Rejected as e:
            raise Rejected("lobby.start_blocked.rolelist", inner=e)


def _row(l: Lobby) -> tuple:
    return (l.lobby_id, l.guild_id, l.channel_id, l.message_id, l.opener_user_id, json.dumps(l.players),
            json.dumps(l.options), json.dumps(l.tokens), l.status, l.created_at, l.updated_at)


def _from_row(r) -> Lobby:
    return Lobby(r[0], r[1], r[4], r[2] or 0, r[3] or 0, json.loads(r[5] or "[]"), json.loads(r[6] or "{}"),
                 json.loads(r[7] or "null"), r[8], r[9] or 0.0, r[10] or 0.0)


COLS = "lobby_id,guild_id,channel_id,message_id,opener_user_id,players_json,settings_json,tokens_json,status," \
       "created_at,updated_at"


class LobbyStore:
    """Persistence on top of a Store."""

    def __init__(self, store):
        self.store = store

    async def save(self, l: Lobby, now: Optional[float] = None) -> None:
        if now is not None:
            l.updated_at = now
        await self.store.db.execute(f"INSERT OR REPLACE INTO lobbies({COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?)", _row(l))
        await self.store.db.commit()

    async def get(self, lobby_id: str) -> Optional[Lobby]:
        async with self.store.db.execute(f"SELECT {COLS} FROM lobbies WHERE lobby_id=?", (lobby_id,)) as cur:
            r = await cur.fetchone()
        return _from_row(r) if r else None

    async def open_for_guild(self, guild_id: int) -> Optional[Lobby]:
        async with self.store.db.execute(
                f"SELECT {COLS} FROM lobbies WHERE guild_id=? AND status='OPEN' ORDER BY created_at DESC LIMIT 1",
                (guild_id,)) as cur:
            r = await cur.fetchone()
        return _from_row(r) if r else None

    async def all_open(self) -> list:
        async with self.store.db.execute(f"SELECT {COLS} FROM lobbies WHERE status='OPEN'") as cur:
            return [_from_row(r) for r in await cur.fetchall()]

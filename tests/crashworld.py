"""Test harness for REL-18: a fake 'Discord' that outlives the bot process, and a way to 'crash' and restart.

`World` holds what Discord remembers (posts, roles, members, history, pins). `boot()` builds a brand new Store,
GameService and presenter on the same database file, exactly like a restarted process."""
from __future__ import annotations

import asyncio
import os
import tempfile

from monke import constants as C
from monke.engine import Settings
from monke.service.archive import ArchiveService
from monke.service.capture import ChatCapture
from monke.service.game_service import GameService
from monke.service.outbox import Retryable
from monke.service.store import Store
from monke.text.bank import default_bank

USERS = [101, 102, 103, 104, 105]
TOKENS = ["Jailor", "Godfather", "TI", "TP", "TK"]
NAMES = {101: "Ann", 102: "Bob", 103: "Cy", 104: "Di", 105: "Ed"}


class World:
    """Everything Discord keeps while the bot is not running."""

    def __init__(self):
        self.posts: list = []  # (kind, game_id, text) in order: public posts and DMs
        self.slot_roles: set = set()  # (guild, slot)
        self.members = set(USERS)
        self.history: dict = {}  # channel kind -> [rows]
        self.missing: list = []  # structures that were deleted
        self.fail_next: int = 0  # the next N sends raise Retryable
        self.notices: list = []
        self.uploads = 0
        self.purged = 0
        self.separators = 0
        self.pinned = []

    def public(self) -> list:
        return [p for p in self.posts if p[0] not in ("dm",)]


class FakePresenter:
    def __init__(self, world: World, crash=None):
        self.w, self.crash = world, crash
        self.bank = default_bank()

    # ---- start sequence
    async def assign_slot_roles(self, s):
        for slot in s.players:
            self.w.slot_roles.add((s.guild_id, slot))

    async def remove_slot_roles(self, s):
        self.w.slot_roles = {r for r in self.w.slot_roles if r[0] != s.guild_id}

    async def send_role_dms(self, s, events):
        return []

    async def apply_permissions(self, s, force=False): ...
    async def reconcile(self, s): ...
    async def cleanup(self, s): ...

    async def notify_admin(self, guild_id, key, **vars):
        self.w.notices.append(key)

    async def post_key(self, s, channel, key, **vars):
        self.w.posts.append(("post", s.game_id, key))

    async def structures_missing(self, s):
        return list(self.w.missing)

    async def members_missing(self, s):
        return [slot for slot, p in s.players.items() if p.alive and p.user_id not in self.w.members]

    async def fetch_history_after(self, s, kind, after):
        return [r for r in self.w.history.get(kind, []) if after is None or r["message_id"] > after]

    async def jail_gap(self, s, rows):
        self.w.posts.append(("jail_gap", s.game_id, str(len(rows))))

    # ---- rendering: every message goes through the outbox, like the real presenter
    async def render(self, s, events, outbox=None):
        for e in events:
            for text in self._texts(s, e):
                async def send(text=text):
                    if self.w.fail_next > 0:
                        self.w.fail_next -= 1
                        raise Retryable("discord is down")
                    self.w.posts.append(("post", s.game_id, text))
                    return None
                if outbox is not None:
                    await outbox.once(f"town:{text[:20]}", send)
                else:
                    await send()

    @staticmethod
    def _texts(s, e):
        if e.type == "PhaseChanged":
            return [f"banner {e.payload['phase']} {e.payload['phase_id']}"]
        if e.type == "VoteUpdated":
            return [f"vote {e.payload['voter']}->{e.payload['target']}"]
        if e.type == "PlayerDied":
            return [f"died {e.payload['slot']}"]
        if e.type == "DawnReport":
            return [f"dawn {e.payload['day']}"]
        if e.type == "PromptRequested":
            return [f"prompt {e.audience} {e.payload['token']}"]
        if e.type == "Announcement":
            return [f"announce {e.payload.get('text_key')}"]
        return []

    # ---- archive
    def filesize_limit(self, guild_id): return 8_000_000
    async def lock_for_archive(self, s): ...
    async def archive_messages_exist(self, guild, ids): return bool(ids) and self.w.uploads > 0

    async def upload_archive(self, s, summary, zips):
        self.w.uploads += 1
        return [999], ["h"]

    async def purge_game_channels(self, guild):
        self.w.purged += 1

    async def send_separators(self, s, summary):
        self.w.separators += 1


class Proc:
    """One 'process': a Store, a GameService and a presenter on the shared database file."""

    def __init__(self, path, world, clock):
        self.path, self.world, self.clock = path, world, clock

    async def boot(self, archive: bool = False, recover: bool = True, last_heartbeat=None):
        self.store = Store(self.path)
        await self.store.open(backup=False)
        self.pres = FakePresenter(self.world)
        self.capture = ChatCapture(self.store)
        self.archive = ArchiveService(self.store, self.pres, self.capture, clock=self.clock) if archive else None
        self.svc = GameService(self.store, self.pres, clock=self.clock, post_game_seconds=0, archive=self.archive)
        self.pres.crash = self.svc.crash

        async def nosleep(_):
            await asyncio.sleep(0)
        self.svc.sleep = nosleep
        if recover:
            await self.svc.recover(last_heartbeat=last_heartbeat)
        return self

    async def die(self):
        """The process ends without any clean-up: cancel its tasks and close the file."""
        for t in list(self.svc._bg):
            t.cancel()
        self.svc.scheduler.cancel_all() if hasattr(self.svc.scheduler, "cancel_all") else None
        for game in list(self.svc.games.values()):
            self.svc.scheduler.cancel(game.game_id)
        await asyncio.sleep(0)
        await self.store.close()


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def new_path():
    d = tempfile.mkdtemp()
    return os.path.join(d, "monke.db")

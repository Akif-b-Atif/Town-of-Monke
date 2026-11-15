from __future__ import annotations

import logging
import os
import time

import discord
from discord.ext import commands, tasks

from ..debug import NullSink
from ..service.archive import ArchiveService
from ..service.capture import ChatCapture
from ..service.game_service import GameService
from ..service.store import Store
from . import views
from .admin_cog import AdminCog
from .chatlog import ChatLogger
from .player_cog import PlayerCog
from .relay import JailRelay
from .renderer import DiscordPresenter
from .setup_cog import SetupCog, apply_commands_channel_permissions

log = logging.getLogger("monke.bot")


class MonkeBot(commands.Bot):
    def __init__(self, db_path: str = "monke.db", sink=None):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True      # receive messages in guild channels (prefix commands, prisoner relay)
        intents.dm_messages = True         # receive the Jailor's DMs
        intents.message_content = True     # PRIVILEGED: needed for `monke` commands and the jail relay
        super().__init__(command_prefix=commands.when_mentioned_or("monke "), intents=intents,
                         case_insensitive=True, help_command=None)
        self.sink = sink or NullSink()  # DBG: the debug console, off by default
        self.store = Store(db_path)
        self.capture = ChatCapture(self.store)  # ARC-3: async queue between Discord events and SQLite
        self.presenter = DiscordPresenter(self, self.store)
        self.presenter.sink = self.sink
        self.archive = ArchiveService(self.store, self.presenter, self.capture,
                                      retention_days=int(os.environ.get("MONKE_ARCHIVE_DAYS", "7")), sink=self.sink)
        self.service = GameService(self.store, self.presenter, archive=self.archive, sink=self.sink)
        self.relay = JailRelay(self)
        self.chatlog = ChatLogger(self)

    async def setup_hook(self) -> None:
        await self.store.open()
        self.capture.start()
        self._prune_loop.start()
        self.add_dynamic_items(*views.DYNAMIC_ITEMS)  # prompts and verdict buttons survive restarts
        await self.add_cog(SetupCog(self))
        await self.add_cog(AdminCog(self))
        await self.add_cog(PlayerCog(self))
        await self.tree.sync()

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)
        if not getattr(self, "_permissions_synced", False):
            self._permissions_synced = True
            await self._sync_commands_channels()
        if not getattr(self, "_recovered", False):
            self._recovered = True
            await self.service.recover()  # section 11: reconcile, re-arm timers, tell the admin

    async def _sync_commands_channels(self) -> None:
        """ADM-1: bring #monke-commands in every configured server up to the current rule."""
        for guild in self.guilds:
            try:
                cfg = await self.store.get_config(guild.id)
                if cfg is not None:
                    await apply_commands_channel_permissions(guild, cfg)
            except Exception:
                log.exception("could not sync #monke-commands in guild %s", guild.id)

    @tasks.loop(hours=24)
    async def _prune_loop(self) -> None:
        """ARC-13: drop old chat and command rows of archived games. Snapshots and events stay."""
        try:
            cutoff = int((time.time() - self.archive.retention_days * 86400) * 1000)
            log.info("pruned %d old archive rows", await self.store.prune_chat(cutoff))
        except Exception:
            log.exception("prune failed")

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        try:
            await self.chatlog.on_raw_edit(payload)
        except Exception:
            log.exception("could not log an edit")

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        try:
            await self.chatlog.on_raw_delete(payload)
        except Exception:
            log.exception("could not log a delete")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        try:
            await self.chatlog.on_message(message)  # before the relay, so prisoner text is always logged
        except Exception:
            log.exception("could not log a message")
        try:
            if await self.relay.handle(message):
                return
        except Exception:
            log.exception("relay failed")
        await self.process_commands(message)

    async def on_member_remove(self, member: discord.Member) -> None:
        g = self.service.get(member.guild.id)
        slot = g.slot_of_user(member.id) if g else None
        if slot is not None:
            from ..engine import commands as K
            from ..errors import Rejected
            try:
                await self.service.submit(member.guild.id, K.Abandon(slot))
            except Rejected:
                pass

    async def close(self) -> None:
        self._prune_loop.cancel()
        await self.capture.stop()  # flush queued chat rows before the database closes
        await super().close()
        await self.store.close()

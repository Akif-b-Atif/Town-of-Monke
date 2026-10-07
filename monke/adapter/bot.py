from __future__ import annotations

import logging

import discord
from discord.ext import commands

from ..service.game_service import GameService
from ..service.store import Store
from . import views
from .admin_cog import AdminCog
from .player_cog import PlayerCog
from .relay import JailRelay
from .renderer import DiscordPresenter
from .setup_cog import SetupCog

log = logging.getLogger("monke.bot")


class MonkeBot(commands.Bot):
    def __init__(self, db_path: str = "monke.db"):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True      # receive messages in guild channels (prefix commands, prisoner relay)
        intents.dm_messages = True         # receive the Jailor's DMs
        intents.message_content = True     # PRIVILEGED: needed for `monke` commands and the jail relay
        super().__init__(command_prefix=commands.when_mentioned_or("monke "), intents=intents,
                         case_insensitive=True, help_command=None)
        self.store = Store(db_path)
        self.presenter = DiscordPresenter(self, self.store)
        self.service = GameService(self.store, self.presenter)
        self.relay = JailRelay(self)

    async def setup_hook(self) -> None:
        await self.store.open()
        self.add_dynamic_items(*views.DYNAMIC_ITEMS)  # prompts and verdict buttons survive restarts
        await self.add_cog(SetupCog(self))
        await self.add_cog(AdminCog(self))
        await self.add_cog(PlayerCog(self))
        await self.tree.sync()

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)
        if not getattr(self, "_recovered", False):
            self._recovered = True
            await self.service.recover()  # section 11: reconcile, re-arm timers, tell the admin

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
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
        await super().close()
        await self.store.close()

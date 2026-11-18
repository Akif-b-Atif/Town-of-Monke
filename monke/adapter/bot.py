from __future__ import annotations

import logging
import os
import pathlib
import time

import discord
from discord.ext import commands, tasks

import asyncio

from ..debug import NullSink
from ..service.guards import WRONG_FOLDER, looks_like_wrong_folder
from ..service.instance import AlreadyRunning, InstanceGuard
from ..text.bank import load_for_use, load_text, default_bank
from ..service.archive import ArchiveService
from ..service.capture import ChatCapture
from ..service.game_service import GameService
from ..service.store import Store
from . import views
from .dispatch import Dispatcher
from .handlers import COMMANDS
from .lobby import DYNAMIC_ITEMS as LOBBY_ITEMS, LobbyManager
from .chatlog import ChatLogger
from .relay import JailRelay
from .renderer import DiscordPresenter
from .setup_cog import apply_commands_channel_permissions

log = logging.getLogger("monke.bot")


FLAVOUR_PATH = pathlib.Path(__file__).resolve().parents[2] / "flavour.yaml"


class MonkeBot(commands.Bot):
    def __init__(self, db_path: str = "monke.db", sink=None, new_db: bool = False, force_takeover: bool = False):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True      # receive messages in guild channels (prefix commands, prisoner relay)
        intents.dm_messages = True         # receive the Jailor's DMs
        intents.message_content = True     # PRIVILEGED: needed for `monke` commands and the jail relay
        super().__init__(command_prefix=commands.when_mentioned_or("monke "), intents=intents,
                         case_insensitive=True, help_command=None)
        self.sink = sink or NullSink()  # DBG: the debug console, off by default
        self.store = Store(db_path)
        self.guard = InstanceGuard(self.store)  # REL-3
        self.new_db, self.force_takeover = new_db, force_takeover
        self.exit_code, self.exit_message = 0, None
        self._closing_started = False
        self._bg: set = set()
        self._last_owner_alert = 0.0
        self.capture = ChatCapture(self.store)  # ARC-3: async queue between Discord events and SQLite
        self.presenter = DiscordPresenter(self, self.store)
        self.presenter.sink = self.sink
        self.flavour_path = pathlib.Path(os.environ.get("MONKE_FLAVOUR") or FLAVOUR_PATH)
        bank, _report, self.text_is_default = load_for_use(self.flavour_path)  # TXT-3: invalid text -> shipped default
        self.presenter.composer.bank = bank
        self.archive = ArchiveService(self.store, self.presenter, self.capture,
                                      retention_days=int(os.environ.get("MONKE_ARCHIVE_DAYS", "7")), sink=self.sink)
        self.service = GameService(self.store, self.presenter, archive=self.archive, sink=self.sink)
        self.relay = JailRelay(self)
        self.chatlog = ChatLogger(self)
        self.lobbies = LobbyManager(self)  # LOB-7
        self.service.on_error = self.report_error
        self.tree.on_error = self._on_tree_error

    # ---------------------------------------------------------------- never die silently (REL-13)
    def _spawn(self, coro, name: str = "task") -> None:
        t = asyncio.create_task(coro)
        self._bg.add(t)

        def done(task: asyncio.Task) -> None:
            self._bg.discard(task)
            if not task.cancelled() and task.exception() is not None:
                self.report_error(task.exception(), None, name)
        t.add_done_callback(done)

    def report_error(self, exc: BaseException, game_id=None, where: str = "") -> None:
        """Log with the game id and DM the owner a spoiler-safe one-liner, at most one a minute."""
        log.error("unhandled error%s (game %s)", f" in {where}" if where else "", game_id or "-", exc_info=exc)
        owner = os.environ.get("MONKE_OWNER_ID", "").strip()
        if not owner.isdigit() or time.monotonic() - self._last_owner_alert < 60:
            return
        self._last_owner_alert = time.monotonic()

        async def tell():
            user = self.get_user(int(owner)) or await self.fetch_user(int(owner))
            gid = game_id or "-"
            await user.send(self.presenter.composer.t(None, "rel.owner_alert", game_id=gid),  # allow-send: owner DM
                            allowed_mentions=discord.AllowedMentions.none())
        try:
            asyncio.get_running_loop().create_task(tell()).add_done_callback(
                lambda t: t.cancelled() or t.exception())  # a failed alert must not raise again
        except RuntimeError:
            pass

    def _loop_exception(self, loop, context: dict) -> None:
        exc = context.get("exception")
        if exc is not None:
            self.report_error(exc, None, "event loop")
        else:
            log.error("event loop: %s", context.get("message"))

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        import sys
        self.report_error(sys.exc_info()[1] or RuntimeError(event_method), None, event_method)

    async def _on_tree_error(self, interaction: discord.Interaction, error) -> None:
        self.report_error(error, None, "slash command")
        try:
            text = self.presenter.composer.t(None, "error.generic")
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)  # allow-send: ephemeral reply
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except Exception:
            pass

    async def setup_hook(self) -> None:
        asyncio.get_running_loop().set_exception_handler(self._loop_exception)
        await self.store.open()
        try:
            await self.guard.start(force=self.force_takeover)  # REL-3: a second copy refuses to start
        except AlreadyRunning as e:
            self.exit_code = 3
            self.exit_message = (f"Another copy of the bot is already running (pid {e.other['pid']} on "
                                 f"{e.other['host']}). Stop it first, or start with --force-takeover.")
            raise
        self.capture.start()
        self.lobbies.start_sweeper()
        self._prune_loop.start()
        self._spawn(self._heartbeat_forever(), "heartbeat")
        self.add_dynamic_items(*views.DYNAMIC_ITEMS, *LOBBY_ITEMS)  # prompts and verdict buttons survive restarts
        self.dispatcher = Dispatcher(self, COMMANDS)  # CMD-1: every command comes from the registry
        for cmd in self.dispatcher.slash_commands():
            self.tree.add_command(cmd)
        await self.tree.sync()

    async def _heartbeat_forever(self) -> None:
        while True:
            try:
                await self.service.heartbeat_tick(self.guard)
            except Exception:
                log.exception("heartbeat failed")
            await asyncio.sleep(5)

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)
        if not getattr(self, "_permissions_synced", False):
            self._permissions_synced = True
            await self._sync_commands_channels()
        if not getattr(self, "_recovered", False):
            self._recovered = True  # REL-4: once per process, never from a repeated on_ready
            if looks_like_wrong_folder(self.store.existed_before, self._has_monke_category(), self.new_db):
                self.exit_code, self.exit_message = 2, WRONG_FOLDER.format(path=self.store.path)
                await self.close()
                return
            self._spawn(self._recover_when_ready(), "recovery")
        else:  # a gateway reconnect: only the light pass
            self._spawn(self.service.light_pass(), "light pass")

    def _has_monke_category(self) -> bool:
        return any(discord.utils.get(g.categories, name="Town of Monke") is not None for g in self.guilds)

    async def _recover_when_ready(self) -> None:
        """Wait (every 30 s, up to 10 minutes) for unavailable servers, then run recovery once."""
        waited = 0
        while any(g.unavailable for g in self.guilds) and waited < 600:
            await asyncio.sleep(30)
            waited += 30
        await self.service.recover(last_heartbeat=self.guard.last_heartbeat_before)

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
        await self.dispatcher.on_message(message)

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
        """REL-12: stop accepting commands, let in-flight locks finish, flush the chat queue, cancel timers, mark a
        clean exit, say goodbye in Town Centre, then close."""
        if self._closing_started:
            return
        self._closing_started = True
        for t in list(self._bg):
            if t.get_name() != "recovery":
                t.cancel()
        try:
            await self.service.shutdown()
        except Exception:
            log.exception("shutdown notice failed")
        try:
            self._prune_loop.cancel()
            await self.capture.stop()  # flush queued chat rows before the database closes
            await self.guard.stop()  # clean_exit = 1
        except Exception:
            log.exception("shutdown persist failed")
        await super().close()
        await self.store.close()

    def reload_text(self) -> tuple:
        """TXT-3 / ADM2-4: swap in the edited file if it is valid; otherwise keep the previous text.
        -> (ok, report)."""
        bank, report = load_text(self.flavour_path, fallback=default_bank())
        if bank is None:
            return False, report
        self.presenter.composer.bank = bank
        self.text_is_default = False
        return True, report

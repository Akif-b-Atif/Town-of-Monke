"""Admin prefix commands. Usable by anyone holding the live Monke Admin role (ADM-3)."""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands

from .. import constants as C
from ..engine import Settings
from ..engine import commands as K
from ..errors import Rejected
from ..service.game_service import StartAborted
from . import strings as S
from .parsing import parse_start
from .textutil import rel, sanitize_name

log = logging.getLogger("monke.admin")

SKIP_GUARD_SECONDS = 3  # ADM-8


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_skip: dict[int, float] = {}

    @staticmethod
    def _is_admin(member, cfg) -> bool:
        """ADM-3: authority is the live Monke Admin role, checked on every command."""
        return any(r.id == cfg.admin_role_id for r in member.roles)

    async def cog_check(self, ctx) -> bool:
        if ctx.guild is None:
            return False
        cfg = await self.bot.store.get_config(ctx.guild.id)
        if cfg is None:
            return False
        if ctx.command is not None and ctx.command.name == "admins":
            # ADM-6: Monke Admin holders or Manage Server, in any channel
            return self._is_admin(ctx.author, cfg) or ctx.author.guild_permissions.manage_guild
        if ctx.channel.id != cfg.commands_channel_id:
            return False  # the bot only listens in Monke Commands
        return self._is_admin(ctx.author, cfg)

    async def _say(self, ctx, text: str):
        """ADM-7: every admin reply names the invoker. No pings."""
        name = discord.utils.escape_mentions(discord.utils.escape_markdown(ctx.author.display_name))
        return await ctx.reply(f"**{name}**: {text}", allowed_mentions=discord.AllowedMentions.none())

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            return
        log.exception("admin command failed", exc_info=error)
        await self._say(ctx, "Something went wrong running that command. Check the bot logs.")

    @commands.command(name="start")
    async def start(self, ctx, *, rest: str = ""):
        try:
            g = self.bot.service.get(ctx.guild.id)
            if g is not None and g.status in (C.STARTING, C.RUNNING, C.PAUSED):
                return await self._say(ctx, S.GAME_ALREADY_RUNNING)
            bot_ids = {m.id for m in ctx.message.mentions if m.bot}
            req = parse_start(ctx.message.content, bot_ids)
            cfg = await self.bot.store.get_config(ctx.guild.id)
            settings = Settings.from_options(req.options, Settings(**cfg.default_settings) if cfg.default_settings else None)
            await self._say(ctx, "Starting the game: assigning roles and sending DMs...")
            names = {}
            for uid in req.user_ids:  # NAM-1: store each player's sanitised server name once, at start
                member = ctx.guild.get_member(uid)
                if member is None:
                    try:
                        member = await ctx.guild.fetch_member(uid)
                    except discord.HTTPException:
                        member = None
                names[uid] = sanitize_name(member.display_name if member else "")
            await self.bot.service.start_game(ctx.guild.id, req.user_ids, req.tokens, settings, names=names,
                                              invoker_user_id=ctx.author.id)
        except Rejected as e:
            await self._say(ctx, f"Can't start: {e.reason}")
        except StartAborted as e:
            who = " ".join(f"<@{u}>" for u in e.failed_user_ids)
            await self._say(ctx, f"Start aborted. These players must open their DMs (Privacy Settings > allow DMs): {who}")
        except Exception as e:
            log.exception("start failed")
            await self._say(ctx, f"Start failed: {e}")

    @commands.command(name="status")
    async def status(self, ctx):
        g = self.bot.service.get(ctx.guild.id)
        if g is None:
            return await self._say(ctx, "No game is running.")
        ends = rel(g.phase_ends_at) if g.status == C.RUNNING else "n/a"
        await self._say(ctx, f"Status **{g.status}**, phase **{g.phase}**, ends {ends}, "
                             f"{len(g.alive_slots())}/{len(g.players)} alive.")  # never shows roles

    async def _send(self, ctx, cmd, ok: str) -> bool:
        g = self.bot.service.get(ctx.guild.id)
        if g is None:
            await self._say(ctx, "No game is running.")
            return False
        try:
            await self.bot.service.submit(ctx.guild.id, cmd(g) if callable(cmd) else cmd)
        except Rejected as e:
            await self._say(ctx, e.reason)
            return False
        await self._say(ctx, ok)
        return True

    def _skipped_too_soon(self, guild_id: int, g) -> bool:
        """ADM-8: reject a skip right after a phase change (double-admin protection)."""
        now = time.time()
        started = getattr(g, "phase_started_at", None)  # used if the game state records it
        if started is not None and now - started < SKIP_GUARD_SECONDS:
            return True
        return now - self._last_skip.get(guild_id, 0.0) < SKIP_GUARD_SECONDS

    @commands.command(name="skip")
    async def skip(self, ctx):
        g = self.bot.service.get(ctx.guild.id)
        if g is not None and self._skipped_too_soon(ctx.guild.id, g):
            return await self._say(ctx, S.SKIP_TOO_SOON)
        if await self._send(ctx, lambda g: K.AdvancePhase(g.phase_id, force=True, by=sanitize_name(ctx.author.display_name, "Admin")),
                                "Phase skipped."):
            self._last_skip[ctx.guild.id] = time.time()
            await self.bot.service.record_admin_action(ctx.guild.id, ctx.author.id, "skip")  # ARC-6

    @commands.command(name="abort")
    async def abort(self, ctx):
        if await self._send(ctx, K.Abort(), "Game aborted. The archive will be posted here shortly."):
            await self.bot.service.record_admin_action(ctx.guild.id, ctx.author.id, "abort")  # ARC-6

    @commands.command(name="resume")
    async def resume(self, ctx):
        if await self._send(ctx, K.Resume(), "Game resumed."):
            await self.bot.service.record_admin_action(ctx.guild.id, ctx.author.id, "resume")  # ARC-6

    @commands.command(name="export")
    async def export(self, ctx, game_id: str = ""):
        """ARC-12: rebuild and post the archive; also retries a failed end-of-game archive."""
        g = self.bot.service.get(ctx.guild.id)
        if g is not None and g.status == C.ENDED:
            await self.bot.service.record_admin_action(ctx.guild.id, ctx.author.id, "export", game_id)  # ARC-6
        elif g is not None and g.status in (C.STARTING, C.RUNNING, C.PAUSED):
            return await self._say(ctx, S.EXPORT_LIVE_REFUSED)
        await self._say(ctx, "Building the archive. This can take a minute.")
        try:
            msg = await self.bot.service.export(ctx.guild.id, game_id or None)
        except Rejected as e:
            return await self._say(ctx, e.reason)
        except Exception:
            log.exception("export failed")
            return await self._say(ctx, S.EXPORT_FAILED)
        await self._say(ctx, msg)

    @commands.command(name="admins")
    async def admins(self, ctx):
        """ADM-6: list current Monke Admin holders."""
        cfg = await self.bot.store.get_config(ctx.guild.id)
        role = ctx.guild.get_role(cfg.admin_role_id) if cfg else None
        holders = sorted(role.members, key=lambda m: m.id) if role else []
        if not holders:
            return await self._say(ctx, S.NO_ADMINS)
        await self._say(ctx, S.ADMINS_LIST.format(names=", ".join(f"<@{m.id}>" for m in holders)))
"""Admin prefix commands. Only usable in Monke Commands by someone holding the Monke Admin role."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .. import constants as C
from ..engine import Settings
from ..engine import commands as K
from ..errors import Rejected
from ..service.game_service import StartAborted
from .parsing import parse_start

log = logging.getLogger("monke.admin")


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx) -> bool:
        if ctx.guild is None:
            return False
        cfg = await self.bot.store.get_config(ctx.guild.id)
        if cfg is None or ctx.channel.id != cfg.commands_channel_id:
            return False  # the bot only listens in Monke Commands
        return any(r.id == cfg.admin_role_id for r in ctx.author.roles)

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            return
        log.exception("admin command failed", exc_info=error)
        await ctx.reply("Something went wrong running that command. Check the bot logs.")

    @commands.command(name="start")
    async def start(self, ctx, *, rest: str = ""):
        try:
            bot_ids = {m.id for m in ctx.message.mentions if m.bot}
            req = parse_start(ctx.message.content, bot_ids)
            cfg = await self.bot.store.get_config(ctx.guild.id)
            settings = Settings.from_options(req.options, Settings(**cfg.default_settings) if cfg.default_settings else None)
            await ctx.reply("Starting the game: assigning roles and sending DMs...")
            await self.bot.service.start_game(ctx.guild.id, req.user_ids, req.tokens, settings)
        except Rejected as e:
            await ctx.reply(f"Can't start: {e.reason}")
        except StartAborted as e:
            who = " ".join(f"<@{u}>" for u in e.failed_user_ids)
            await ctx.reply(f"Start aborted. These players must open their DMs (Privacy Settings > allow DMs): {who}",
                            allowed_mentions=discord.AllowedMentions.none())
        except Exception as e:
            log.exception("start failed")
            await ctx.reply(f"Start failed: {e}")

    @commands.command(name="status")
    async def status(self, ctx):
        g = self.bot.service.get(ctx.guild.id)
        if g is None:
            return await ctx.reply("No game is running.")
        ends = f"<t:{int(g.phase_ends_at)}:R>" if g.status == C.RUNNING else "n/a"
        await ctx.reply(f"Status **{g.status}**, phase **{g.phase}**, ends {ends}, "
                        f"{len(g.alive_slots())}/{len(g.players)} alive.")  # never shows roles

    async def _send(self, ctx, cmd, ok: str):
        g = self.bot.service.get(ctx.guild.id)
        if g is None:
            return await ctx.reply("No game is running.")
        try:
            await self.bot.service.submit(ctx.guild.id, cmd(g) if callable(cmd) else cmd)
            await ctx.reply(ok)
        except Rejected as e:
            await ctx.reply(e.reason)

    @commands.command(name="skip")
    async def skip(self, ctx):
        await self._send(ctx, lambda g: K.AdvancePhase(g.phase_id, force=True), "Phase skipped.")

    @commands.command(name="abort")
    async def abort(self, ctx):
        await self._send(ctx, K.Abort(), "Game aborted.")

    @commands.command(name="resume")
    async def resume(self, ctx):
        await self._send(ctx, K.Resume(), "Game resumed.")

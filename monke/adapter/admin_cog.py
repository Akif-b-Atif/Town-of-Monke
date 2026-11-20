"""Admin prefix commands. Usable by anyone holding the live Monke Admin role (ADM-3)."""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands

from .. import constants as C
from ..engine import Settings
from ..engine.rolelist import default_rolelist
from ..engine.settings import resolve_settings
from ..engine import commands as K
from ..errors import Rejected
from ..service.game_service import StartAborted
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

    def _t(self, key: str, state=None, **vars) -> str:
        return self.bot.presenter.composer.t(state, key, **vars)

    def _err(self, rej, state=None) -> str:
        return self.bot.presenter.composer.error(rej, state)

    async def _say(self, ctx, text: str):
        """ADM-7: every admin reply names the invoker. No pings."""
        name = discord.utils.escape_mentions(discord.utils.escape_markdown(ctx.author.display_name))
        return await ctx.reply(f"**{name}**: {text}", allowed_mentions=discord.AllowedMentions.none())

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            return
        log.exception("admin command failed", exc_info=error)
        await self._say(ctx, self._t("error.generic"))

    @commands.command(name="start")
    async def start(self, ctx, *, rest: str = ""):
        try:
            g = self.bot.service.get(ctx.guild.id)
            if g is not None and g.status in (C.STARTING, C.RUNNING, C.PAUSED):
                return await self._say(ctx, self._t("error.game_running"))
            bot_ids = {m.id for m in ctx.message.mentions if m.bot}
            req = parse_start(ctx.message.content, bot_ids)
            cfg = await self.bot.store.get_config(ctx.guild.id)
            settings, resolved = resolve_settings(cfg.server_settings, req.options, cfg.default_settings or None)
            await self._say(ctx, self._t("admin.start.starting"))
            names = {}
            for uid in req.user_ids:  # NAM-1: store each player's sanitised server name once, at start
                member = ctx.guild.get_member(uid)
                if member is None:
                    try:
                        member = await ctx.guild.fetch_member(uid)
                    except discord.HTTPException:
                        member = None
                names[uid] = sanitize_name(member.display_name if member else "")
            await self.bot.service.start_game(ctx.guild.id, req.user_ids, req.tokens or default_rolelist(len(req.user_ids)),
                                              settings, names=names, invoker_user_id=ctx.author.id,
                                              resolved=resolved)
        except Rejected as e:
            await self._say(ctx, self._t("admin.start.cant", causes=self._err(e)))
        except StartAborted as e:
            who = " ".join(f"<@{u}>" for u in e.failed_user_ids)
            await self._say(ctx, self._t("admin.start.dm_failed", causes=who))
        except Exception as e:
            log.exception("start failed")
            await self._say(ctx, self._t("error.generic"))

    @commands.command(name="status")
    async def status(self, ctx):
        g = self.bot.service.get(ctx.guild.id)
        if g is None:
            return await self._say(ctx, self._t("error.no_game"))
        ends = rel(g.phase_ends_at) if g.status == C.RUNNING else "n/a"
        await self._say(ctx, self._t("admin.status", g, status=g.status, phase=g.phase, rel=ends,
                                     alive=len(g.alive_slots()), total=len(g.players)))  # never shows roles

    async def _send(self, ctx, cmd, ok: str) -> bool:
        g = self.bot.service.get(ctx.guild.id)
        if g is None:
            await self._say(ctx, self._t("error.no_game"))
            return False
        try:
            await self.bot.service.submit(ctx.guild.id, cmd(g) if callable(cmd) else cmd)
        except Rejected as e:
            await self._say(ctx, self._err(e, g))
            return False
        await self._say(ctx, self._t(ok, g))
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
            return await self._say(ctx, self._t("admin.skip_too_soon"))
        if await self._send(ctx, lambda g: K.AdvancePhase(g.phase_id, force=True, by=sanitize_name(ctx.author.display_name, "Admin")),
                                "admin.skipped"):
            self._last_skip[ctx.guild.id] = time.time()
            await self.bot.service.record_admin_action(ctx.guild.id, ctx.author.id, "skip")  # ARC-6

    @commands.command(name="abort")
    async def abort(self, ctx):
        if await self._send(ctx, K.Abort(), "admin.abort.done"):
            await self.bot.service.record_admin_action(ctx.guild.id, ctx.author.id, "abort")  # ARC-6

    @commands.command(name="resume")
    async def resume(self, ctx):
        if await self._send(ctx, K.Resume(), "admin.resumed"):
            await self.bot.service.record_admin_action(ctx.guild.id, ctx.author.id, "resume")  # ARC-6

    @commands.command(name="export")
    async def export(self, ctx, game_id: str = ""):
        """ARC-12: rebuild and post the archive; also retries a failed end-of-game archive."""
        g = self.bot.service.get(ctx.guild.id)
        if g is not None and g.status == C.ENDED:
            await self.bot.service.record_admin_action(ctx.guild.id, ctx.author.id, "export", game_id)  # ARC-6
        elif g is not None and g.status in (C.STARTING, C.RUNNING, C.PAUSED):
            return await self._say(ctx, self._t("archive.live_refused"))
        await self._say(ctx, self._t("archive.building"))
        try:
            msg = await self.bot.service.export(ctx.guild.id, game_id or None)
        except Rejected as e:
            return await self._say(ctx, self._err(e))
        except Exception:
            log.exception("export failed")
            return await self._say(ctx, self._t("archive.export.failed"))
        await self._say(ctx, self._t(msg))

    @commands.command(name="reloadtext")
    async def reloadtext(self, ctx):
        """Reload flavour.yaml. A file with errors is rejected and the previous text stays active."""
        ok, report = self.bot.reload_text()
        if ok:
            warn = "\n".join(f"- {w}" for w in report.warnings[:15])
            msg = self._t("admin.reload.ok", count=report.keys) + (f"\n{warn}" if warn else "")
        else:
            msg = self._t("admin.reload.failed", causes="\n".join(f"- {e}" for e in report.errors[:15]))
        await self._say(ctx, msg)

    @commands.command(name="admins")
    async def admins(self, ctx):
        """ADM-6: list current Monke Admin holders."""
        cfg = await self.bot.store.get_config(ctx.guild.id)
        role = ctx.guild.get_role(cfg.admin_role_id) if cfg else None
        holders = sorted(role.members, key=lambda m: m.id) if role else []
        if not holders:
            return await self._say(ctx, self._t("admin.no_admins"))
        await self._say(ctx, self._t("admin.admins_list", names=", ".join(f"<@{m.id}>" for m in holders)))
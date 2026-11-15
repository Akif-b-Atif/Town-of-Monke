"""`monke setup` / `monke teardown` (Manage Server). Setup is idempotent."""
from __future__ import annotations

import logging
from dataclasses import asdict

import discord
from discord.ext import commands

from ..engine import Settings
from ..service.store import GuildConfig
from .planner import commands_channel_plan

log = logging.getLogger("monke.setup")

REQUIRED_PERMS = ("manage_roles", "manage_channels", "manage_messages", "view_channel", "send_messages",
                  "embed_links", "attach_files", "read_message_history", "use_application_commands")  # ARC-15: Attach Files
CHANNELS = (("monke-commands", "commands"), ("town-centre", "town"), ("mafia-lair", "mafia"),
            ("jail", "jail"), ("graveyard", "graveyard"))


class SetupError(Exception):
    """Carries a text key and variables (the renderer words it)."""

    def __init__(self, key: str, **vars):
        super().__init__(key)
        self.key, self.vars = key, vars


def _find_role(guild, rid, name):
    return (rid and guild.get_role(rid)) or discord.utils.get(guild.roles, name=name)


def commands_overwrites(guild, admin_role) -> dict:
    """Permissions for #monke-commands (ADM-1), built from the planner's static plan."""
    plan = commands_channel_plan()
    return {
        guild.default_role: discord.PermissionOverwrite(**plan["everyone"]),
        admin_role: discord.PermissionOverwrite(**plan["admin"]),
        guild.me: discord.PermissionOverwrite(**plan["bot"], manage_channels=True),
    }


async def apply_commands_channel_permissions(guild: discord.Guild, cfg: GuildConfig) -> None:
    """Re-apply the #monke-commands plan to an existing server (called at startup, ADM-1)."""
    ch = guild.get_channel(cfg.commands_channel_id)
    admin = guild.get_role(cfg.admin_role_id)
    if ch is None or admin is None:
        return
    try:
        await ch.edit(overwrites=commands_overwrites(guild, admin), reason="Town of Monke permissions")
    except discord.HTTPException:
        log.exception("could not update #monke-commands permissions in guild %s", guild.id)


async def ensure_structures(guild: discord.Guild, store) -> GuildConfig:
    me = guild.me
    missing = [p for p in REQUIRED_PERMS if not getattr(me.guild_permissions, p)]
    if missing:
        raise SetupError("admin.setup.missing_perms", causes=", ".join(missing))
    old = await store.get_config(guild.id)
    hidden = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
              me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True,
                                              read_message_history=True, embed_links=True, manage_channels=True)}
    admin = _find_role(guild, old and old.admin_role_id, "Monke Admin") or await guild.create_role(
        name="Monke Admin", permissions=discord.Permissions.none(), reason="Town of Monke setup")
    slot_roles = []
    for i in range(1, 21):
        r = _find_role(guild, old and len(old.slot_role_ids) >= i and old.slot_role_ids[i - 1], str(i))
        if r is None:
            r = await guild.create_role(name=str(i), permissions=discord.Permissions.none(), colour=discord.Colour.default(),
                                        hoist=False, mentionable=False, reason="Town of Monke setup")
        slot_roles.append(r)
    for r in [admin] + slot_roles:  # hierarchy: the bot must sit above every role it assigns
        if r >= me.top_role:
            raise SetupError("admin.setup.hierarchy", role=r.name)
    cat = (old and guild.get_channel(old.category_id)) or discord.utils.get(guild.categories, name="Town of Monke") \
        or await guild.create_category("Town of Monke", overwrites=hidden)
    ids = {}
    for name, key in CHANNELS:
        existing = (old and guild.get_channel(getattr(old, f"{key}_id" if key != "commands" else "commands_channel_id"))) \
            or discord.utils.get(cat.text_channels, name=name)
        if key == "commands":
            ow = commands_overwrites(guild, admin)
        else:
            ow = dict(hidden)
        ch = existing or await cat.create_text_channel(name, overwrites=ow)
        if existing:
            await ch.edit(overwrites=ow)
        ids[key] = ch.id
    cfg = GuildConfig(guild.id, cat.id, ids["commands"], admin.id, ids["town"], ids["mafia"], ids["jail"],
                      ids["graveyard"], [r.id for r in slot_roles], asdict(Settings()))
    await store.set_config(cfg)
    return cfg


NO_MENTIONS = discord.AllowedMentions.none()


class SetupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _t(self, key: str, **vars) -> str:
        return self.bot.presenter.composer.t(None, key, **vars)

    @commands.command(name="setup")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def setup_cmd(self, ctx):
        try:
            cfg = await ensure_structures(ctx.guild, self.bot.store)
        except SetupError as e:
            return await ctx.reply(self._t(e.key, **e.vars), allowed_mentions=NO_MENTIONS)
        msg = self._t("admin.setup.done") + "\n" + self._t("admin.setup.details", channel=cfg.commands_channel_id)
        admin_role = ctx.guild.get_role(cfg.admin_role_id)
        if admin_role is not None and not admin_role.members:
            msg += "\n" + self._t("admin.no_admins")
        await ctx.reply(msg, allowed_mentions=NO_MENTIONS)  # FIX-9: setup replies never ping

    @commands.command(name="teardown")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def teardown_cmd(self, ctx, *, flags: str = ""):
        if (g := self.bot.service.get(ctx.guild.id)) and g.status in ("STARTING", "RUNNING", "PAUSED"):
            return await ctx.reply(self._t("admin.teardown.running"), allowed_mentions=NO_MENTIONS)
        if await self.bot.store.pending_archive_games(ctx.guild.id) and "--force" not in flags.lower().split():
            return await ctx.reply(self._t("admin.teardown.pending"), allowed_mentions=NO_MENTIONS)  # ARC-15
        cfg = await self.bot.store.get_config(ctx.guild.id)
        if cfg is None:
            return await ctx.reply(self._t("admin.teardown.nothing"), allowed_mentions=NO_MENTIONS)
        for cid in (cfg.commands_channel_id, cfg.town_id, cfg.mafia_id, cfg.jail_id, cfg.graveyard_id, cfg.category_id):
            ch = ctx.guild.get_channel(cid)
            if ch and ch.id != ctx.channel.id:
                await ch.delete(reason="Town of Monke teardown")
        for rid in [cfg.admin_role_id] + cfg.slot_role_ids:
            r = ctx.guild.get_role(rid)
            if r:
                await r.delete(reason="Town of Monke teardown")
        await self.bot.store.delete_config(ctx.guild.id)
        try:
            await ctx.reply(self._t("admin.teardown.done"), allowed_mentions=NO_MENTIONS)
        except discord.HTTPException:
            pass




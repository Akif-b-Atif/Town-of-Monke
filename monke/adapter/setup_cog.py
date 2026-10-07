"""`monke setup` / `monke teardown` (Manage Server). Setup is idempotent."""
from __future__ import annotations

import logging
from dataclasses import asdict

import discord
from discord.ext import commands

from ..engine import Settings
from ..service.store import GuildConfig

log = logging.getLogger("monke.setup")

REQUIRED_PERMS = ("manage_roles", "manage_channels", "manage_messages", "view_channel", "send_messages",
                  "embed_links", "read_message_history", "use_application_commands")
CHANNELS = (("monke-commands", "commands"), ("town-centre", "town"), ("mafia-lair", "mafia"),
            ("jail", "jail"), ("graveyard", "graveyard"))


class SetupError(Exception):
    pass


def _find_role(guild, rid, name):
    return (rid and guild.get_role(rid)) or discord.utils.get(guild.roles, name=name)


async def ensure_structures(guild: discord.Guild, store) -> GuildConfig:
    me = guild.me
    missing = [p for p in REQUIRED_PERMS if not getattr(me.guild_permissions, p)]
    if missing:
        raise SetupError("I'm missing permissions: " + ", ".join(missing) + ". (Do not give me Administrator.)")
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
            raise SetupError(f"Move my role above the '{r.name}' role (Server Settings > Roles), then run setup again.")
    cat = (old and guild.get_channel(old.category_id)) or discord.utils.get(guild.categories, name="Town of Monke") \
        or await guild.create_category("Town of Monke", overwrites=hidden)
    ids = {}
    for name, key in CHANNELS:
        existing = (old and guild.get_channel(getattr(old, f"{key}_id" if key != "commands" else "commands_channel_id"))) \
            or discord.utils.get(cat.text_channels, name=name)
        ow = dict(hidden)
        if key == "commands":
            ow[admin] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        ch = existing or await cat.create_text_channel(name, overwrites=ow)
        if existing:
            await ch.edit(overwrites=ow)
        ids[key] = ch.id
    cfg = GuildConfig(guild.id, cat.id, ids["commands"], admin.id, ids["town"], ids["mafia"], ids["jail"],
                      ids["graveyard"], [r.id for r in slot_roles], asdict(Settings()))
    await store.set_config(cfg)
    return cfg


class SetupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="setup")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def setup_cmd(self, ctx):
        try:
            cfg = await ensure_structures(ctx.guild, self.bot.store)
        except SetupError as e:
            return await ctx.reply(str(e))
        await ctx.reply(f"Setup complete. Give players' host the **Monke Admin** role and run games in <#{cfg.commands_channel_id}>.\n"
                        "Server owners and Administrators can see every channel, so they should not play.")

    @commands.command(name="teardown")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def teardown_cmd(self, ctx):
        if (g := self.bot.service.get(ctx.guild.id)) and g.status in ("STARTING", "RUNNING", "PAUSED"):
            return await ctx.reply("A game is running. Use `monke abort` first.")
        cfg = await self.bot.store.get_config(ctx.guild.id)
        if cfg is None:
            return await ctx.reply("Nothing to tear down.")
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
            await ctx.reply("Teardown complete.")
        except discord.HTTPException:
            pass

"""/diagnose (ADM2-5): an embed of checks with a one-line fix for each failure. `fix:true` performs safe repairs and
never touches a running game's roles. The report is spoiler-safe: Monke Commands is public."""
from __future__ import annotations

import logging
import os

import discord

from .. import constants as C
from ..text.bank import load_text

log = logging.getLogger("monke.diagnose")
NEEDED = ("manage_roles", "manage_channels", "manage_messages", "view_channel", "send_messages", "embed_links",
          "attach_files", "read_message_history", "use_application_commands")
GAME_KEYS = ("town", "mafia", "jail", "graveyard")


def missing_permissions(perms) -> list:
    return [name for name in NEEDED if not getattr(perms, name, False)]


def _channel_ids(cfg) -> dict:
    return {"town": cfg.town_id, "mafia": cfg.mafia_id, "jail": cfg.jail_id, "graveyard": cfg.graveyard_id,
            "commands": cfg.commands_channel_id, "lobby": cfg.lobby_id}


async def check_permissions(bot, guild, cfg):
    m = missing_permissions(guild.me.guild_permissions)
    return (not m, ", ".join(m))


async def check_hierarchy(bot, guild, cfg):
    top = guild.me.top_role.position
    low = [r.name for r in (guild.get_role(i) for i in [cfg.admin_role_id] + list(cfg.slot_role_ids))
           if r is not None and r.position >= top]
    return (not low, ", ".join(low[:5]))


async def check_channels(bot, guild, cfg):
    gone = [k for k, cid in _channel_ids(cfg).items() if not cid or guild.get_channel(cid) is None]
    return (not gone, ", ".join(gone))


async def check_overwrites(bot, guild, cfg):
    bad = []
    for key in GAME_KEYS:
        ch = guild.get_channel(_channel_ids(cfg)[key])
        if ch is None:
            continue
        if ch.overwrites_for(guild.default_role).view_channel is not False:
            bad.append(f"{key}: everyone can see it")
        admin = guild.get_role(cfg.admin_role_id)
        if admin is not None and admin in ch.overwrites:
            bad.append(f"{key}: Monke Admin has extra access")
    cmd = guild.get_channel(cfg.commands_channel_id)
    if cmd is not None:
        ow = cmd.overwrites_for(guild.default_role)
        if ow.view_channel is not True or ow.send_messages is not False:
            bad.append("commands: the plan is not applied")
    return (not bad, "; ".join(bad))


async def check_slot_roles(bot, guild, cfg):
    roles = [guild.get_role(i) for i in cfg.slot_role_ids]
    bad = len(cfg.slot_role_ids) != 20 or any(r is None for r in roles) or any(r.permissions.value for r in roles if r)
    return (not bad, f"{sum(r is not None for r in roles)}/20 present")


async def check_intents(bot, guild, cfg):
    ok = bool(bot.intents.members and bot.intents.message_content)
    return (ok, "" if ok else "members or message_content is off")


async def check_database(bot, guild, cfg):
    try:
        async with bot.store.db.execute("PRAGMA quick_check") as cur:
            rows = [r[0] for r in await cur.fetchall()]
        await bot.store.db.execute("BEGIN IMMEDIATE")
        await bot.store.db.execute("ROLLBACK")
        return (rows == ["ok"], "; ".join(rows)[:100] if rows != ["ok"] else "")
    except Exception as e:
        return (False, str(e)[:100])


async def check_backups(bot, guild, cfg):
    d = bot.store.backup_dir
    ok = os.path.isdir(d) and any(f.endswith(".db") for f in os.listdir(d))
    return (ok, "" if ok else "none yet")


async def check_flavour(bot, guild, cfg):
    _bank, rep = load_text(bot.flavour_path, strict_missing=True)
    if rep.errors:
        return (False, f"{len(rep.errors)} problem(s), first: {rep.errors[0]}")
    return (True, "")


async def check_games(bot, guild, cfg):
    async with bot.store.db.execute("SELECT COUNT(*) FROM games WHERE status='QUARANTINED' AND guild_id=?",
                                    (guild.id,)) as cur:
        quarantined = (await cur.fetchone())[0]
    pending = await bot.store.pending_archive_games(guild.id)
    bad = []
    if quarantined:
        bad.append(f"{quarantined} quarantined")
    if pending:
        bad.append(f"{len(pending)} unfinished archive(s)")
    return (not bad, ", ".join(bad))


async def check_instance(bot, guild, cfg):
    import time
    others = await bot.store.other_instances(bot.guard.instance_id)
    live = [o for o in others if not o["clean_exit"] and time.time() - o["heartbeat_at"] < 20]
    return (not live, f"pid {live[0]['pid']} on {live[0]['host']}" if live else "")


async def check_debug(bot, guild, cfg):
    return (True, "")


CHECKS = [("permissions", check_permissions), ("hierarchy", check_hierarchy), ("channels", check_channels),
          ("overwrites", check_overwrites), ("slot_roles", check_slot_roles), ("intents", check_intents),
          ("database", check_database), ("backups", check_backups), ("flavour", check_flavour),
          ("games", check_games), ("instance", check_instance), ("debug", check_debug)]
REPAIRABLE = ("channels", "overwrites", "slot_roles")


async def collect(bot, guild, cfg) -> list:
    out = []
    for cid, fn in CHECKS:
        try:
            ok, detail = await fn(bot, guild, cfg)
        except Exception as e:  # a check that crashes is a failed check, not a crashed command
            log.exception("diagnose check %s failed", cid)
            ok, detail = False, repr(e)[:100]
        out.append((cid, ok, detail))
    return out


def render(c, results: list, debug_on: bool) -> dict:
    lines = []
    for cid, ok, detail in results:
        label = c.t(None, f"diagnose.check.{cid}")
        if cid == "debug":
            lines.append(c.t(None, "diagnose.debug.on" if debug_on else "diagnose.debug.off"))
        elif ok:
            lines.append(c.t(None, "diagnose.line.ok", label=label))
        else:
            lines.append(c.t(None, "diagnose.line.bad", label=label, detail=detail or "-",
                             fix=c.t(None, f"diagnose.fix.{cid}")))
    bad = [r for r in results if not r[1]]
    head = c.t(None, "admin.diagnose.problems" if bad else "admin.diagnose.ok")
    return {"title": c.t(None, "diagnose.title"), "description": (head + "\n\n" + "\n".join(lines))[:4000],
            "color": "mafia" if bad else "town"}


async def run_diagnose(bot, ctx, fix: bool) -> None:
    cfg = await bot.store.get_config(ctx.guild_id)
    c = bot.presenter.composer
    results = await collect(bot, ctx.guild, cfg)
    note = ""
    if fix and any(not ok for cid, ok, _ in results if cid in REPAIRABLE):
        game = bot.service.get(ctx.guild_id)
        running = game is not None and game.status in (C.STARTING, C.RUNNING, C.PAUSED)
        if running:  # never touch a running game's roles: only the planned channel permissions are reapplied
            await bot.presenter.apply_permissions(game, force=True)
            note = c.t(None, "diagnose.fix.skipped_running")
        else:
            from .setup_cog import ensure_structures
            await ensure_structures(ctx.guild, bot.store)
            note = c.t(None, "diagnose.fixed")
        cfg = await bot.store.get_config(ctx.guild_id)
        results = await collect(bot, ctx.guild, cfg)
    emb = bot.presenter._embed(render(c, results, bool(getattr(bot.sink, "enabled", False))))
    await ctx.reply(note or None, embed=emb)

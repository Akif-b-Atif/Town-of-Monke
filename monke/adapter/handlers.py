"""Every command handler, and the registry that lists them (CMD-1). Logic lives here once; slash commands, `monke`
prefix commands, buttons and /help are all generated from COMMANDS."""
from __future__ import annotations

import logging
import re
import time

import discord

from .. import constants as C
from ..engine import commands as K
from ..engine.rolelist import default_rolelist
from ..engine.settings import describe_settings, resolve_settings
from ..roles.registry import has_role
from ..errors import Rejected
from ..roles import get_def
from ..engine.rolecard import role_card
from ..service.game_service import StartAborted
from . import info
from .parsing import _OPTION, parse_start
from .registry import ArgSpec as A, CommandSpec
from .textutil import rel, sanitize_name

log = logging.getLogger("monke.handlers")
SKIP_GUARD_SECONDS = 3  # ADM-8
_last_skip: dict = {}


def _need_game(bot, ctx):
    g = bot.service.get(ctx.guild_id)
    if g is None:
        raise Rejected("error.no_game")
    return g


# ======================================================================================= player commands
async def h_vote(bot, ctx, player=None):
    g, slot = ctx.state, ctx.slot
    if player is None:  # CMD-2: no argument -> show where the votes stand
        return await ctx.reply(info.votes_text(bot.presenter.composer, g), ephemeral=True)
    target = info.resolve_player(g, player)
    if target is None:
        raise Rejected("error.unknown_target")
    await bot.service.submit(ctx.guild_id, K.Vote(slot, target))
    await ctx.reply(ctx.t("ui.vote.recorded"), ephemeral=True)


async def h_unvote(bot, ctx):
    await bot.service.submit(ctx.guild_id, K.Vote(ctx.slot, None))
    await ctx.reply(ctx.t("ui.vote.removed"), ephemeral=True)


async def h_votes(bot, ctx):
    await ctx.reply(info.votes_text(bot.presenter.composer, ctx.state), ephemeral=True)


async def h_alive(bot, ctx):
    await ctx.reply(info.alive_text(bot.presenter.composer, ctx.state), ephemeral=True)


async def h_rolelist(bot, ctx, count=None):
    await ctx.reply(info.rolelist_text(bot.presenter.composer, ctx.state, count), ephemeral=True)


async def h_timer(bot, ctx):
    await ctx.reply(info.timer_text(bot.presenter.composer, ctx.state), ephemeral=True)


async def h_role(bot, ctx):
    card = role_card(ctx.state, ctx.state.players[ctx.slot])
    emb = bot.presenter._embed(bot.presenter.composer.card(ctx.state, card))
    await ctx.reply(embed=emb, ephemeral=True)


async def h_help(bot, ctx):
    cfg = await bot.store.get_config(ctx.guild_id)
    is_admin = cfg is not None and any(r.id == cfg.admin_role_id for r in ctx.user.roles)
    manager = ctx.user.guild_permissions.manage_guild
    text = info.help_text(bot.presenter.composer, ctx.state, COMMANDS, ctx.slot, is_admin, manager)
    await ctx.reply(text, ephemeral=True)


async def h_resend(bot, ctx):
    n = await bot.service.resend_prompts(ctx.guild_id, ctx.user.id)
    await ctx.reply(ctx.t("ui.resend.done", count=n), ephemeral=True)


# ======================================================================================= admin commands
_YES = re.compile(r"(?:^|\s)-y(?=\s|$)")
_MENTION_ANY = re.compile(r"<@!?(\d+)>")


def _parse_start_text(bot, ctx, rest: str):
    """-> (request or None, options, yes). None means 'no players were mentioned': open a lobby (Flow A)."""
    text = rest or ""
    yes = bool(_YES.search(text))
    text = _YES.sub(" ", text)
    ids = {int(x) for x in _MENTION_ANY.findall(text)}
    if not ids:
        return None, dict(_OPTION.findall(text)), yes
    bot_ids = {uid for uid in ids if (m := ctx.guild.get_member(uid)) is not None and m.bot}
    return parse_start("monke start " + text, bot_ids), None, yes


async def c_start(bot, ctx, rest: str = ""):
    """CMD-3 / LOB-8: quick start (players but no role list) asks for confirmation, unless -y."""
    if (g := bot.service.get(ctx.guild_id)) is not None and g.status in (C.STARTING, C.RUNNING, C.PAUSED):
        raise Rejected("error.game_running")
    req, _opts, yes = _parse_start_text(bot, ctx, rest)
    if req is None or req.tokens or yes:
        return None
    cfg = await bot.store.get_config(ctx.guild_id)
    settings, _ = resolve_settings(cfg.server_settings, req.options, cfg.default_settings or None)
    tokens = default_rolelist(len(req.user_ids))  # raises if the count is not 5 to 20
    c = bot.presenter.composer
    names = ", ".join(sanitize_name(m.display_name) if (m := ctx.guild.get_member(u)) else str(u) for u in req.user_ids)
    roles = ", ".join(c.role_name(t) if has_role(t) else t for t in tokens)
    details = c.t(None, "confirm.quickstart.details", players=names, rolelist=roles,
                  settings=", ".join(f"{k}={v}" for k, v in describe_settings(settings)))
    return ("confirm.what.quickstart", {}, details)


async def h_start(bot, ctx, rest: str = ""):
    try:
        g = bot.service.get(ctx.guild_id)
        if g is not None and g.status in (C.STARTING, C.RUNNING, C.PAUSED):
            return await ctx.say(ctx.t("error.game_running"))
        req, opts, _yes = _parse_start_text(bot, ctx, rest)
        if req is None:  # Flow A: no players mentioned -> a lobby in Monke Lobby (LOB-7)
            lobby = await bot.lobbies.open(ctx.guild, ctx.user.id, options=opts)
            return await ctx.say(ctx.t("lobby.where", channel=lobby.channel_id))
        cfg = await bot.store.get_config(ctx.guild_id)
        settings, resolved = resolve_settings(cfg.server_settings, req.options, cfg.default_settings or None)
        await ctx.say(ctx.t("admin.start.starting"))
        names = {}
        for uid in req.user_ids:  # NAM-1: store each player's sanitised server name once, at start
            member = ctx.guild.get_member(uid)
            if member is None:
                try:
                    member = await ctx.guild.fetch_member(uid)
                except discord.HTTPException:
                    member = None
            names[uid] = sanitize_name(member.display_name if member else "")
        # Flow B (no list) uses the default for N; Flow C (an explicit list) is unchanged (LOB-8, LOB-9)
        await bot.service.start_game(ctx.guild_id, req.user_ids, req.tokens or default_rolelist(len(req.user_ids)),
                                     settings, names=names, invoker_user_id=ctx.user.id, resolved=resolved)
    except Rejected as e:
        await ctx.say(ctx.t("admin.start.cant", causes=ctx.err(e)))
    except StartAborted as e:
        who = " ".join(f"<@{u}>" for u in e.failed_user_ids)
        await ctx.say(ctx.t("admin.start.dm_failed", causes=who))
    except Exception:
        log.exception("start failed")
        await ctx.say(ctx.t("error.generic"))


async def h_lobby(bot, ctx, action: str = "", player=None):
    """LOB-7: `lobby add @x`, `lobby remove @x`, `lobby cancel`."""
    mgr = bot.lobbies
    lobby = await mgr.store.open_for_guild(ctx.guild_id)
    if lobby is None:
        return await ctx.say(ctx.t("lobby.none_open"))
    action = (action or "").lower()
    if action in ("add", "remove"):
        if player is None:
            raise Rejected("error.missing_arg", causes="player")
        uid = int(player)
        member = ctx.guild.get_member(uid)
        who = sanitize_name(member.display_name) if member else str(uid)
        (lobby.join if action == "add" else lobby.leave)(uid)  # an admin adds without the DM test; Start re-checks DMs
        await mgr.store.save(lobby, time.time())
        mgr.schedule_refresh(lobby.lobby_id)
        return await ctx.say(ctx.t("lobby.added" if action == "add" else "lobby.removed", player=who))
    if action == "cancel":
        await mgr._finish(lobby, "CANCELLED", "lobby.cancelled")
        return await ctx.say(ctx.t("lobby.cancelled"))
    raise Rejected("error.bad_option_nosuggest", causes=action or "lobby")


async def h_status(bot, ctx):
    g = _need_game(bot, ctx)
    ends = rel(g.phase_ends_at) if g.status == C.RUNNING else "n/a"
    await ctx.say(ctx.t("admin.status", g, status=g.status, phase=g.phase, rel=ends, alive=len(g.alive_slots()),
                        total=len(g.players)))  # never shows roles


async def _admin_submit(bot, ctx, cmd, ok_key: str, audit: str, detail: str = "") -> None:
    g = _need_game(bot, ctx)
    await bot.service.submit(ctx.guild_id, cmd(g) if callable(cmd) else cmd)
    await ctx.say(ctx.t(ok_key, g))
    await bot.service.record_admin_action(ctx.guild_id, ctx.user.id, audit, detail)  # ARC-6


def _skipped_too_soon(guild_id: int, g) -> bool:
    """ADM-8: reject a skip right after a phase change. Measured from when the phase began (FIX-4)."""
    now = time.time()
    started = getattr(g, "phase_started_at", 0)
    if started and now - started < SKIP_GUARD_SECONDS:
        return True
    return now - _last_skip.get(guild_id, 0.0) < SKIP_GUARD_SECONDS


async def c_skip(bot, ctx):
    g = _need_game(bot, ctx)
    if _skipped_too_soon(ctx.guild_id, g):
        raise Rejected("admin.skip_too_soon")
    return ("confirm.what.skip", {})


async def h_skip(bot, ctx):
    g = _need_game(bot, ctx)
    if _skipped_too_soon(ctx.guild_id, g):
        raise Rejected("admin.skip_too_soon")
    await _admin_submit(bot, ctx, lambda g: K.AdvancePhase(g.phase_id, force=True,
                                                           by=sanitize_name(ctx.user.display_name, "Admin")),
                        "admin.skipped", "skip")
    _last_skip[ctx.guild_id] = time.time()


async def c_abort(bot, ctx):
    g = _need_game(bot, ctx)
    if g.status == C.ENDED:
        raise Rejected("error.game_ended")
    return ("admin.abort.confirm", {})


async def h_abort(bot, ctx):
    await _admin_submit(bot, ctx, K.Abort(), "admin.abort.done", "abort")


async def h_resume(bot, ctx):
    await _admin_submit(bot, ctx, K.Resume(), "admin.resumed", "resume")


async def h_export(bot, ctx, game_id: str = ""):
    """ARC-12: rebuild and post the archive; also retries a failed end-of-game archive."""
    g = bot.service.get(ctx.guild_id)
    if g is not None and g.status == C.ENDED:
        await bot.service.record_admin_action(ctx.guild_id, ctx.user.id, "export", game_id)  # ARC-6
    elif g is not None and g.status in (C.STARTING, C.RUNNING, C.PAUSED):
        return await ctx.say(ctx.t("archive.live_refused"))
    await ctx.say(ctx.t("archive.building"))
    try:
        msg = await bot.service.export(ctx.guild_id, game_id or None)
    except Rejected as e:
        return await ctx.say(ctx.err(e))
    except Exception:
        log.exception("export failed")
        return await ctx.say(ctx.t("archive.export.failed"))
    await ctx.say(ctx.t(msg))


async def h_admins(bot, ctx):
    """ADM-6: list current Monke Admin holders."""
    cfg = await bot.store.get_config(ctx.guild_id)
    role = ctx.guild.get_role(cfg.admin_role_id) if cfg else None
    holders = sorted(role.members, key=lambda m: m.id) if role else []
    if not holders:
        return await ctx.say(ctx.t("admin.no_admins"))
    await ctx.say(ctx.t("admin.admins_list", names=", ".join(f"<@{m.id}>" for m in holders)))


async def h_reloadtext(bot, ctx):
    ok, report = bot.reload_text()
    if ok:
        warn = "\n".join(f"- {w}" for w in report.warnings[:15])
        msg = ctx.t("admin.reload.ok", count=report.keys) + (f"\n{warn}" if warn else "")
    else:
        msg = ctx.t("admin.reload.failed", causes="\n".join(f"- {e}" for e in report.errors[:15]))
    await ctx.say(msg)


# ======================================================================================= server commands
async def h_setup(bot, ctx):
    from .setup_cog import SetupError, ensure_structures
    try:
        cfg = await ensure_structures(ctx.guild, bot.store)
    except SetupError as e:
        return await ctx.reply(ctx.t(e.key, **e.vars))
    msg = ctx.t("admin.setup.done") + "\n" + ctx.t("admin.setup.details", channel=cfg.commands_channel_id)
    admin_role = ctx.guild.get_role(cfg.admin_role_id)
    if admin_role is not None and not admin_role.members:
        msg += "\n" + ctx.t("admin.no_admins")
    await ctx.reply(msg)  # FIX-9: setup replies never ping (Ctx.reply sets allowed_mentions=none)


async def _teardown_blocker(bot, ctx, force: bool):
    if (g := bot.service.get(ctx.guild_id)) and g.status in ("STARTING", "RUNNING", "PAUSED"):
        return "admin.teardown.running"
    if await bot.store.pending_archive_games(ctx.guild_id) and not force:
        return "admin.teardown.pending"  # ARC-15
    if await bot.store.get_config(ctx.guild_id) is None:
        return "admin.teardown.nothing"
    return None


async def c_teardown(bot, ctx, force: bool = False):
    blocker = await _teardown_blocker(bot, ctx, force)
    if blocker:
        raise Rejected(blocker)
    return ("admin.teardown.confirm", {})


async def h_teardown(bot, ctx, force: bool = False):
    blocker = await _teardown_blocker(bot, ctx, force)
    if blocker:
        return await ctx.reply(ctx.t(blocker))
    cfg = await bot.store.get_config(ctx.guild_id)
    for cid in (cfg.commands_channel_id, cfg.town_id, cfg.mafia_id, cfg.jail_id, cfg.graveyard_id, cfg.lobby_id,
                cfg.category_id):
        ch = ctx.guild.get_channel(cid)
        if ch and ch.id != ctx.channel.id:
            await ch.delete(reason="Town of Monke teardown")
    for rid in [cfg.admin_role_id] + cfg.slot_role_ids:
        r = ctx.guild.get_role(rid)
        if r:
            await r.delete(reason="Town of Monke teardown")
    await bot.store.delete_config(ctx.guild_id)
    try:
        await ctx.reply(ctx.t("admin.teardown.done"))
    except discord.HTTPException:
        pass


def _join_start(kw: dict) -> dict:
    """The slash form has separate options; the handler wants the same text the prefix form carries."""
    parts = [kw.get("players") or "", ("\n" + kw["roles"]) if kw.get("roles") else "", ("\n" + kw["options"]) if kw.get("options") else ""]
    return {"rest": " ".join(p for p in parts if p).strip()}


# ======================================================================================= the registry
COMMANDS: list = [
    # ---- players (slash) ----
    CommandSpec("vote", "player", (A("player", "player"),), h_vote, allowed_phases=(C.NOON,), alive_only=True),
    CommandSpec("unvote", "player", (), h_unvote, allowed_phases=(C.NOON,), alive_only=True),
    CommandSpec("votes", "player", (), h_votes),
    CommandSpec("alive", "player", (), h_alive),
    CommandSpec("rolelist", "player", (A("count", "int"),), h_rolelist),
    CommandSpec("timer", "player", (), h_timer),
    CommandSpec("role", "player", (), h_role),
    CommandSpec("help", "player", (), h_help),
    CommandSpec("resend", "player", (), h_resend, allowed_phases=(C.DAY_1, C.DAY, C.NOON, C.AFTERNOON, C.NIGHT),
                alive_only=False),
    # ---- admins (slash and `monke ...`) ----
    CommandSpec("start", "admin", (A("rest", "rest"),), h_start, prefix=True, confirm=c_start,
                slash_args=(A("players", "text"), A("roles", "text"), A("options", "text")), join=_join_start),
    CommandSpec("lobby", "admin", (A("action", "text", True), A("player", "member")), h_lobby, prefix=True),
    CommandSpec("status", "admin", (), h_status, prefix=True),
    CommandSpec("skip", "admin", (), h_skip, prefix=True, confirm=c_skip),
    CommandSpec("abort", "admin", (), h_abort, prefix=True, confirm=c_abort),
    CommandSpec("resume", "admin", (), h_resume, prefix=True),
    CommandSpec("export", "admin", (A("game_id", "text"),), h_export, prefix=True),
    CommandSpec("admins", "admin_any", (), h_admins, prefix=True),
    CommandSpec("reloadtext", "admin", (), h_reloadtext, prefix=True),
    # ---- server managers ----
    CommandSpec("setup", "manage_server", (), h_setup, prefix=True),
    CommandSpec("teardown", "manage_server", (A("force", "bool"),), h_teardown, prefix=True, confirm=c_teardown),
]

"""DiscordPresenter: turns engine events into messages/DMs and planner output into permission overwrites.
Decides no rules. Every method is idempotent so `reconcile` can safely repeat it."""
from __future__ import annotations

import hashlib
import inspect
import io
import logging
from typing import Optional

import discord

from .. import constants as C
from ..names import fmt_player
from ..service.store import GuildConfig, Store
from . import planner, strings as S, views
from ..debug import NullSink
from .chatlog import flatten_post
from .textutil import (MAX_CONTENT, MAX_EMBED_DESCRIPTION, MAX_EMBEDS_PER_MESSAGE, chunked, clock, rel,
                       sanitize_name, split_text)

log = logging.getLogger("monke.presenter")
NO_MENTIONS = discord.AllowedMentions.none()

GAME_CHANNELS = ("town", "mafia", "jail", "graveyard")  # the four channels send_logged serves (XC-2)


class _SafeFormat(dict):
    """format_map helper: a missing key shows '?' instead of crashing the banner."""

    def __missing__(self, key):
        return "?"


class DiscordPresenter:
    def __init__(self, bot, store: Store):
        self.bot, self.store = bot, store
        self._applied: dict = {}
        self._names: dict = {}  # game_id -> {slot: live display name}, only a fallback for pre-NAM games
        self._banners: dict = {}  # guild_id -> last pinned phase banner message
        self.sink = NullSink()  # DBG-6: set by the bot

    # ------------------------------------------------------------ lookups
    async def _cfg(self, guild_id: int) -> GuildConfig:
        cfg = await self.store.get_config(guild_id)
        if cfg is None:
            raise RuntimeError("Run `monke setup` first.")
        return cfg

    def _guild(self, guild_id: int) -> discord.Guild:
        g = self.bot.get_guild(guild_id)
        if g is None:
            raise RuntimeError(f"Guild {guild_id} not available")
        return g

    def name_of(self, state, slot: int, bold: bool = False) -> str:
        """'Maya (#3)' (NAM-2). Games that started before names were stored fall back to the live
        display name, then to 'Player 3' (NAM-1)."""
        p = state.players.get(slot)
        if p is not None and not p.display_name:
            live = self._names.get(state.game_id, {}).get(slot)
            if live:
                label = f"{sanitize_name(live)} (#{slot})"
                return f"**{label}**" if bold else label
        return fmt_player(state, slot, bold=bold)

    def _plain_name(self, state, slot: int) -> str:
        """Just the stored (or, for older games, live) name, without the '(#3)' part."""
        p = state.players.get(slot)
        if p is not None and p.display_name:
            return p.display_name
        live = self._names.get(state.game_id, {}).get(slot)
        return sanitize_name(live) if live else ""

    def mention(self, state, slot: int) -> str:
        """Kept for older call sites. Never pings: it is a plain name now."""
        return self.name_of(state, slot)

    async def _channel(self, guild_id: int, key: str) -> discord.abc.Messageable:
        cfg = await self._cfg(guild_id)
        cid = {"town": cfg.town_id, "mafia": cfg.mafia_id, "jail": cfg.jail_id,
               "graveyard": cfg.graveyard_id, "commands": cfg.commands_channel_id}[key]
        ch = self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
        return ch

    async def _fill_names(self, state) -> None:
        guild = self._guild(state.guild_id)
        names = self._names.setdefault(state.game_id, {})
        for slot, p in state.players.items():
            if slot not in names:
                m = guild.get_member(p.user_id)
                if m is None:
                    try:
                        m = await guild.fetch_member(p.user_id)
                    except discord.HTTPException:
                        continue
                names[slot] = m.display_name

    async def _dm(self, user_id: int, **kw) -> bool:
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await user.send(allowed_mentions=NO_MENTIONS, **kw)  # allow-send: DMs are not game channels
            self.sink.dm(user_id, flatten_post(kw.get("content"), kw.get("embeds") or ([kw["embed"]] if kw.get("embed") else [])))
            return True
        except (discord.Forbidden, discord.HTTPException) as e:
            log.warning("DM to %s failed: %s", user_id, e)
            return False

    # ------------------------------------------------------------ slot roles
    async def assign_slot_roles(self, state) -> None:
        guild, cfg = self._guild(state.guild_id), await self._cfg(state.guild_id)
        await self._fill_names(state)
        added = []
        try:
            for slot, p in state.players.items():
                member = guild.get_member(p.user_id) or await guild.fetch_member(p.user_id)
                await member.add_roles(guild.get_role(cfg.slot_role_ids[slot - 1]), reason="Town of Monke")
                added.append((member, slot))
        except Exception:
            for member, slot in added:
                try:
                    await member.remove_roles(guild.get_role(cfg.slot_role_ids[slot - 1]))
                except discord.HTTPException:
                    pass
            raise

    async def remove_slot_roles(self, state) -> None:
        guild, cfg = self._guild(state.guild_id), await self._cfg(state.guild_id)
        for slot, p in state.players.items():
            role = guild.get_role(cfg.slot_role_ids[slot - 1])
            try:
                member = guild.get_member(p.user_id) or await guild.fetch_member(p.user_id)
                await member.remove_roles(role, reason="Town of Monke game over")
            except discord.HTTPException:
                continue

    # ------------------------------------------------------------ role DMs (start gate)
    async def send_role_dms(self, state, events: list) -> list:
        failed = []
        for e in events:
            if e.type != "RoleAssigned":
                continue
            c, slot = e.payload, e.payload["slot"]
            emb = discord.Embed(title=f"You are the {c['role']} (Player {slot})", color=discord.Color.dark_gold())
            emb.add_field(name="Alignment", value=c["alignment"].title(), inline=True)
            emb.add_field(name="Attack / Defense", value=f"{c['attack']} / {c['defense']}", inline=True)
            emb.add_field(name="Objective", value=c["objective"], inline=False)
            emb.add_field(name="Abilities", value=c["summary"], inline=False)
            if c["special"]:
                emb.add_field(name="Special", value=c["special"], inline=False)
            if c["tips"]:
                emb.add_field(name="Tip", value=c["tips"], inline=False)
            if c["teammates"]:
                emb.add_field(name="Your Mafia team", value="\n".join(
                    f"{self.name_of(state, t['slot'])}: {t['role']}" for t in c["teammates"]), inline=False)
            if not await self._dm(state.players[slot].user_id, embed=emb):
                failed.append(state.players[slot].user_id)
        return failed

    # ------------------------------------------------------------ permissions (planner -> overwrites)
    @staticmethod
    def _perm(level: int) -> discord.PermissionOverwrite:
        if level >= planner.SEND:
            return discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        return discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True,
                                           add_reactions=False, send_messages_in_threads=False)

    async def apply_permissions(self, state, force: bool = False, archiving: bool = False) -> None:
        guild, cfg = self._guild(state.guild_id), await self._cfg(state.guild_id)
        plans = planner.plan(state, archiving=archiving)
        for key, grants in plans.items():
            sig = tuple(sorted(grants.items()))
            if not force and self._applied.get((guild.id, key)) == sig:
                continue  # apply only the diff
            ow = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True,
                                                      read_message_history=True, embed_links=True),
            }
            for slot, level in grants.items():
                role = guild.get_role(cfg.slot_role_ids[slot - 1])
                if role:
                    ow[role] = self._perm(level)
            channel = await self._channel(guild.id, key)
            await channel.edit(overwrites=ow, reason="Town of Monke permission sync")
            self._applied[(guild.id, key)] = sig

    # ------------------------------------------------------------ event rendering
    async def render(self, state, events: list) -> None:
        for e in events:
            fn = getattr(self, f"_r_{e.type}", None)
            if fn is None:
                continue
            try:
                await fn(state, e)
            except Exception:
                log.exception("rendering %s failed", e.type)

    # ------------------------------------------------------------ outbound posts (XC-2 to XC-4)
    @staticmethod
    def _split_embeds(embeds: list) -> list:
        """XC-4: an embed description over 4096 characters becomes several embeds, split at line breaks."""
        out = []
        for e in embeds:
            desc = e.description or ""
            if len(desc) <= MAX_EMBED_DESCRIPTION:
                out.append(e)
                continue
            parts = split_text(desc, MAX_EMBED_DESCRIPTION)
            first = e.copy()
            first.description = parts[0]
            out.append(first)
            out.extend(discord.Embed(description=p, color=e.color) for p in parts[1:])
        return out

    async def _record_chat(self, session, channel_kind: str, message, content=None, embeds=None) -> None:
        """ARC-3: the bot's own posts go into chat_log (kind 'bot'; embeds flattened to text)."""
        logger = getattr(self.bot, "chatlog", None)
        if logger is not None and session is not None:
            logger.log_bot(session, channel_kind, content, embeds, message)

    async def send_logged(self, channel_kind: str, content: Optional[str] = None, embeds: Optional[list] = None,
                          view=None, *, session=None, guild_id: Optional[int] = None, log: bool = True,
                          mentions: bool = False) -> list:
        """XC-2: the ONLY way the bot posts to Town Centre, Mafia Lair, Jail or Graveyard.
        Applies XC-3 (no mentions unless `mentions=True`, used only by the Graveyard welcome) and XC-4
        (split long text and long embeds, at most 10 embeds per message). Returns the sent messages."""
        if channel_kind not in GAME_CHANNELS:
            raise ValueError(f"send_logged is for game channels, not {channel_kind!r}")
        gid = guild_id if guild_id is not None else (session.guild_id if session is not None else None)
        if gid is None:
            raise ValueError("send_logged needs a session or a guild_id")
        channel = await self._channel(gid, channel_kind)
        allowed = discord.AllowedMentions(users=True) if mentions else NO_MENTIONS
        texts = split_text(content or "", MAX_CONTENT)
        batches = [list(b) for b in chunked(self._split_embeds(list(embeds or [])), MAX_EMBEDS_PER_MESSAGE)]
        count = max(len(texts), len(batches), 1 if view is not None else 0)
        sent = []
        for i in range(count):
            kw = {"allowed_mentions": allowed}
            if i < len(texts):
                kw["content"] = texts[i]
            if i < len(batches):
                kw["embeds"] = batches[i]
            if view is not None and i == count - 1:
                kw["view"] = view
            msg = await channel.send(**kw)  # allow-send: this is send_logged itself
            sent.append(msg)
            self.sink.post(gid, channel_kind, flatten_post(kw.get("content"), kw.get("embeds")))
            if log:
                try:
                    await self._record_chat(session, channel_kind, msg, kw.get("content"), kw.get("embeds"))
                except Exception:
                    log_ = logging.getLogger("monke.presenter")
                    log_.exception("could not record chat row")
        return sent

    async def _post(self, state, audience: str, **kw) -> list:
        embeds = [kw.pop("embed")] if "embed" in kw else list(kw.pop("embeds", []) or [])
        content, view = kw.get("content"), kw.get("view")
        if audience == "public":
            return await self.send_logged("town", content, embeds, view, session=state)
        if audience.startswith("alignment:"):
            return await self.send_logged("mafia", content, embeds, view, session=state)
        if audience == "admin":
            # XC-6: admin-audience events feed the archive only while a game is live.
            if state.status in (C.RUNNING, C.PAUSED):
                log.info("admin-only event not shown (game %s)", state.game_id)
                return []
            await (await self._channel(state.guild_id, "commands")).send(  # allow-send: Monke Commands
                content=content, embeds=embeds, allowed_mentions=NO_MENTIONS)
            return []
        if audience.startswith("slot:"):
            slot = int(audience.split(":")[1])
            dm = {k: v for k, v in (("content", content), ("view", view)) if v is not None}
            if embeds:
                dm["embeds"] = embeds
            if not await self._dm(state.players[slot].user_id, **dm):
                await self.notify_admin(state.guild_id, f"Could not DM <@{state.players[slot].user_id}>. "
                                                        f"They must open their DMs and use `/resend`.")
        return []

    async def notify_admin(self, guild_id: int, text: str) -> None:
        """Short, spoiler-safe notices in Monke Commands (XC-7)."""
        await (await self._channel(guild_id, "commands")).send(  # allow-send: Monke Commands
            text[:1900], allowed_mentions=NO_MENTIONS)
        self.sink.post(guild_id, "commands", text[:1900])

    def _banner_text(self, state, p: dict) -> str:
        """TRN-3: reason line, blank line, heading, deadline line (and votes needed at Noon)."""
        ctx = dict(p.get("ctx") or {})
        slot = ctx.get("target_slot")
        ctx["target"] = self.name_of(state, slot) if slot is not None else "?"
        reason = S.TRANSITION_LINES.get(p.get("reason"), S.UNKNOWN_REASON).format_map(_SafeFormat(ctx))
        if ctx.get("admin_skip"):
            reason = S.ADMIN_SKIP_PREFIX.format(name=ctx.get("admin_name") or "Admin") + " " + reason
        heading = S.PHASE_TITLE.get(p["phase"], p["phase"].title()).format_map(
            _SafeFormat(day=p["day_number"], night=p["night_number"]))
        lines = [reason, "", f"{S.PHASE_EMOJI.get(p['phase'], '')} **{heading}**".strip(),
                 S.BANNER_ENDS.format(rel=rel(p["ends_at"]), clock=clock(p["ends_at"]),
                                      alive=len(state.alive_slots()))]
        if p["phase"] == C.NOON and ctx.get("needed") is not None:
            lines.append(S.BANNER_VOTES.format(needed=ctx["needed"]))
        return "\n".join(lines)

    async def _r_PhaseChanged(self, state, e):
        sent = await self._post(state, "public", content=self._banner_text(state, e.payload))
        if not sent:
            return
        prev = self._banners.get(state.guild_id)
        if prev is not None:  # one pinned banner at a time; ignore pin failures such as the 50-pin cap
            try:
                await prev.unpin()
            except discord.HTTPException:
                pass
        try:
            await sent[0].pin(reason="Town of Monke phase banner")
        except discord.HTTPException:
            pass
        self._banners[state.guild_id] = sent[0]

    async def _r_Announcement(self, state, e):
        await self._post(state, e.audience, content=e.payload["text"])

    async def _r_PrivateMessage(self, state, e):
        await self._post(state, e.audience, content=e.payload["text"])

    async def _r_PlayerDied(self, state, e):
        await self._post(state, "public", embed=discord.Embed(description=f"💀 {e.payload['text']}", color=discord.Color.dark_red()))
        try:
            await self.send_logged("graveyard", f"{self.name_of(state, e.payload['slot'])} has joined the graveyard.",
                                   session=state)
        except Exception:
            log.exception("graveyard welcome failed")

    async def _r_VoteUpdated(self, state, e):
        p = e.payload
        voter = self.name_of(state, p["voter"], bold=True)
        if p["target"] is None:
            text = f"{voter} withdrew their vote."
        else:
            text = f"{voter} voted for {self.name_of(state, p['target'], bold=True)}. ({p['count']}/{p['threshold']})"
        await self._post(state, "public", content=text)

    async def _r_TrialStarted(self, state, e):
        d = e.payload["defendant"]
        await self._post(state, "public", content=f"⚖️ {self.name_of(state, d, bold=True)} is on trial! Only they may speak "
                                                  f"for {int(e.payload['defense_s'])} seconds.")

    async def _r_VerdictOpened(self, state, e):
        p = e.payload
        await self._post(state, "public", content=f"Cast your verdict on {self.name_of(state, p['defendant'], bold=True)} "
                                                  f"(ends <t:{int(p['ends_at'])}:R>).",
                         view=views.verdict_view(p["game_id"], p["token"]))

    async def _r_VerdictsRevealed(self, state, e):
        p = e.payload
        lines = [f"{self.name_of(state, v['slot'])}: {v['verdict']}" for v in p["votes"]]
        await self._post(state, "public", embed=discord.Embed(
            title=f"Verdict: {p['guilty']} guilty, {p['innocent']} innocent", description="\n".join(lines)))

    async def _r_RosterPosted(self, state, e):
        await self._fill_names(state)
        roster = "\n".join(f"#{r['slot']} {self._plain_name(state, r['slot'])}".rstrip() for r in e.payload["roster"])
        await self._post(state, "public", embed=discord.Embed(title=S.ROSTER_TITLE, description=roster)
                         .add_field(name=S.ROSTER_ROLELIST, value=", ".join(e.payload["rolelist"]), inline=False)
                         .set_footer(text=S.GAME_LOGGED))  # ARC-14

    async def _r_GameEnded(self, state, e):
        p = e.payload
        title = {"DRAW": "It's a draw!", "ABORTED": "The game was aborted."}.get(p["faction"], f"{p['faction'].replace('_', ' ').title()} wins!")
        lines = [f"{self.name_of(state, r['slot'], bold=True)}: {r['role']}" + ("" if r["alive"] else " ☠️") +
                 (" 🏆" if r["slot"] in p["winners"] else "") for r in p["roles"]]
        await self._post(state, "public", embed=discord.Embed(
            title=title, description="\n".join(lines)).set_footer(text=f"{p['reason']} • after day {p['days']}"))

    async def _r_PromptRequested(self, state, e):
        p = e.payload
        await self._fill_names(state)
        names = {s: self.name_of(state, s) for s in p["options"]}
        self.sink.prompt(state, int(e.audience.split(":")[1]), p["label"], p["options"])
        current = ""
        if p["kind"] == "toggle" and p["current_active"] is not None:
            current = f"\n\nCurrent choice: **{'ON' if p['current_active'] else 'OFF'}**"
        elif p["current_target"] is not None:
            current = f"\n\nCurrent choice: **{self.name_of(state, p['current_target'])}**"
        when = "tonight" if p["phase_kind"] == "NIGHT" else "today"
        await self._post(state, e.audience, content=f"**{p['label']}** ({when})" + current,
                         view=views.prompt_view(p, names))

    async def _r_JailEnded(self, state, e):
        try:
            jail = await self._channel(state.guild_id, "jail")
            await jail.purge(limit=None)
        except Exception:
            log.exception("jail purge failed")

    async def _r_StatusChanged(self, state, e):
        if e.payload["status"] == C.PAUSED:
            await self.notify_admin(state.guild_id, S.GAME_PAUSED)

    # ------------------------------------------------------------ archive (ARC-9 to ARC-11)
    async def lock_for_archive(self, state) -> None:
        """Step 1: planner mode ARCHIVING hides every game channel, so nothing is written during the build."""
        await self.apply_permissions(state, force=True, archiving=True)

    def filesize_limit(self, guild_id: int) -> int:
        return int(getattr(self._guild(guild_id), "filesize_limit", 8 * 1024 * 1024))

    async def upload_archive(self, state, summary: dict, zips: list):
        """Step 3: post one embed plus the zip(s) in Monke Commands, re-fetch each message and verify the
        attachments. Returns (message_ids, sha256_list). Raises if anything does not match."""
        channel = await self._channel(state.guild_id, "commands")
        rows = "\n".join(f"#{r['slot']:02d} {r['name']}: {r['role']}, {r['fate']}" + (" 🏆" if r["winner"] else "")
                         for r in summary["players"])
        emb = discord.Embed(title=f"Game {state.game_id} archive", description=rows[:4000],
                            color=discord.Color.dark_gold())
        emb.add_field(name="Result", value=f"{summary['winner']}: {summary['reason']}"[:1000], inline=False)
        emb.add_field(name="Length", value=f"{summary['duration_s'] // 60} min, {summary['days']} days", inline=True)
        ids, hashes = [], []
        for gi, group in enumerate(chunked(zips, 10)):
            kw = {"files": [discord.File(io.BytesIO(data), filename=name) for name, data in group],
                  "allowed_mentions": NO_MENTIONS}
            if gi == 0:
                kw["embed"] = emb
            msg = await channel.send(**kw)  # allow-send: the archive upload goes to Monke Commands
            fetched = await channel.fetch_message(msg.id)
            got = {a.filename: a.size for a in fetched.attachments}
            want = {name: len(data) for name, data in group}
            if got != want:
                raise RuntimeError(f"upload verification failed: {got} != {want}")
            ids.append(msg.id)
            hashes += [hashlib.sha256(data).hexdigest() for _, data in group]
        return ids, hashes

    async def archive_messages_exist(self, guild_id: int, ids: list) -> bool:
        channel = await self._channel(guild_id, "commands")
        try:
            for mid in ids:
                await channel.fetch_message(mid)
        except discord.HTTPException:
            return False
        return True

    @staticmethod
    async def _pins(channel) -> list:
        res = channel.pins()  # a list in older discord.py, an async iterator in newer ones
        if inspect.isawaitable(res):
            return list(await res)
        return [m async for m in res]

    async def purge_game_channels(self, guild_id: int) -> None:
        """Step 4: empty all four game channels (pins included) and verify, up to 3 tries each. Messages older
        than 14 days cannot be bulk-deleted; discord.py then deletes them one by one (slower, ARC-17)."""
        for key in GAME_CHANNELS:
            channel = await self._channel(guild_id, key)
            for attempt in range(1, 4):
                gone = await channel.purge(limit=None)
                log.info("purged %s: %d messages (attempt %d)", key, len(gone), attempt)
                empty = not [m async for m in channel.history(limit=1)]
                if empty and not await self._pins(channel):
                    break
            else:
                raise RuntimeError(f"could not empty {key}")

    async def send_separators(self, state, summary: dict) -> None:
        """Step 5: a DM separator for every participant. Failures are logged and ignored (ARC-11)."""
        text = S.SEPARATOR.format(game_id=state.game_id, result=f"Result: {summary['winner']} ({summary['reason']})")
        for p in state.players.values():
            await self._dm(p.user_id, content=text)

    # ------------------------------------------------------------ reconcile / cleanup
    async def reconcile(self, state) -> None:
        """Repair missing slot roles and refill the name cache. Prompt views are DynamicItems, so they
        are already 'registered' by the bot. Permissions are re-applied by the caller (force=True)."""
        guild, cfg = self._guild(state.guild_id), await self._cfg(state.guild_id)
        await self._fill_names(state)
        for slot, p in state.players.items():
            if state.status == C.ENDED or p.state.get("inactive"):
                continue
            role = guild.get_role(cfg.slot_role_ids[slot - 1])
            try:
                member = guild.get_member(p.user_id) or await guild.fetch_member(p.user_id)
            except discord.HTTPException:
                continue
            if role and role not in member.roles:
                await member.add_roles(role, reason="Town of Monke reconcile")

    async def cleanup(self, state) -> None:
        """Post-game teardown: remove slot roles and hide every game channel."""
        await self.remove_slot_roles(state)
        await self.apply_permissions(_Hidden(state), force=True)
        try:
            for key in ("town", "mafia", "graveyard"):
                await (await self._channel(state.guild_id, key)).purge(limit=None)
        except Exception:
            log.exception("channel purge failed")


class _Hidden:
    """A stand-in 'no game' state so the planner hides everything between games."""

    def __init__(self, state):
        self.guild_id, self.status, self.players = state.guild_id, C.STARTING, {}

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
import asyncio

from .. import compose as composer
from . import info
from ..text.bank import default_bank
from ..service.outbox import GuildWriter, Retryable, is_retryable
from ..text.keys import TEXT_KEYS
from . import planner, views
from ..debug import NullSink
from .chatlog import flatten_post
from .textutil import (MAX_CONTENT, MAX_EMBED_DESCRIPTION, MAX_EMBEDS_PER_MESSAGE, chunked, clock, rel,
                       sanitize_name, split_text)

log = logging.getLogger("monke.presenter")
NO_MENTIONS = discord.AllowedMentions.none()

GAME_CHANNELS = ("town", "mafia", "jail", "graveyard")  # the four channels send_logged serves (XC-2)


class DiscordPresenter:
    def __init__(self, bot, store: Store, bank=None):
        self.bot, self.store = bot, store
        self.composer = composer.Composer(bank or default_bank(), namer=self.name_of)  # TXT-2: the only text path
        self._applied: dict = {}
        self._names: dict = {}  # game_id -> {slot: live display name}, only a fallback for pre-NAM games
        self._banners: dict = {}  # guild_id -> last pinned phase banner message
        self.sink = NullSink()  # DBG-6: set by the bot
        self._writers: dict = {}  # guild_id -> GuildWriter (REL-17)
        self._panels: dict = {}  # game_id -> (phase_id, message): the live vote panel (CMD-5)
        self._panel_tasks: dict = {}
        self._prompts: dict = {}  # game_id -> [{token, kind, message, label}] for QOL-8

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

    def writer(self, guild_id: int) -> GuildWriter:
        """All Discord writes for a guild go through one ordered worker (REL-17)."""
        return self._writers.setdefault(guild_id, GuildWriter())

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

    async def _dm(self, user_id: int, **kw):
        """-> the sent message (truthy), or False when the player cannot be reached (closed DMs)."""
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            msg = await user.send(allowed_mentions=NO_MENTIONS, **kw)  # allow-send: DMs are not game channels
            self.sink.dm(user_id, flatten_post(kw.get("content"), kw.get("embeds") or ([kw["embed"]] if kw.get("embed") else [])))
            return msg or True
        except discord.Forbidden as e:  # closed DMs: permanent, reported to the admin, never retried
            log.warning("DM to %s failed: %s", user_id, e)
            return False
        except discord.HTTPException as e:
            if is_retryable(e):
                raise  # REL-7: 5xx and 429 keep the event unrendered so it is retried, not lost
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
            slot = e.payload["slot"]
            emb = self._embed(self.composer.card(state, e.payload))
            view = views.card_view(state.game_id, bool(e.payload.get("kills")), self.composer.card_labels(state))
            if not await self._dm(state.players[slot].user_id, embed=emb, view=view):
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
        """P0: a transition's permissions complete before its announcements (REL-17, DEAD-1)."""
        await self.writer(state.guild_id).run(
            GuildWriter.P0, lambda: self._apply_permissions(state, force, archiving))

    async def _apply_permissions(self, state, force: bool = False, archiving: bool = False) -> None:
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

    async def notify_admin(self, guild_id: int, key: str, **vars) -> None:
        """Short, spoiler-safe notices in Monke Commands (XC-7). `key` is a text key (or already-worded text)."""
        state = self.bot.service.get(guild_id) if getattr(self.bot, "service", None) else None
        text = self.composer.t(state, key, **vars) if key in TEXT_KEYS else key
        await (await self._channel(guild_id, "commands")).send(  # allow-send: Monke Commands
            text[:1900], allowed_mentions=NO_MENTIONS)
        self.sink.post(guild_id, "commands", text[:1900])

    # ------------------------------------------------------------ event rendering (TXT-2)
    @staticmethod
    def _embed(d: dict) -> discord.Embed:
        color = composer.COLORS.get(d.get("color"), d.get("color") if isinstance(d.get("color"), int) else None)
        emb = discord.Embed(title=d.get("title"), description=d.get("description"),
                            color=discord.Color(color) if color is not None else None)
        for name, value, inline in d.get("fields", []):
            emb.add_field(name=name[:256], value=value[:1024], inline=inline)
        if d.get("footer"):
            emb.set_footer(text=d["footer"])
        return emb

    def _view(self, spec):
        if spec is None:
            return None
        if spec[0] == "verdict":
            return views.verdict_view(spec[1], spec[2], spec[3] if len(spec) > 3 else None)
        if spec[0] == "card":
            return views.card_view(spec[1], spec[2], spec[3])
        if spec[0] == "panel":
            return views.panel_view(spec[1], spec[2], spec[3], spec[4], spec[5])
        return views.prompt_view(spec[1], spec[2], spec[3], spec[4])

    async def render(self, state, events: list, outbox=None) -> None:
        """Deliver events. Retryable Discord failures propagate (the service keeps the event unrendered and
        retries); anything else is logged and skipped. `outbox` makes every message exactly-once (REL-7)."""
        for e in events:
            if e.type == "RoleAssigned":
                continue  # role cards go out through send_role_dms, the start gate
            try:
                msgs = self.composer.compose(state, e)
            except Exception:
                log.exception("composing %s failed", e.type)
                continue
            for m in msgs:
                try:
                    await self._deliver(state, e, m, outbox)
                except Exception as exc:
                    if is_retryable(exc):
                        raise
                    log.exception("rendering %s failed", e.type)
            try:
                if e.type == "PhaseChanged":
                    await self._after_phase(state)
                elif e.type == "VoteUpdated":
                    self._schedule_panel_refresh(state)
            except Exception:
                log.exception("post-phase housekeeping failed")

    # ---- vote panel (CMD-5) and prompt hygiene (QOL-8) ----
    PANEL_DEBOUNCE = 1.0

    def _schedule_panel_refresh(self, state) -> None:
        """Edit the live tally at most once a second (priority P3, latest wins) instead of reposting."""
        gid = state.game_id
        if gid in self._panel_tasks or gid not in self._panels:
            return

        async def run():
            try:
                await asyncio.sleep(self.PANEL_DEBOUNCE)
                st = self.bot.service.get(state.guild_id) or state
                panel = self._panels.get(gid)
                if panel is None or st.phase != C.NOON or panel[0] != st.phase_id:
                    return
                emb = self._embed(info.tally_embed(self.composer, st))
                await self.writer(st.guild_id).run(GuildWriter.P3, lambda: panel[1].edit(embed=emb),
                                                   key=("panel", gid))
            except Exception:
                log.exception("could not refresh the vote panel")
            finally:
                self._panel_tasks.pop(gid, None)
        self._panel_tasks[gid] = asyncio.create_task(run())

    async def _after_phase(self, state) -> None:
        """When a phase changes: close the vote panel and expire old prompts ('Expired: ...', components removed).
        Failures are ignored: the buttons are already dead (their freshness token no longer matches)."""
        panel = self._panels.get(state.game_id)
        if panel is not None and (state.phase != C.NOON or panel[0] != state.phase_id):
            self._panels.pop(state.game_id, None)
            emb = self._embed(info.tally_embed(self.composer, state))
            try:
                await self.writer(state.guild_id).run(GuildWriter.P3, lambda: panel[1].edit(embed=emb, view=None))
            except Exception:
                log.debug("could not close the vote panel", exc_info=True)
        kept = []
        for entry in self._prompts.get(state.game_id, []):
            if state.token_for(entry["kind"]) == entry["token"]:
                kept.append(entry)
                continue
            text = self.composer.t(state, "ui.prompt.expired", what=entry["label"])
            try:
                await self.writer(state.guild_id).run(GuildWriter.P3, lambda e=entry: e["message"].edit(content=text, view=None))
            except Exception:
                log.debug("could not expire a prompt", exc_info=True)
        self._prompts[state.game_id] = kept

    async def _send(self, state, outbox, target: str, priority: int, fn):
        """One message: through the guild's ordered writer, and through the outbox when there is one."""
        async def go():
            return await self.writer(state.guild_id).run(priority, fn)
        return await (outbox.once(target, go) if outbox is not None else go())

    async def _deliver(self, state, e, m, outbox=None) -> list:
        if m.meta.get("admin_only"):
            if state.status in (C.RUNNING, C.PAUSED):  # XC-6: admin-audience events feed the archive only while live
                log.info("admin-only event not shown (game %s)", state.game_id)
                return []
        if m.effect == "purge_jail":
            try:
                await (await self._channel(state.guild_id, "jail")).purge(limit=None)
            except Exception:
                log.exception("jail purge failed")
            return []
        embeds = [self._embed(m.embed)] if m.embed else []
        view = self._view(m.view)
        if m.target in GAME_CHANNELS:
            sent = await self._send(state, outbox, m.target, GuildWriter.P1, lambda: self.send_logged(
                m.target, m.content or None, embeds, view, session=state, mentions=m.mentions))
            if m.effect == "banner" and sent:
                await self._pin_banner(state, sent[0])
            elif m.effect == "panel" and sent:
                self._panels[state.game_id] = (m.meta["phase_id"], sent[0])
                try:  # remembered with the outbox so a restart can find the panel again
                    await self.store.outbox_add(state.game_id, -int(m.meta["phase_id"]), 0, "panel", sent[0].id)
                except Exception:
                    log.exception("could not store the vote panel message id")
            elif m.effect == "pin" and sent:
                try:
                    await sent[0].pin(reason="Town of Monke")
                except discord.HTTPException:
                    pass
            return sent
        if m.target == "commands":
            await self._send(state, outbox, "commands", GuildWriter.P1,
                             lambda: self.notify_admin(state.guild_id, m.content))
            return []
        if m.target.startswith("slot:"):
            slot = int(m.target.split(":")[1])
            dm = {k: v for k, v in (("content", m.content or None), ("view", view)) if v is not None}
            if embeds:
                dm["embeds"] = embeds
            if m.view and m.view[0] == "prompt":
                self.sink.prompt(state, slot, m.meta.get("label", ""), m.view[1]["options"])
            ok = await self._send(state, outbox, f"dm:{slot}", GuildWriter.P2,
                                  lambda: self._dm(state.players[slot].user_id, **dm))
            if m.view and m.view[0] == "prompt" and ok:  # QOL-8: remember it so it can be expired
                p = m.view[1]
                self._prompts.setdefault(state.game_id, []).append(
                    {"token": p["token"], "kind": p["phase_kind"], "message": ok, "label": m.meta.get("label", "")})
            if ok is False:  # a permanent failure (closed DMs): reported, and counted as rendered
                await self.notify_admin(state.guild_id, self.composer.t(state, "admin.dm_failed", player=slot))
        return []

    async def _pin_banner(self, state, message) -> None:
        prev = self._banners.get(state.guild_id)
        if prev is not None:  # one pinned banner at a time; ignore pin failures such as the 50-pin cap
            try:
                await prev.unpin()
            except discord.HTTPException:
                pass
        try:
            await message.pin(reason="Town of Monke phase banner")
        except discord.HTTPException:
            pass
        self._banners[state.guild_id] = message
        try:  # FIX-6: remembered across restarts, so recovery can unpin the old banner
            await self.store.set_banner_message(state.game_id, message.id)
        except Exception:
            log.exception("could not store the banner message id")

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
        c, win = self.composer, self.composer.t(state, "ui.emoji.winner")
        rows = "\n".join(c.t(state, "archive.embed.player", slot=f"{r['slot']:02d}", name=r["name"], role=r["role"],
                             fate=r["fate"]) + (f" {win}" if r["winner"] else "") for r in summary["players"])
        emb = discord.Embed(title=c.t(state, "archive.embed.title", game_id=state.game_id), description=rows[:4000],
                            color=discord.Color(composer.COLORS["gold"]))
        emb.add_field(name=c.t(state, "archive.embed.result"), value=f"{summary['winner']}: {summary['reason']}"[:1000],
                      inline=False)
        emb.add_field(name="\u200b", value=c.t(state, "archive.embed.length", minutes=summary["duration_s"] // 60,
                                                days=summary["days"]), inline=True)
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
        text = self.composer.t(state, "archive.separator", game_id=state.game_id,
                               result=f"{summary['winner']} ({summary['reason']})")
        for p in state.players.values():
            await self._dm(p.user_id, content=text)

    # ------------------------------------------------------------ reconcile / cleanup
    async def reconcile(self, state) -> None:
        """Repair missing slot roles and refill the name cache. Prompt views are DynamicItems, so they
        are already 'registered' by the bot. Permissions are re-applied by the caller (force=True)."""
        guild, cfg = self._guild(state.guild_id), await self._cfg(state.guild_id)
        await self._fill_names(state)
        try:
            await self.reconcile_banner(state)
        except discord.HTTPException:
            log.exception("could not reconcile the pinned banner")
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

    @staticmethod
    async def _pins(channel) -> list:
        res = channel.pins()
        if hasattr(res, "__aiter__"):  # discord.py 2.6+ returns an async iterator
            return [m async for m in res]
        return list(await res)

    async def reconcile_banner(self, state) -> None:
        """FIX-6: unpin every old bot banner in Town Centre and keep the current one pinned."""
        if state.status not in (C.RUNNING, C.PAUSED):
            return
        town = await self._channel(state.guild_id, "town")
        mine = [m for m in await self._pins(town) if m.author.id == self.bot.user.id]
        keep = await self.store.banner_message(state.game_id)
        if mine and keep not in {m.id for m in mine}:
            keep = max(m.id for m in mine)
            await self.store.set_banner_message(state.game_id, keep)
        for m in mine:
            if m.id != keep:
                try:
                    await m.unpin()
                except discord.HTTPException:
                    pass
        current = next((m for m in mine if m.id == keep), None)
        if current is not None:
            self._banners[state.guild_id] = current

    # ---- recovery helpers (REL-4, REL-9) ----
    async def structures_missing(self, state) -> list:
        """Names of game channels or slot roles that no longer exist. Never creates anything (REL-4 step 3)."""
        cfg = await self._cfg(state.guild_id)
        guild = self._guild(state.guild_id)
        out = []
        for key, cid in (("town", cfg.town_id), ("mafia", cfg.mafia_id), ("jail", cfg.jail_id),
                         ("graveyard", cfg.graveyard_id), ("commands", cfg.commands_channel_id)):
            if self.bot.get_channel(cid) is None:
                try:
                    await self.bot.fetch_channel(cid)
                except discord.NotFound:
                    out.append(key)
                except discord.HTTPException:
                    raise  # Discord trouble is not 'missing'
        for slot in state.players:
            if slot - 1 >= len(cfg.slot_role_ids) or guild.get_role(cfg.slot_role_ids[slot - 1]) is None:
                out.append(f"slot role #{slot}")
        return out

    async def members_missing(self, state) -> list:
        guild = self._guild(state.guild_id)
        gone = []
        for slot, p in state.players.items():
            if not p.alive or p.state.get("inactive"):
                continue
            if guild.get_member(p.user_id) is not None:
                continue
            try:
                await guild.fetch_member(p.user_id)
            except discord.NotFound:
                gone.append(slot)
        return gone

    async def fetch_history_after(self, state, kind: str, after_id) -> list:
        """Messages in a game channel after the highest logged one, as chat_log rows (REL-9)."""
        channel = await self._channel(state.guild_id, kind)
        after = discord.Object(id=after_id) if after_id else None
        rows = []
        async for msg in channel.history(limit=1000, after=after, oldest_first=True):
            bot = msg.author.bot
            rows.append({
                "ts_ms": int(msg.created_at.timestamp() * 1000), "kind": "bot" if bot else "msg",
                "message_id": msg.id, "author_user_id": None if bot else msg.author.id,
                "author_name": "Bot" if bot else sanitize_name(msg.author.display_name),
                "content": flatten_post(msg.content, msg.embeds) if bot else (msg.content or ""),
                "attachments": [{"filename": a.filename, "size": a.size, "url": a.url} for a in msg.attachments]})
        return rows

    async def jail_gap(self, state, rows: list) -> None:
        """REL-9: tell the Jail, and DM the Jailor a digest of what the prisoner said while the bot was offline."""
        await self.send_logged("jail", self.composer.t(state, "rel.jail_gap"), session=state)
        jailor = next((p for p in state.players.values() if p.role_id == "jailor" and p.alive), None)
        if jailor is None:
            return
        digest = "\n".join(f"- {r['content'][:120]}" for r in rows[:10]) or "-"
        await self._dm(jailor.user_id, content=self.composer.t(state, "rel.jailor_gap", count=len(rows),
                                                                digest=digest))

    async def send_logged_plain(self, channel, **kw):
        """A post in Monke Lobby (spoiler-safe, public, never pings: PRES-2, PRES-6)."""
        return await channel.send(allowed_mentions=NO_MENTIONS, **kw)  # allow-send: Monke Lobby

    async def dm_key(self, state, slot: int, key: str, **vars) -> None:
        await self._dm(state.players[slot].user_id, content=self.composer.t(state, key, **vars))

    async def post_key(self, state, channel: str, key: str, **vars) -> None:
        await self.send_logged(channel, self.composer.t(state, key, **vars), session=state)

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

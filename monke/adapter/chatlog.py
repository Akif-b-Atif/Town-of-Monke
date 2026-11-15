"""ARC-3: turns Discord chat events into chat_log rows. Writes go through the capture queue so chat
never waits on the database. DMs are never logged, except through the jail relay."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from ..archive.channels import CHANNEL_KINDS, session_for
from .textutil import sanitize_name

log = logging.getLogger("monke.chatlog")
CONFIG_TTL = 60.0


def flatten_embed(e) -> str:
    """Embeds become plain text: title, description, fields, footer."""
    parts = []
    if getattr(e, "title", None):
        parts.append(str(e.title))
    if getattr(e, "description", None):
        parts.append(str(e.description))
    for f in getattr(e, "fields", []) or []:
        name, value = (f if isinstance(f, tuple) else (f.name, f.value))
        parts.append(f"{name}: {value}")
    footer = getattr(e, "footer", None)
    text = getattr(footer, "text", footer if isinstance(footer, str) else None)
    if text:
        parts.append(str(text))
    return "\n".join(parts)


def flatten_post(content: Optional[str], embeds: Optional[list]) -> str:
    parts = [content] if content else []
    parts += [flatten_embed(e) for e in (embeds or [])]
    return "\n".join(p for p in parts if p)


class ChatLogger:
    def __init__(self, bot):
        self.bot = bot
        self._cfg: dict = {}

    async def _config(self, guild_id: int):
        hit = self._cfg.get(guild_id)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        cfg = await self.bot.store.get_config(guild_id)
        self._cfg[guild_id] = (time.monotonic() + CONFIG_TTL, cfg)
        return cfg

    def invalidate(self, guild_id: Optional[int] = None) -> None:
        if guild_id is None:
            self._cfg.clear()
        else:
            self._cfg.pop(guild_id, None)

    @staticmethod
    def _kind_of(cfg, channel_id: int) -> Optional[str]:
        if cfg is None:
            return None
        for kind, k in CHANNEL_KINDS.items():
            if getattr(cfg, k.config_attr, None) == channel_id:
                return kind
        return None

    def _live_game(self, guild_id: int):
        g = self.bot.service.get(guild_id)
        if g is None or self.bot.capture.is_closed(g.game_id):
            return None
        return g

    def _put(self, row: dict) -> None:
        self.bot.capture.put(row)

    # ---------------------------------------------------------------- human messages
    async def on_message(self, message) -> None:
        if message.guild is None or message.author.bot:
            return
        g = self._live_game(message.guild.id)
        if g is None:
            return
        kind = self._kind_of(await self._config(message.guild.id), message.channel.id)
        if kind is None:
            return
        slot = g.slot_of_user(message.author.id)
        stored = g.players[slot].display_name if slot is not None else ""
        sink = getattr(self.bot, "sink", None)  # DBG-3: debug mode shows only the length of human chat
        if sink is not None:
            sink.chat(g, kind, slot, stored or sanitize_name(message.author.display_name), message.content or "")
        self._put({
            "game_id": g.game_id, "ts_ms": int(message.created_at.timestamp() * 1000), "channel_kind": kind,
            "session": session_for(kind, g.night_number), "kind": "msg", "message_id": message.id,
            "author_user_id": message.author.id, "author_slot": slot,
            "author_name": stored or sanitize_name(message.author.display_name),
            "content": message.content or "",
            "attachments": [{"filename": a.filename, "size": a.size, "url": a.url} for a in message.attachments],
        })

    async def on_raw_edit(self, payload) -> None:
        g = self._live_game(payload.guild_id) if payload.guild_id else None
        content = (payload.data or {}).get("content")
        if g is None or content is None:
            return
        kind = self._kind_of(await self._config(payload.guild_id), payload.channel_id)
        if kind is None:
            return
        ts = time.time()
        stamp = (payload.data or {}).get("edited_timestamp")
        if stamp:
            try:
                ts = datetime.fromisoformat(stamp).timestamp()
            except ValueError:
                pass
        self._put({"game_id": g.game_id, "ts_ms": int(ts * 1000), "channel_kind": kind,
                   "session": session_for(kind, g.night_number), "kind": "edit", "message_id": payload.message_id,
                   "content": content})

    async def on_raw_delete(self, payload) -> None:
        g = self._live_game(payload.guild_id) if payload.guild_id else None
        if g is None:
            return
        kind = self._kind_of(await self._config(payload.guild_id), payload.channel_id)
        if kind is None:
            return
        self._put({"game_id": g.game_id, "ts_ms": int(time.time() * 1000), "channel_kind": kind,
                   "session": session_for(kind, g.night_number), "kind": "delete", "message_id": payload.message_id,
                   "content": ""})

    # ---------------------------------------------------------------- the bot's own posts and the jail relay
    def log_bot(self, state, channel_kind: str, content, embeds, message) -> None:
        if state is None or self.bot.capture.is_closed(state.game_id):
            return
        created = getattr(message, "created_at", None)
        ts = int(created.timestamp() * 1000) if created is not None else int(time.time() * 1000)
        self._put({"game_id": state.game_id, "ts_ms": ts, "channel_kind": channel_kind,
                   "session": session_for(channel_kind, state.night_number), "kind": "bot",
                   "message_id": getattr(message, "id", None), "author_name": "Bot",
                   "content": flatten_post(content, embeds)})

    async def log_jailor(self, state, text: str, message_id: Optional[int]) -> None:
        """The relay logs only Jailor-to-prisoner text, under the Jailor's slot (prisoner text is logged by on_message)."""
        jailor = next((p for p in state.players.values() if p.role_id == "jailor"), None)
        if jailor is None or self.bot.capture.is_closed(state.game_id):
            return
        self._put({"game_id": state.game_id, "ts_ms": int(time.time() * 1000), "channel_kind": "jail",
                   "session": session_for("jail", state.night_number), "kind": "msg", "message_id": message_id,
                   "author_user_id": jailor.user_id, "author_slot": jailor.slot,
                   "author_name": jailor.display_name or "Jailor", "content": text})

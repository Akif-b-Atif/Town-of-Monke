"""The Monke Lobby (LOB-6 to LOB-10): the lobby embed with Join, Leave, Start, Edit Settings, Edit Role List and
Cancel; quick start; rematch. Buttons are persistent (dynamic items), so they work across restarts. Start, Edit and
Cancel check the live Monke Admin role of whoever presses (D25)."""
from __future__ import annotations

import asyncio
import logging
import time

import discord

from .. import constants as C
from ..engine.rolelist import split_tokens, validate_rolelist
from ..engine.settings import resolve_settings
from ..errors import Rejected
from ..service.game_service import StartAborted
from ..service.lobby import CANCELLED, EXPIRED, OPEN, REMATCH, STARTED, Lobby, LobbyStore
from .textutil import sanitize_name

log = logging.getLogger("monke.lobby")
DEBOUNCE = 1.0  # edits are debounced to one per second (LOB-7)
ACTS = ("join", "leave", "start", "settings", "roles", "cancel")


class LobbyManager:
    def __init__(self, bot):
        self.bot = bot
        self.store = LobbyStore(bot.store)
        self._edit_tasks: dict = {}
        self._sweeper = None

    # ------------------------------------------------------------------ helpers
    def _c(self):
        return self.bot.presenter.composer

    def t(self, key: str, **vars) -> str:
        return self._c().t(None, key, **vars)

    async def _names(self, guild, lobby) -> dict:
        names = {}
        for uid in set(lobby.players) | {lobby.opener_user_id}:
            m = guild.get_member(uid)
            names[uid] = sanitize_name(m.display_name) if m else str(uid)
        return names

    async def _timeout(self, guild_id: int) -> float:
        cfg = await self.bot.store.get_config(guild_id)
        try:
            return resolve_settings(cfg.server_settings if cfg else {}, {})[0].lobby_timeout_s
        except Exception:
            return 1800.0

    async def _is_admin(self, member, guild_id: int) -> bool:
        cfg = await self.bot.store.get_config(guild_id)
        return cfg is not None and any(r.id == cfg.admin_role_id for r in getattr(member, "roles", []))

    # ------------------------------------------------------------------ rendering (debounced)
    async def render(self, lobby: Lobby, status_key: str = "", with_view: bool = True) -> dict:
        guild = self.bot.get_guild(lobby.guild_id)
        timeout = await self._timeout(lobby.guild_id)
        emb = self.bot.presenter._embed(self._c().lobby_embed(lobby, await self._names(guild, lobby), timeout, status_key))
        return {"embed": emb, "view": lobby_view(self._c(), lobby.lobby_id) if with_view else None}

    def schedule_refresh(self, lobby_id: str) -> None:
        if lobby_id in self._edit_tasks:
            return

        async def run():
            try:
                await asyncio.sleep(DEBOUNCE)
                lobby = await self.store.get(lobby_id)
                if lobby is None or not lobby.message_id:
                    return
                ch = self.bot.get_channel(lobby.channel_id)
                msg = ch.get_partial_message(lobby.message_id)
                await msg.edit(**await self.render(lobby))
            except Exception:
                log.exception("lobby refresh failed")
            finally:
                self._edit_tasks.pop(lobby_id, None)
        self._edit_tasks[lobby_id] = asyncio.create_task(run())

    async def _finish(self, lobby: Lobby, status: str, status_key: str) -> None:
        """Close a lobby: no more buttons, and say why."""
        lobby.status = status
        await self.store.save(lobby, time.time())
        try:
            ch = self.bot.get_channel(lobby.channel_id)
            await ch.get_partial_message(lobby.message_id).edit(**await self.render(lobby, status_key, with_view=False))
        except Exception:
            log.debug("could not close the lobby message", exc_info=True)

    # ------------------------------------------------------------------ opening (Flow A) and rematch
    async def open(self, guild, opener_user_id: int, players=None, options=None) -> Lobby:
        cfg = await self.bot.store.get_config(guild.id)
        if cfg is None or not cfg.lobby_id:
            raise Rejected("error.not_set_up")
        existing = await self.store.open_for_guild(guild.id)
        if existing is not None:
            await self._finish(existing, CANCELLED, "lobby.cancelled")
        lobby = Lobby.new(guild.id, opener_user_id, time.time(), players, options)
        lobby.channel_id = cfg.lobby_id
        ch = guild.get_channel(cfg.lobby_id) or await guild.fetch_channel(cfg.lobby_id)
        await self.store.save(lobby)
        msg = await self.bot.presenter.send_logged_plain(ch, **await self.render(lobby))
        lobby.message_id = msg.id
        await self.store.save(lobby)
        return lobby

    async def save_rematch(self, state) -> None:
        """Remember who played and how (LOB-10), so the game-over Play Again button can open a pre-filled lobby."""
        keep = Lobby(state.game_id, state.guild_id, state.players[min(state.players)].user_id,
                     players=[p.user_id for p in state.players.values()],
                     options=dict(state.settings_resolved.get("layers", {}).get("game", {})), status=REMATCH,
                     created_at=time.time(), updated_at=time.time())
        await self.store.save(keep)

    async def rematch(self, interaction: discord.Interaction, game_id: str) -> None:
        old = await self.store.get(game_id)
        if old is None or old.status != REMATCH:
            return await interaction.response.send_message(self.t("error.stale_prompt"), ephemeral=True)
        present = [u for u in old.players if interaction.guild.get_member(u) is not None]
        if not present:
            return await interaction.response.send_message(self.t("lobby.rematch_empty"), ephemeral=True)
        try:
            lobby = await self.open(interaction.guild, interaction.user.id, present, old.options)
        except Rejected as e:
            return await interaction.response.send_message(self._c().error(e), ephemeral=True)
        await interaction.response.send_message(self.t("lobby.where", channel=lobby.channel_id), ephemeral=True)

    # ------------------------------------------------------------------ buttons
    async def press(self, interaction: discord.Interaction, act: str, lobby_id: str) -> None:
        lobby = await self.store.get(lobby_id)
        if lobby is None or lobby.status != OPEN:
            return await interaction.response.send_message(self.t("error.stale_prompt"), ephemeral=True)
        user = interaction.user
        if act in ("settings", "roles", "start", "cancel") and not await self._is_admin(user, lobby.guild_id):
            return await interaction.response.send_message(self.t("error.not_admin"), ephemeral=True)  # live check
        if act == "join":
            return await self._join(interaction, lobby)
        if act == "leave":
            try:
                lobby.leave(user.id)
            except Rejected as e:
                return await interaction.response.send_message(self._c().error(e), ephemeral=True)
            await self.store.save(lobby, time.time())
            self.schedule_refresh(lobby_id)
            return await interaction.response.send_message(self.t("lobby.left"), ephemeral=True)
        if act == "cancel":
            await interaction.response.defer()
            return await self._finish(lobby, CANCELLED, "lobby.cancelled")
        if act == "settings":
            return await interaction.response.send_modal(SettingsModal(self, lobby))
        if act == "roles":
            return await interaction.response.send_modal(RolesModal(self, lobby))
        if act == "start":
            return await self._start(interaction, lobby)

    async def _join(self, interaction: discord.Interaction, lobby: Lobby) -> None:
        user = interaction.user
        try:
            lobby.join(user.id)
        except Rejected as e:
            return await interaction.response.send_message(self._c().error(e), ephemeral=True)
        try:  # Join sends a test DM and refuses, with instructions, if DMs are closed (LOB-7)
            await user.send(self.t("lobby.joined"), allowed_mentions=discord.AllowedMentions.none())  # allow-send: test DM
        except discord.Forbidden:
            lobby.leave(user.id)
            return await interaction.response.send_message(self.t("lobby.dm_closed"), ephemeral=True)
        await self.store.save(lobby, time.time())
        self.schedule_refresh(lobby.lobby_id)
        await interaction.response.send_message(self.t("lobby.joined"), ephemeral=True)

    def blocked_text(self, e: Rejected) -> str:
        causes = self._c().error(e.vars["inner"]) if "inner" in e.vars else ""
        return self._c().t(None, e.key, count=e.vars.get("count", 0), causes=causes)

    async def _start(self, interaction: discord.Interaction, lobby: Lobby) -> None:
        try:
            lobby.check_start()
        except Rejected as e:
            return await interaction.response.send_message(self.blocked_text(e), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        try:
            settings, resolved = resolve_settings((await self.bot.store.get_config(guild.id)).server_settings, lobby.options)
            names = {}
            for uid in lobby.players:
                m = guild.get_member(uid) or await guild.fetch_member(uid)
                names[uid] = sanitize_name(m.display_name)
            await self.bot.service.start_game(guild.id, list(lobby.players), lobby.rolelist(), settings, names=names,
                                              invoker_user_id=interaction.user.id, resolved=resolved)
        except Rejected as e:
            return await interaction.followup.send(self._c().error(e), ephemeral=True)  # allow-send: ephemeral
        except StartAborted as e:
            who = " ".join(f"<@{u}>" for u in e.failed_user_ids)
            return await interaction.followup.send(self.t("admin.start.dm_failed", causes=who), ephemeral=True)  # allow-send
        await self._finish(lobby, STARTED, "lobby.started")
        await interaction.followup.send(self.t("lobby.started"), ephemeral=True)  # allow-send: ephemeral

    # ------------------------------------------------------------------ expiry (lobby_timeout of inactivity)
    def start_sweeper(self) -> None:
        if self._sweeper is None:
            self._sweeper = asyncio.create_task(self._sweep_forever())

    async def _sweep_forever(self) -> None:
        while True:
            try:
                await self.sweep(time.time())
            except Exception:
                log.exception("lobby sweep failed")
            await asyncio.sleep(60)

    async def sweep(self, now: float) -> int:
        n = 0
        for lobby in await self.store.all_open():
            if now - lobby.updated_at > await self._timeout(lobby.guild_id):
                await self._finish(lobby, EXPIRED, "lobby.expired")
                n += 1
        return n

    # ------------------------------------------------------------------ edits from the modals
    async def apply_settings(self, lobby_id: str, text: str) -> None:
        options = {}
        for line in text.replace(",", "\n").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                options[k.strip().lower()] = v.strip()
        resolve_settings({}, options)  # validates; raises Rejected with a did-you-mean
        lobby = await self.store.get(lobby_id)
        lobby.options = options
        await self.store.save(lobby, time.time())
        self.schedule_refresh(lobby_id)

    async def apply_rolelist(self, lobby_id: str, text: str) -> None:
        tokens = split_tokens(text)
        lobby = await self.store.get(lobby_id)
        if tokens:
            validate_rolelist(tokens, len(tokens))  # unknown entries are named now; the count is checked at Start
        lobby.tokens = tokens or None
        await self.store.save(lobby, time.time())
        self.schedule_refresh(lobby_id)


class SettingsModal(discord.ui.Modal):
    def __init__(self, mgr: LobbyManager, lobby: Lobby):
        super().__init__(title=mgr.t("lobby.modal.settings_title")[:45])
        self.mgr, self.lobby_id = mgr, lobby.lobby_id
        self.box = discord.ui.TextInput(label=mgr.t("lobby.modal.settings_label")[:45], style=discord.TextStyle.paragraph,
                                        required=False, default="\n".join(f"{k}={v}" for k, v in lobby.options.items()),
                                        max_length=500)
        self.add_item(self.box)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.mgr.apply_settings(self.lobby_id, self.box.value)
        except Rejected as e:
            return await interaction.response.send_message(self.mgr._c().error(e), ephemeral=True)
        await interaction.response.defer()


class RolesModal(discord.ui.Modal):
    def __init__(self, mgr: LobbyManager, lobby: Lobby):
        super().__init__(title=mgr.t("lobby.modal.rolelist_title")[:45])
        self.mgr, self.lobby_id = mgr, lobby.lobby_id
        self.box = discord.ui.TextInput(label=mgr.t("lobby.modal.rolelist_label")[:45], style=discord.TextStyle.paragraph,
                                        required=False, placeholder=mgr.t("lobby.modal.rolelist_hint")[:100],
                                        default=", ".join(lobby.tokens or []), max_length=500)
        self.add_item(self.box)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.mgr.apply_rolelist(self.lobby_id, self.box.value)
        except Rejected as e:
            return await interaction.response.send_message(self.mgr._c().error(e), ephemeral=True)
        await interaction.response.defer()


# ---------------------------------------------------------------------------------------- persistent buttons
_LABELS = {"join": "ui.button.join", "leave": "ui.button.leave", "start": "ui.button.start",
           "settings": "ui.button.edit_settings", "roles": "ui.button.edit_rolelist", "cancel": "ui.button.cancel"}
_STYLES = {"join": discord.ButtonStyle.success, "start": discord.ButtonStyle.primary, "cancel": discord.ButtonStyle.danger}


class LobbyButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"monke:lobby:(?P<act>join|leave|start|settings|roles|cancel):(?P<id>[0-9a-f]+)"):
    def __init__(self, act: str, lobby_id: str, label: str = ""):
        self.act, self.lobby_id = act, lobby_id
        super().__init__(discord.ui.Button(label=label or act.title(), custom_id=f"monke:lobby:{act}:{lobby_id}",
                                           style=_STYLES.get(act, discord.ButtonStyle.secondary)))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["act"], match["id"])

    async def callback(self, interaction: discord.Interaction):
        await interaction.client.lobbies.press(interaction, self.act, self.lobby_id)


class RematchButton(discord.ui.DynamicItem[discord.ui.Button], template=r"monke:again:(?P<id>[0-9a-f]+)"):
    def __init__(self, game_id: str, label: str = ""):
        self.game_id = game_id
        super().__init__(discord.ui.Button(label=label or "Play again", custom_id=f"monke:again:{game_id}",
                                           style=discord.ButtonStyle.primary))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["id"])

    async def callback(self, interaction: discord.Interaction):
        await interaction.client.lobbies.rematch(interaction, self.game_id)


def lobby_view(composer, lobby_id: str) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    for act in ACTS:
        v.add_item(LobbyButton(act, lobby_id, composer.t(None, _LABELS[act])))
    return v


def rematch_view(composer, game_id: str) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(RematchButton(game_id, composer.t(None, "ui.button.play_again")))
    return v


DYNAMIC_ITEMS = (LobbyButton, RematchButton)

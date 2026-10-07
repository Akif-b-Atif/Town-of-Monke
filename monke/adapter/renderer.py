"""DiscordPresenter: turns engine events into messages/DMs and planner output into permission overwrites.
Decides no rules. Every method is idempotent so `reconcile` can safely repeat it."""
from __future__ import annotations

import logging
from typing import Optional

import discord

from .. import constants as C
from ..service.store import GuildConfig, Store
from . import planner, views

log = logging.getLogger("monke.presenter")
NO_MENTIONS = discord.AllowedMentions.none()

PHASE_TITLES = {
    C.DAY_1: "☀️ Day 1", C.DAY: "☀️ Day {day}", C.NOON: "🗳️ Noon: voting is open",
    C.TRIAL_DEFENSE: "⚖️ Defense", C.TRIAL_VERDICT: "⚖️ Verdict", C.AFTERNOON: "🌇 Afternoon",
    C.NIGHT: "🌙 Night {night}",
}


class DiscordPresenter:
    def __init__(self, bot, store: Store):
        self.bot, self.store = bot, store
        self._applied: dict = {}
        self._names: dict = {}  # game_id -> {slot: display name}

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

    def name_of(self, state, slot: int) -> str:
        n = self._names.get(state.game_id, {}).get(slot)
        return f"#{slot} {n}" if n else f"Player {slot}"

    def mention(self, state, slot: int) -> str:
        return f"<@{state.players[slot].user_id}> (#{slot})"

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
            await user.send(allowed_mentions=NO_MENTIONS, **kw)
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
                    f"Player {t['slot']}: {t['role']}" for t in c["teammates"]), inline=False)
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

    async def apply_permissions(self, state, force: bool = False) -> None:
        guild, cfg = self._guild(state.guild_id), await self._cfg(state.guild_id)
        plans = planner.plan(state)
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

    async def _post(self, state, audience: str, **kw) -> None:
        kw.setdefault("allowed_mentions", NO_MENTIONS)
        if audience == "public":
            await (await self._channel(state.guild_id, "town")).send(**kw)
        elif audience == "admin":
            await (await self._channel(state.guild_id, "commands")).send(**kw)
        elif audience.startswith("alignment:"):
            await (await self._channel(state.guild_id, "mafia")).send(**kw)
        elif audience.startswith("slot:"):
            slot = int(audience.split(":")[1])
            kw.pop("allowed_mentions")
            if not await self._dm(state.players[slot].user_id, **kw):
                await self.notify_admin(state.guild_id, f"Could not DM <@{state.players[slot].user_id}>. "
                                                        f"They must open their DMs and use `/resend`.")

    async def notify_admin(self, guild_id: int, text: str) -> None:
        await (await self._channel(guild_id, "commands")).send(text[:1900], allowed_mentions=NO_MENTIONS)

    async def _r_PhaseChanged(self, state, e):
        p = e.payload
        title = PHASE_TITLES.get(p["phase"])
        if title:
            await self._post(state, "public", content=f"**{title.format(day=p['day_number'], night=p['night_number'])}** "
                                                      f"(ends <t:{int(p['ends_at'])}:R>)")

    async def _r_Announcement(self, state, e):
        await self._post(state, e.audience, content=e.payload["text"])

    async def _r_PrivateMessage(self, state, e):
        await self._post(state, e.audience, content=e.payload["text"])

    async def _r_PlayerDied(self, state, e):
        await self._post(state, "public", embed=discord.Embed(description=f"💀 {e.payload['text']}", color=discord.Color.dark_red()))
        try:
            grave = await self._channel(state.guild_id, "graveyard")
            await grave.send(f"{self.mention(state, e.payload['slot'])} has joined the graveyard.", allowed_mentions=NO_MENTIONS)
        except Exception:
            log.exception("graveyard welcome failed")

    async def _r_VoteUpdated(self, state, e):
        p = e.payload
        voter = self.mention(state, p["voter"])
        if p["target"] is None:
            text = f"{voter} withdrew their vote."
        else:
            text = f"{voter} voted for {self.mention(state, p['target'])}. ({p['count']}/{p['threshold']})"
        await self._post(state, "public", content=text)

    async def _r_TrialStarted(self, state, e):
        d = e.payload["defendant"]
        await self._post(state, "public", content=f"⚖️ {self.mention(state, d)} is on trial! Only they may speak "
                                                  f"for {int(e.payload['defense_s'])} seconds.")

    async def _r_VerdictOpened(self, state, e):
        p = e.payload
        await self._post(state, "public", content=f"Cast your verdict on {self.mention(state, p['defendant'])} "
                                                  f"(ends <t:{int(p['ends_at'])}:R>).",
                         view=views.verdict_view(p["game_id"], p["token"]))

    async def _r_VerdictsRevealed(self, state, e):
        p = e.payload
        lines = [f"{self.mention(state, v['slot'])}: {v['verdict']}" for v in p["votes"]]
        await self._post(state, "public", embed=discord.Embed(
            title=f"Verdict: {p['guilty']} guilty, {p['innocent']} innocent", description="\n".join(lines)))

    async def _r_RosterPosted(self, state, e):
        roster = "\n".join(f"**{r['slot']}**: <@{r['user_id']}>" for r in e.payload["roster"])
        await self._post(state, "public", embed=discord.Embed(title="Town of Monke: the game begins", description=roster)
                         .add_field(name="Role list", value=", ".join(e.payload["rolelist"]), inline=False))

    async def _r_GameEnded(self, state, e):
        p = e.payload
        title = {"DRAW": "It's a draw!", "ABORTED": "The game was aborted."}.get(p["faction"], f"{p['faction'].replace('_', ' ').title()} wins!")
        lines = [f"**{r['slot']}** <@{r['user_id']}>: {r['role']}" + ("" if r["alive"] else " ☠️") +
                 (" 🏆" if r["slot"] in p["winners"] else "") for r in p["roles"]]
        await self._post(state, "public", embed=discord.Embed(
            title=title, description="\n".join(lines)).set_footer(text=f"{p['reason']} • after day {p['days']}"))

    async def _r_PromptRequested(self, state, e):
        p = e.payload
        await self._fill_names(state)
        names = {s: self.name_of(state, s) for s in p["options"]}
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
            await self.notify_admin(state.guild_id, f"Game paused. {e.payload.get('reason', '')}")

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

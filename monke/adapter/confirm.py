"""Confirm / Cancel buttons (CMD-3). Any Monke Admin may press them, checked live when pressed; they expire after 60 s."""
from __future__ import annotations

import logging

import discord

log = logging.getLogger("monke.confirm")


class ConfirmView(discord.ui.View):
    def __init__(self, bot, guild_id: int, on_confirm, labels: dict, expired_text: str, cancelled_text: str,
                 timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.bot, self.guild_id, self.on_confirm = bot, guild_id, on_confirm
        self.expired_text, self.cancelled_text = expired_text, cancelled_text
        self.message = None
        yes = discord.ui.Button(label=labels["confirm"], style=discord.ButtonStyle.danger)
        no = discord.ui.Button(label=labels["cancel"], style=discord.ButtonStyle.secondary)
        yes.callback, no.callback = self._yes, self._no
        self.add_item(yes)
        self.add_item(no)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        cfg = await self.bot.store.get_config(self.guild_id)
        member = interaction.user
        ok = cfg is not None and any(r.id == cfg.admin_role_id for r in getattr(member, "roles", []))  # ADM-3: live
        if not ok:
            await interaction.response.send_message(self.bot.presenter.composer.t(None, "error.not_admin"),
                                                    ephemeral=True)
        return ok

    async def _yes(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.edit_message(view=None)
        await self.on_confirm(interaction)

    async def _no(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.edit_message(content=self.cancelled_text, view=None)

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(content=self.expired_text, view=None)
            except discord.HTTPException:
                pass

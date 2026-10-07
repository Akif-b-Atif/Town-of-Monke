"""Player slash commands: /vote, /unvote, /resend."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .. import constants as C
from ..engine import commands as K
from ..errors import Rejected


class PlayerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _slot(self, interaction):
        g = self.bot.service.get(interaction.guild_id)
        slot = g.slot_of_user(interaction.user.id) if g else None
        return g, slot

    async def _vote(self, interaction: discord.Interaction, target_user_id):
        g, slot = self._slot(interaction)
        if g is None or slot is None:
            return await interaction.response.send_message("You are not in a game here.", ephemeral=True)
        target = None
        if target_user_id is not None:
            target = g.slot_of_user(target_user_id)
            if target is None:
                return await interaction.response.send_message("That player is not in the game.", ephemeral=True)
        try:
            await self.bot.service.submit(interaction.guild_id, K.Vote(slot, target))
        except Rejected as e:
            return await interaction.response.send_message(e.reason, ephemeral=True)
        await interaction.response.send_message("Vote recorded." if target else "Vote removed.", ephemeral=True)

    @app_commands.command(name="vote", description="Vote to put a player on trial (Noon only)")
    @app_commands.guild_only()
    async def vote(self, interaction: discord.Interaction, player: discord.Member):
        await self._vote(interaction, player.id)

    @app_commands.command(name="unvote", description="Withdraw your vote")
    @app_commands.guild_only()
    async def unvote(self, interaction: discord.Interaction):
        await self._vote(interaction, None)

    @app_commands.command(name="resend", description="Resend your current action prompt")
    @app_commands.guild_only()
    async def resend(self, interaction: discord.Interaction):
        try:
            n = await self.bot.service.resend_prompts(interaction.guild_id, interaction.user.id)
        except Rejected as e:
            return await interaction.response.send_message(e.reason, ephemeral=True)
        await interaction.response.send_message(f"Sent {n} prompt(s) to your DMs.", ephemeral=True)

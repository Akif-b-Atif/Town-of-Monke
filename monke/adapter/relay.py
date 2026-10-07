"""Anonymous Jail relay: Jailor DM <-> Jail channel, active only during the night with a prisoner."""
from __future__ import annotations

import logging

import discord

from .. import constants as C

log = logging.getLogger("monke.relay")
NO_MENTIONS = discord.AllowedMentions.none()


class JailRelay:
    def __init__(self, bot):
        self.bot = bot

    def _live(self):
        return [g for g in self.bot.service.games.values()
                if g.status == C.RUNNING and g.phase == C.NIGHT and g.prisoner_slot is not None]

    async def handle(self, message: discord.Message) -> bool:
        """Returns True if the message was relayed."""
        if message.author.bot or not message.content:
            return False
        text = message.content[:1800]
        if message.guild is None:  # DM from the Jailor -> Jail channel
            for g in self._live():
                jailor = next((p for p in g.players.values() if p.role_id == "jailor"), None)
                if jailor and jailor.alive and jailor.user_id == message.author.id:
                    if text.lower().startswith("monke "):
                        return False
                    cfg = await self.bot.store.get_config(g.guild_id)
                    ch = self.bot.get_channel(cfg.jail_id) or await self.bot.fetch_channel(cfg.jail_id)
                    await ch.send(f"**Jailor:** {text}", allowed_mentions=NO_MENTIONS)
                    await message.add_reaction("✅")
                    return True
            return False
        g = self.bot.service.get(message.guild.id)  # prisoner in Jail channel -> Jailor DM
        if g is None or g not in self._live():
            return False
        cfg = await self.bot.store.get_config(g.guild_id)
        if cfg is None or message.channel.id != cfg.jail_id:
            return False
        if g.players[g.prisoner_slot].user_id != message.author.id:
            return False
        jailor = next((p for p in g.players.values() if p.role_id == "jailor"), None)
        if jailor is None:
            return False
        try:
            user = self.bot.get_user(jailor.user_id) or await self.bot.fetch_user(jailor.user_id)
            await user.send(f"**Prisoner:** {text}", allowed_mentions=NO_MENTIONS)
        except discord.HTTPException:
            log.warning("could not relay to the Jailor")
        return True

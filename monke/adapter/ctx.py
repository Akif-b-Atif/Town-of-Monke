"""One context for a command, whether it came from a slash command, a button, or a `monke ...` message."""
from __future__ import annotations

import discord

NO_MENTIONS = discord.AllowedMentions.none()


class Ctx:
    def __init__(self, bot, guild, channel, user, message=None, interaction=None):
        self.bot, self.guild, self.channel, self.user = bot, guild, channel, user
        self.message, self.interaction = message, interaction
        self.state = None  # set by the dispatcher for player commands
        self.slot = None

    @property
    def guild_id(self) -> int:
        return self.guild.id

    def name(self) -> str:
        return discord.utils.escape_mentions(discord.utils.escape_markdown(self.user.display_name))

    async def reply(self, text=None, *, embed=None, view=None, ephemeral: bool = False):
        """Reply wherever the command came from. Ephemeral only exists for slash commands and buttons. Never pings."""
        if self.interaction is not None:
            kw = {"allowed_mentions": NO_MENTIONS, "ephemeral": ephemeral}
            if text is not None:
                kw["content"] = text
            if embed is not None:
                kw["embed"] = embed
            if view is not None:
                kw["view"] = view
            if self.interaction.response.is_done():
                return await self.interaction.followup.send(**kw)  # allow-send: a command reply
            await self.interaction.response.send_message(**kw)
            try:
                return await self.interaction.original_response()
            except discord.HTTPException:
                return None
        kw = {"allowed_mentions": NO_MENTIONS, "mention_author": False}
        if embed is not None:
            kw["embed"] = embed
        if view is not None:
            kw["view"] = view
        return await self.message.reply(text or None, **kw)

    async def say(self, text: str, **kw):
        """ADM-7: every admin reply names the person who ran the command."""
        return await self.reply(f"**{self.name()}**: {text}", **kw)

    def t(self, key: str, state=None, **vars) -> str:
        return self.bot.presenter.composer.t(state if state is not None else self.state, key, **vars)

    def err(self, rej) -> str:
        return self.bot.presenter.composer.error(rej, self.state)

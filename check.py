import os
import discord
from dotenv import load_dotenv

load_dotenv()

class Check(discord.Client):
    async def on_ready(self):
        print("Logged in as:", self.user, "| application id:", self.user.id)
        print("Servers the bot is in:", [(g.name, g.id) for g in self.guilds] or "NONE")
        print("Invite URL:", discord.utils.oauth_url(
            self.user.id,
            permissions=discord.Permissions(2416012304),
            scopes=("bot", "applications.commands"),
        ))
        await self.close()

Check(intents=discord.Intents.none()).run(os.environ["DISCORD_TOKEN"])
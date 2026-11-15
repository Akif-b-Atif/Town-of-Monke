import os
import discord
from dotenv import load_dotenv

load_dotenv()

# The permissions the bot needs (keep in sync with REQUIRED_PERMS in monke/adapter/setup_cog.py).
# Attach Files was added in 1.0.1 for the post-game archive upload. Administrator is deliberately NOT included.
PERMISSIONS = discord.Permissions(
    manage_roles=True,
    manage_channels=True,
    manage_messages=True,
    view_channel=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    read_message_history=True,
    use_application_commands=True,
)


class Check(discord.Client):
    async def on_ready(self):
        print("Logged in as:", self.user, "| application id:", self.user.id)
        print("Servers the bot is in:", [(g.name, g.id) for g in self.guilds] or "NONE")
        print("Invite URL:", discord.utils.oauth_url(
            self.user.id,
            permissions=PERMISSIONS,
            scopes=("bot", "applications.commands"),
        ))
        await self.close()

Check(intents=discord.Intents.none()).run(os.environ["DISCORD_TOKEN"])

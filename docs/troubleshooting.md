# Troubleshooting and FAQ

Find your symptom, then follow the fix. Run **`monke diagnose`** first for anything that looks like a setup problem.

## Contents

- [Players](#players)
- [Admins and commands](#admins-and-commands)
- [Setup and permissions](#setup-and-permissions)
- [During a game](#during-a-game)
- [After a game](#after-a-game)
- [Running the bot](#running-the-bot)

## Players

**"I could not DM you" when pressing Join, or "Start aborted. These players must open their DMs".**
Open your DMs for the server: *Server name > Privacy Settings > Direct Messages*. Press **Join** again.

**I did not get a role card.**
Check that DMs from server members are on, and that you are in the game (`/alive` lists players). Use `/role` to show the card
again. If the game could not DM you at the start, it would have been aborted.

**I pressed a button and it says it is stale or expired.**
Prompts expire when their phase ends. Use `/resend` to get a fresh one, or `/help` to see what you can do now.

**I cannot vote.**
Voting only works at **Noon**, and only for living players. You cannot vote for yourself or someone already pardoned today.
Check `/timer`.

**I cannot see #mafia-lair or #jail or #graveyard.**
Working as intended: those channels appear only to those who should see them. The Graveyard is for the dead.

**I cannot type in #town-centre.**
It is read-only at night, during the Verdict, and during the Defense unless you are the accused. Dead players cannot write
there either.

**I was removed from the game for being AFK.**
Three days in a row without voting, acting, pressing a button or talking in Town Centre removes you. See
[AFK rules](rules.md#inactivity-afk).

**The Jailor's messages do not appear for the prisoner (or vice versa).**
Relay happens only at night while a prisoner exists. The Jailor's reply must be sent as a **DM to the bot** and must not
start with `monke `. A ✅ appears on a message that was relayed.

## Admins and commands

**I type `monke start` and nothing happens.**
By design the bot stays silent if the message is from someone without the **Monke Admin** role, or is sent outside
`#monke-commands`. Check both. Try the slash version `/start` to see an error message. `monke admins` lists who has the role.

**"This server is not set up yet."**
A server manager (someone with Manage Server) must run `monke setup`.

**"Only the Monke Admin can use that command."**
Give yourself or the host the **Monke Admin** role.

**"A game is already running" or "starting".**
Only one game can run per server. Use `monke status`, and `monke abort` if it is stuck.

**"Start aborted ... open their DMs".**
Those players must enable DMs. If someone left the server, remove them from the lobby.

**A new game will not start because of the archive.**
The previous game's archive has not finished. Try `monke export`. If that fails, check `monke diagnose` and the bot's log.

**The role list is rejected.**
Common causes: the wrong number of entries (it must equal the player count), no Jailor or no Godfather, or a unique role
repeated. See [Role list rules](role-lists-and-settings.md#rules). The error names the problem.

**"Did you mean ...?" for a setting.**
Typos in `key=value` are caught. Use the suggested key.

**My `monke teardown` is refused.**
Either a game is in progress, or an archive is unfinished. Finish or `monke export`, or use `monke teardown --force`.

## Setup and permissions

**`monke setup` says a permission is missing.**
Give the bot the permission it names (see [the list](hosting.md#4-invite-the-bot)). Re-invite it with the URL from `python check.py`
if needed.

**`monke setup` says a role is above the bot.**
Server Settings > Roles. Drag the bot's role above `Monke Admin` and `1` to `20`.

**`monke diagnose` reports "members or message_content is off".**
This is a known quirk in 1.1.0. The check looks for the *Server Members* intent, which the bot does not currently request.
If **Message Content Intent** is on in the Developer Portal, you can ignore this line. Other failures in the report are
real.

**Admin commands are visible but not usable.**
Admins need the **Monke Admin** role, and `use_application_commands` must not be blocked in `#monke-commands`. Run
`monke setup` to restore the channel permissions.

**Slash commands do not appear.**
Re-invite the bot with the `applications.commands` scope. Discord can take a few minutes to refresh the list. Restarting
Discord helps.

**Channels or permissions look wrong.**
Run `monke diagnose --fix`. If that does not help, `monke setup` rebuilds anything missing.

## During a game

**The game seems stuck.**
`monke status` for the phase and time left. Then try `monke skip`. If a prompt is stuck, players can `/resend`. As a last
resort `monke abort`.

**Someone's DMs are failing mid-game (their prompts do not arrive).**
They must allow DMs. If they cannot, `monke replace` them.

**A player disconnected.**
Use `monke pause` while they come back, `monke replace` to swap them for someone else, or leave them to be removed as AFK.

**The bot went offline in the middle of a game.**
Start it again. The game resumes where it was, with the clock frozen during the downtime.

**A message is missing from the channel.**
Failed posts are retried in order. If the bot is rate limited, messages arrive late but in order.

**A player is on trial but we are not sure why.**
Votes are public and counted live. `/votes` shows the tally at Noon.

## After a game

**The archive zip did not appear.**
Run `monke export`. It rebuilds the last game's archive and posts it in `#monke-commands`. Large zips are split to fit
the server's upload limit. The bot needs **Attach Files**.

**The game channels are empty.**
That is the cleanup after the archive. The data is in the zip.

**Can I replay a game?**
Yes, for debugging: `python -m monke.sim.replay path/to/game.json` replays an archived `data/game.json` and prints the first
divergence.

## Running the bot

**"Set DISCORD_TOKEN ..."**
Put your token in `.env` or the environment. See [Hosting](hosting.md#3-create-the-discord-application).

**"Another copy seems to be running."**
Stop the other copy. If it crashed hard and left a lock, use `python -m monke --force-takeover`.

**"Database damaged".**
The integrity check failed. Stop the bot, copy the latest file from `backups/` over `monke.db`, and start again.

**It will not start in a server that is already set up, saying the database is new.**
You probably started it from the wrong folder or lost the database. Restore a backup, or use `--new-db` if you really want to
start from scratch.

**Message Content errors on startup.**
Turn on the **Message Content Intent** under Bot > Privileged Gateway Intents.

**I want to see exactly what happened.**
Logs are in `logs/`. For deeper debugging, `python -m monke --debug` prints every role and decision (do not use it in a live
game with players watching), and `python -m monke.sim.cli --games 1 --seed 7 --debug` shows a simulated game.

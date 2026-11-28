# Hosting the bot

How to install, configure and run Town of Monke. This is for whoever **operates** the bot. If you only want to host
games in a server where the bot already runs, you want the [Admin guide](admin-guide.md).

## Contents

1. [Requirements](#1-requirements)
2. [Install](#2-install)
3. [Create the Discord application](#3-create-the-discord-application)
4. [Invite the bot](#4-invite-the-bot)
5. [Run it](#5-run-it)
6. [Configuration reference](#configuration-reference)
7. [Command-line options](#command-line-options)
8. [Keeping it running](#keeping-it-running)
9. [Data, backups and logs](#data-backups-and-logs)
10. [Updating](#updating)
11. [Customising text](#customising-text)

## 1. Requirements

- **Python 3.11 or newer**
- A Discord account that can create an application
- A machine that stays on while games are running (a VPS, a Raspberry Pi, a spare computer)
- A Discord **server** where you have **Manage Server**

The bot stores everything in a local **SQLite** file. No separate database is needed.

## 2. Install

```bash
git clone https://github.com/Akif-b-Atif/Town-of-Monke.git
cd Town-of-Monke
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```

`requirements.txt` includes `pytest` for the tests. The bot itself needs `discord.py`, `aiosqlite`, `python-dotenv` and
`PyYAML`.

## 3. Create the Discord application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Open **Bot**.
3. Click **Reset Token** and copy the token. **Keep it secret.** Anyone with it controls your bot.
4. Under **Privileged Gateway Intents**, turn on **Message Content Intent**. It is required for the `monke ...` text
   commands and for the anonymous Jail chat.
5. Paste the token in `.env`: `DISCORD_TOKEN=...`

The bot also uses the non-privileged Guilds, Guild Messages and Direct Messages intents. You do not need to enable
anything else.

> **Never commit `.env`.** It is already in `.gitignore`.

## 4. Invite the bot

With your token in `.env`, run:

```bash
python check.py
```

It logs in, prints the **permissions number** and an **invite URL**, and exits. Open the URL and choose your server.

The permissions are: Manage Roles, Manage Channels, Manage Messages, View Channels, Send Messages, Embed Links, Attach
Files, Read Message History, Use Application Commands (integer **2416045072**, scopes `bot` and
`applications.commands`). **Do not give Administrator.**

To make the invite yourself instead, use the Developer Portal's **OAuth2 URL Generator**, select the `bot` and
`applications.commands` scopes and those permissions.

After inviting, follow [One-time server setup](admin-guide.md#one-time-server-setup).

## 5. Run it

```bash
python -m monke
```

On start it prints the database path and the log file path. Leave it running.

Keep it running while games are on. If the bot goes offline during a game the game **freezes and resumes** when it
comes back (see [Restarts](#restarts-and-crashes)).

## Configuration reference

Set these in `.env` (or as environment variables).

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DISCORD_TOKEN` | **Yes** | | The bot token |
| `MONKE_DB` | No | `monke.db` in the project folder | Where the SQLite database lives |
| `MONKE_ARCHIVE_DAYS` | No | `7` | Days to keep chat and command logs of finished games before pruning. The zip archive itself stays in Discord |
| `MONKE_DEBUG` | No | off | Set to `1` to print every role, DM and decision to the console (same as `--debug`). **Spoils games** |
| `MONKE_OWNER_ID` | No | | Your Discord user ID. The bot DMs you a spoiler-safe one-liner when something unexpected happens |
| `MONKE_FLAVOUR` | No | `flavour.yaml` in the project folder | Path to a custom text file. See [Customising text](#customising-text) |

> `.env.example` mentions `MONKE_DB` twice. They are the same setting, so keep only one.

## Command-line options

`python -m monke [options]`

| Option | What it does |
|---|---|
| `--supervise` | Runs the bot as a child process and restarts it if it crashes (back-off from 1 to 60 seconds) |
| `--new-db` | Allow starting with a brand-new database in a server that is already set up. Use only if you know you lost the old one |
| `--force-takeover` | Start even if another copy seems to be running. Use after a hard crash that left a stale lock |
| `--debug` | Print every role, private message and decision to the console. **Spoils games** |
| `--debug-file PATH` | Also write debug output to a file |
| `--debug-chat` | Debug mode also prints what players type |

## Keeping it running

### Restarts and crashes

- The bot **refuses to run twice** against the same database. If you really need to start another, use
  `--force-takeover`.
- It **refuses to start with a brand-new, empty database in a server that is already set up** (for example if you launched it from the wrong folder). Use `--new-db` only if that is really what you want. The database path is always resolved relative to the project, never the folder you ran the command from.
- During downtime, game time is **frozen** and handed back. Nothing is lost and nothing is posted twice. Chat said while
  the bot was down is recovered.
- Failed Discord posts are retried in order.

### systemd example (Linux)

```ini
# /etc/systemd/system/monke.service
[Unit]
Description=Town of Monke bot
After=network-online.target

[Service]
WorkingDirectory=/opt/Town-of-Monke
ExecStart=/opt/Town-of-Monke/.venv/bin/python -m monke --supervise
Restart=on-failure
User=monke

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl enable --now monke`. Stop it with `sudo systemctl stop monke`. The bot shuts down gracefully.

Alternatives include `tmux` or `screen`, Docker, or a hosting panel that runs Python.

## Data, backups and logs

| What | Where |
|---|---|
| Database | `monke.db` in the project folder (or `MONKE_DB`) |
| Backups | `backups/` next to the database. A backup is taken at every start and before every migration. The latest 5 are kept |
| Logs | `logs/` in the project folder. Rotating files tagged with guild, game, phase and event number |

To restore: **stop the bot**, copy a backup over the database, and start it again. If the database fails its integrity
check, the bot refuses to start and says so.

Games are saved in the database, so a restart mid-game is safe. Saved games use schema version 2.

## Updating

```bash
git pull
pip install -r requirements.txt
python -m monke
```

The database is upgraded automatically, after a backup. A snapshot written by **newer** code than you are running is
set aside, never rewritten, so do not downgrade with a game in progress. Read the [CHANGELOG](../CHANGELOG.md) for any
upgrade notes (for example, new permissions).

## Customising text

Every message the bot writes (death messages, banners, role intros) lives in **`flavour.yaml`**. You can edit it to
change the style of your server without touching the code.

- Each key is one situation, with comments above it telling you where it is used and which `{placeholders}` it may use.
- A key can hold one string or a list of variants. The bot rotates through the list without repeating.
- Markdown works. Use `\n` for a new line. Escape double quotes inside strings as `\"`.
- After editing run **`monke reloadtext`** in `#monke-commands`. If something is wrong the bot tells you and **keeps the old
  text**.
- Validate offline with `python -m monke.text.check`.
- If a key is missing, the bot falls back to the shipped default, key by key.

Keep the placeholders. Removing one a message needs can break it.

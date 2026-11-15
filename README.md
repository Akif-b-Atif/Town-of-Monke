# Town of Monke Bot (v1.0.1)

A Town-of-Salem-style game run through Discord channel visibility, hidden numbered roles and DMs.
Implements the v1 design spec (5-20 players, 10 roles, Day/Noon/Afternoon/Night cycle, voting and trials,
night resolution, anonymous jail relay, graveyard, win conditions, restart recovery) plus the v1.0.1
quality-of-life release: player names in every message, phase banners with a reason line, admin changes,
and a **post-game archive** (a zip of every chat, action and night, posted after each game).

See [CHANGELOG.md](CHANGELOG.md) for what changed in each release.

## Architecture (the point of the design)

```
adapter/   Discord only: cogs, views, renderer (events -> messages, send_logged), planner (state -> permissions),
           relay (jail), chatlog (Discord chat events -> chat_log rows), strings (ALL player-visible text), textutil
service/   GameService (per-guild lock, timers, SQLite persistence, command log, recovery, fail-closed),
           ArchiveService (the end-of-game archive), ChatCapture (async queue for chat rows), store (SQLite)
engine/    PURE: (state, command, now) -> (new_state, events). Zero Discord imports.
archive/   PURE: builder (stored rows -> zip contents), zipper (size splitting), channels (registry of archived channels)
roles/     RoleDef data + handler per role, registered in a registry
sim/       Plays thousands of full games with fake players (and checks every phase change has a reason)
names.py   Pure player-name helpers (fmt_player), shared by the engine and the adapter
```

* `engine` and `archive` never import discord; the whole game and the whole archive are testable offline.
* Channel permissions come from one pure function, `adapter/planner.py`, diffed against what is applied.
  `plan(state, archiving=True)` is the ARCHIVING mode: every game channel hidden while the zip is built.
* Every input goes through `GameService._commit`: lock -> `engine.handle` -> persist state, events **and the command** (one
  transaction) -> sync permissions -> render -> re-arm timer. Rejected commands are logged too.
* **`DiscordPresenter.send_logged` is the only way the bot posts to Town Centre, Mafia Lair, Jail and Graveyard.** It never
  pings, splits text over 2,000 characters and embed descriptions over 4,096, caps embeds at 10 per message, and records the
  post. A test (`tests/test_no_direct_send.py`) fails if any other code calls `.send(` without an `# allow-send` marker.
* **All player-visible text lives in `adapter/strings.py`.** The engine writes data (events with reason codes), not prose,
  apart from a few role-result lines that use `names.fmt_player`.
* Stale timers and stale buttons are harmless: the engine ignores a mismatching `phase_id`, and prompts carry a freshness token.
* **Adding a role**: create a `RoleDef` + handler class and call `register()` (see `roles/town.py`). The night pipeline
  (`engine/night.py`) is the one place that needs new steps if the role introduces a new interaction; add matching
  `T(...)` trace calls there so the archive explains it.
* **Archiving another channel** (for example a future Medium seance): add one entry to `CHANNEL_KINDS` in
  `archive/channels.py`. No schema change and no change to the builder.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env            # then edit .env and paste your token (or: export DISCORD_TOKEN=...)
python -m monke                 # run from the project folder
```

Environment variables (all in `.env.example`):

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `DISCORD_TOKEN` | yes | none | Bot token from the Discord developer portal. Never commit `.env`. |
| `MONKE_DB` | no | `monke.db` | Path of the SQLite database. |
| `MONKE_ARCHIVE_DAYS` | no | `7` | Days to keep chat and command logs of archived games before they are pruned. |

Discord developer portal: enable the **Message Content** privileged intent. The bot also uses Guilds,
guild messages and DM messages (non-privileged).

Invite it with these permissions (scopes: `bot`, `applications.commands`): **Manage Roles, Manage Channels, Manage Messages,
View Channels, Send Messages, Embed Links, Attach Files, Read Message History, Use Slash Commands** (shown as "Use Application
Commands" in some versions of the portal). **Do not** give it Administrator. Its role must sit above the 20 slot roles and Monke Admin.

> **Upgrading from 1.0.0 or earlier:** add **Attach Files** to the bot's role (Server Settings > Roles). The archive upload needs
> it, and `monke setup` now checks for it. New database tables are created automatically on first start.

1. `monke setup` (needs Manage Server) creates the category, channels, `Monke Admin` and roles `1`-`20`. It is safe to run again.
2. Give the host the **Monke Admin** role. Admin commands work only in `#monke-commands`.
   **Everyone can read `#monke-commands`; only Monke Admin can write there.** The bot re-applies this at every start.
3. Players must allow DMs from server members (the start aborts and lists anyone who can't be DMed).

### Starting a game

```
monke start @p1 @p2 @p3 @p4 @p5
Jailor
Godfather
TI
TP
MK
day=5 noon=3 afternoon=2 night=2 defense=30 verdict=20 stalemate=3
```

Tokens: `Jailor`, `Godfather`, groups `TK TI TP TS MK MS NK NE`, random `RT` (any Town, never Jailor), `RM` (any Mafia,
never Godfather). Specific role names (e.g. `Sheriff`) are also accepted as a convenience. One role line per player.
`@mentions` can be pasted from a channel everyone can see, because `#monke-commands` only suggests people who can see it.

| Setting | Unit | Minimum | Default |
|---|---|---|---|
| `day` | minutes | 2 | 4 |
| `noon` | minutes | 2 | 3 |
| `afternoon` | minutes | 2 | 2 |
| `night` | minutes | 2 | 2 |
| `defense` | seconds | 15 | 30 |
| `verdict` | seconds | 15 | 20 |
| `stalemate` | cycles | 1 | 3 |

Day 1 and the Afternoon phase currently last **half of `day`**; the `afternoon` value is validated but not used for the
Afternoon length. `monke skip` moves a phase along without waiting.

### Commands

| Command | Who and where | What it does |
|---|---|---|
| `monke setup` | Manage Server | Create or repair the category, channels and roles. |
| `monke teardown [--force]` | Manage Server | Delete the channels and roles. Refuses while a game runs, or while an archive is unfinished unless `--force`. |
| `monke start ...` | Monke Admin, `#monke-commands` | Start a game (see above). Refused while the previous game is still being archived. |
| `monke status` | Monke Admin, `#monke-commands` | Phase, time left, players alive. Never shows roles. |
| `monke skip` | Monke Admin, `#monke-commands` | End the current phase early. Rejected within 3 seconds of another skip. |
| `monke abort` | Monke Admin, `#monke-commands` | End the game; the archive is built straight away. |
| `monke resume` | Monke Admin, `#monke-commands` | Resume a paused game. |
| `monke export [game_id]` | Monke Admin, `#monke-commands` | Retry a failed archive, or re-post the zip of a finished game. Refuses during a game. |
| `monke admins` | Monke Admin or Manage Server, any channel | List the current Monke Admin holders. |
| `/vote @p`, `/unvote`, `/resend` | players | Vote, withdraw a vote, re-send your night prompt. Night actions and verdicts are buttons and menus. |

Admin authority is the live **Monke Admin** role, checked on every command; nothing about who is admin is stored. Every admin
reply starts with the admin's name and never pings.

## What players see (v1.0.1)

* **Names:** each player's server display name is stored once at game start (control and zero-width characters removed,
  whitespace collapsed, cut to 20 characters, markdown and mentions escaped). The roster lists `#1 Maya`, and every vote, trial,
  verdict and death line reads `Maya (#3)`. Games saved before this release show `Player 3`.
* **Phase banner:** every phase change posts one message in Town Centre and pins it (the previous banner is unpinned):

  ```
  **Sam (#3)** has 4/4 votes and goes on trial.

  🛡️ **Defense, Day 2**
  Ends <relative time> (<clock time>) · 6 alive
  ```
  The first line is the *reason* for the change. Reason codes: `game_start`, `day1_timer`, `day_timer`, `trial_majority`,
  `defense_timer`, `verdict_guilty`, `verdict_pardon`, `three_innocent`, `noon_no_trial`, `noon_timeout_after_pardon`,
  `afternoon_timer`, `night_resolved`. Noon also shows how many votes a trial needs. After `monke skip` the line starts with
  "An admin (Name) ended the phase early."
* **Spoiler-safe admin channel:** while a game is live nothing with roles, seeds or error text is posted in `#monke-commands`.
  An internal error shows only: "Game X was paused because of an internal error. Use `monke resume` or `monke abort`."

## Post-game archive

Every game is recorded and, when it ends, packaged into a zip that is posted in `#monke-commands`. The four game channels are
then emptied so the next game starts clean. The game-start post tells players that "Game channels are logged for the post-game archive."

**What is recorded** (SQLite tables `chat_log`, `game_commands`, `game_events`, `archive_jobs`):

* Every message, edit and delete in Town Centre, Mafia Lair, Jail and Graveyard, plus the bot's own posts (embeds flattened to text).
* The Jailor's relayed jail messages (logged under the Jailor's slot). Other DMs are never logged.
* Every command, accepted or rejected, with slots instead of names.
* A structured trace of each night (jail, roleblocks, Mafia chain, alerts, visits, heals, attacks, investigations, deaths).
* Admin actions: `start`, `skip`, `abort`, `resume`, `export`.

**When it runs:** a normal ending waits 5 minutes for post-game chat; `monke abort` archives immediately.

**The sequence (fail-closed, nothing is deleted before a verified upload):**
1. Lock: all game channels are hidden and recording stops.
2. Build the zip(s) from the stored rows (deterministic: the same inputs give identical files).
3. Upload to `#monke-commands` with a summary embed, then re-fetch the message and verify every attachment.
4. Purge the four game channels (pins included) and verify they are empty, up to 3 tries each.
5. DM every participant a separator: "Anything below this line belongs to the next game."
6. Remove slot roles and finish; the job is marked `PURGED`.

Each step is saved in `archive_jobs`, so a restart resumes from the recorded step and never uploads the same zip twice.
If anything fails before a verified upload, nothing is deleted and the admin sees "Archive failed. Chats were NOT deleted. Run
`monke export` to retry." If only the purge fails, the archive is already safe and `monke export` finishes the cleanup.

**Zip contents** (`monke-game-<id>-<YYYYMMDD-HHMM>.zip`; several `partNofM` zips if it exceeds the server's file size limit):

```
README.txt             result, players (slot, name, role, fate), settings, seed, bot version
timeline.txt           everything merged in time order, tagged CHAT / ACTION / TRACE / PHASE / VOTE / VERDICT / DEATH / ADMIN
chat/                  town.txt, mafia.txt, graveyard.txt and one jail_night_NN.txt per night
abilities/             night_NN.txt (actions, trace, results delivered) and day_NN.txt (jail selections)
votes_and_trials.txt   every vote, trial and verdict
data/game.json         structured data for replay: settings, roles, commands, events
```
Edits show as `(edited)`; deleted messages show `[deleted]` with their original text. Everyone can read `#monke-commands`, so
the zip (which contains all roles) is visible to the whole server after the game.

**Other rules:** the next game cannot start until the previous archive is finished. A daily task deletes chat and command rows of
archived games older than `MONKE_ARCHIVE_DAYS` (snapshots and events are kept); `monke export` refuses games past that window.

## Tests and simulation

```bash
python -m pytest                       # 116 tests: night scenarios, phases, planner, service, names, banners, archive, chat logger
python -m monke.sim.cli --games 1000   # 1,000 random full games with invariants (every phase change must carry a reason)
```

## Status against the milestones

| M | State |
|---|---|
| M1-M3 engine, roles, night resolver, phases, voting, simulator | Done and tested |
| M4 persistence/service (lock, store, recovery, fail-closed) | Done and tested |
| v1.0.1 PR 1 foundations (strings, send_logged, names, banners, admin) | Done and tested; played live on a test server |
| v1.0.1 PR 2 archive | Done and tested offline; the zip upload was confirmed live. Channel purge, DM separators and restart-mid-archive still need a live check |
| v1.0.1 PR 3 smoothness (spec section 8) | **Not started** (the spec section was not available) |

### Live checks still worth doing
1. After a game ends: the four game channels are empty and unpinned, and players got the separator DM.
2. Restart the bot while an archive is half done: it resumes and does not post a second zip.
3. Restart the bot mid-night: prompts still work, the timer resumes.
4. Jail relay both directions: the Jail channel is purged at dawn, and the Jailor's lines appear in the archive.

## Decisions (spec section 15) and where I deviated or interpreted

* **D1 Veteran defense:** the spec table says None; Town of Salem gives Basic defense while on alert. I implemented
  **Basic on alert**. One switch: `VETERAN_ALERT_DEFENSE` in `roles/town.py`.
* **Slot to player mapping is public.** A roster is posted in Town Centre at start; otherwise nobody can vote for "Player 3".
  The role-to-player assignment is never printed. Slot roles have no colour/hoist/permissions.
* **Intents:** the spec lists Guilds + Message Content; receiving message events also needs `guild_messages` and `dm_messages`.
* **Dead Mafia** keep view-only on the Lair; other dead players get no Lair/Jail (D6). A **jailed Mafia** member can see but not talk in the Lair.
* **Jester haunt** stays available until used. **Mafia cannot target Mafia.**
* A **blocked SK attacks the blocker even if he chose no target**. An Escort targeting the prisoner just gets "target in jail".
* **Win check extras:** if only Neutral Evil roles remain alive the game is a draw. Two living Serial Killers do not win.
* **Stalemate** counts full cycles (Day lynch + Night) with zero deaths; Day 1 + Night 1 is cycle 1.
* **Post-game:** Town Centre stays open to participants for 5 minutes (`GameService.post_game_seconds`), then the archive runs.
* D2-D10 are implemented as written in the spec.

### v1.0.1 decisions and interpretations

* `fmt_player` lives in `monke/names.py` (re-exported from `adapter/textutil.py`) because the engine writes a few role-result
  lines that need names.
* The banner heading is `Night 2` for night phases and `Noon, Day 2` style for the others.
* Engine announcements now covered by the banner reason lines were removed ("Voting is open...", "Night N falls", "Player N was
  pardoned", "Day N dawns"). The dawn report (spec QOL-3) is not built yet, so the dawn reason line is just "Day N dawns."
* **Skip protection** rejects a skip within 3 seconds of the last skip. The spec also wants it measured from the phase start; the
  game state has no `phase_started_at`, so that check only activates if the field is added.
* `monke admins` can list too few people: the bot does not request the Server Members intent, so it only knows members it has seen.
* A stale timer advance (one that changes nothing) is not written to the command log.
* Admin-audience events (for example "a player left the server") are not posted while a game is live; they appear in the archive.

## Known limits
Out of v1 as specified: last wills, Mafioso promotion, dead players reading living chats, multiple simultaneous games, lobby UI,
web dashboard. Not built yet in 1.0.x: the dawn report, warnings before a phase ends, info commands, the graveyard welcome message
and the night recap (spec section 8). Day 1 / Afternoon length ignores the `afternoon` setting (see above).

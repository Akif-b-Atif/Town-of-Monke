# Town of Monke Bot

A Town-of-Salem-style game run through Discord channel visibility, hidden numbered roles and DMs.
Implements the design spec (5-20 players, 10 roles, Day/Noon/Afternoon/Night cycle, voting and trials,
night resolution, anonymous jail relay, graveyard, win conditions) and, from v1.1, the complete game: a lobby, role cards, wills
and death notes, a night recap and journal, dead-player experience, pacing and AFK handling, admin tools, a post-game recap, a
**post-game archive**, an editable text file for every message, a debug console, and crash-safe restarts.

See [CHANGELOG.md](CHANGELOG.md) for what changed in each release.

## Architecture (the point of the design)

```
adapter/   Discord only: registry + dispatch + handlers (every command, defined once), views, lobby, renderer
           (events -> messages, send_logged), planner (state -> permissions), relay (jail), chatlog, diagnose
service/   GameService (per-guild lock, timers, SQLite persistence, command log, ordered rendering with an outbox,
           recovery pipeline, time compensation), ArchiveService, ChatCapture, store (SQLite, WAL, backups, migrations),
           instance guard, outbox + ordered writer, lobby model
engine/    PURE: (state, command, now) -> (new_state, events). Zero Discord imports and no prose: text keys only.
compose.py PURE: events -> messages through the text system (shared by the bot, simulator, debug console and tests)
text/      the flavour loader, validator, shuffle bag and the registry of text keys (flavour.yaml is the file you edit)
describe.py PURE: the one place that words events, commands and night traces for the archive and the debug console
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
* **All player-visible text lives in `flavour.yaml`.** The engine writes data (events with a `text_key` and variables), never
  prose; only the composer turns them into words. `tests/test_text.py` scans the engine for stray sentences.
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
Commands" in some versions of the portal). Permissions integer: `2416045072` (`python check.py` prints it and a ready-made invite link). **Do not** give it Administrator. Its role must sit above the 20 slot roles and Monke Admin.

> **Upgrading from 1.0.0 or earlier:** add **Attach Files** to the bot's role (Server Settings > Roles). The archive upload needs
> it, and `monke setup` now checks for it. New database tables are created automatically on first start.

1. `monke setup` (needs Manage Server) creates the category, channels, `Monke Admin` and roles `1`-`20`. It is safe to run again.
2. Give the host the **Monke Admin** role. Admin commands work only in `#monke-commands`.
   **Everyone can read `#monke-commands`; only Monke Admin can write there.** The bot re-applies this at every start.
3. Players must allow DMs from server members (the start aborts and lists anyone who can't be DMed).

### Crashes, restarts and backups

The game survives the bot being killed, the computer sleeping or restarting, and Discord having a bad hour. Roles and
channels stay in place while the bot is offline (on purpose); when it returns it finds its way back.

- **Time is frozen while the bot is offline** and handed back in full: each running phase gets what it had left at the last
  heartbeat (at least 60 seconds). A paused game stays paused. The clock is also rechecked every 5 seconds, so a laptop that
  sleeps for hours does not leave a phase hanging.
- **Nothing is lost or posted twice.** Every message is recorded as it is sent; after a restart the missed ones are posted,
  once, in order. If Discord is down the bot keeps retrying (2, 4, 8 ... 60 s) and tells the admin after 10 failures.
- **Chat said while offline** is read back into the archive (marked "(recovered)"). Players who left are removed. If a game
  channel or slot role was deleted, the game is paused and the admin is told; the bot never recreates things in a live game.
- **Run it under supervision:** `python -m monke --supervise` restarts the bot after a crash (back-off 1 to 60 s; it gives up
  after 5 crashes in 5 minutes and says why). Alternatives: systemd (`Restart=on-failure`), Docker (`restart: unless-stopped`),
  pm2, or Windows Task Scheduler. The honest limit: if the computer itself is off, nothing runs. The game stays frozen in the
  database and resumes, time given back, at the next start.
- **One copy only.** A second copy refuses to start. After a hard crash use `--force-takeover` if it is wrongly blocked.
- **The database** is `monke.db` in the project folder whatever folder you start from (the full path is printed at start). It
  runs in WAL mode with full syncing, is integrity-checked at start, and is backed up with SQLite's backup API at every start
  and before every migration (`backups/`, the newest 5 are kept). If the file is missing but the server is already set up the
  bot refuses to run ("wrong folder or a lost database"); `--new-db` overrides that. To restore: stop the bot, copy a file
  from `backups/` over `monke.db`.
- **Logs** go to `logs/monke.log` (5 files of 5 MB) and the console, every line tagged with guild, game, phase and event
  number. The file can contain a game's seed after a crash, so treat it as a spoiler. Set `MONKE_OWNER_ID` to get a DM
  (at most one a minute) when something unexpected happens.
- **Stopping the bot cleanly** (Ctrl+C, SIGTERM, closing the console) waits for commands in flight, saves, and posts a notice
  in Town Centre. A crash skips that, and the next start behaves the same way.

### Debug mode

`python -m monke --debug` (or `MONKE_DEBUG=1`) prints everything the game does to the console, as the all-seeing admin:
the role table at game start, every phase change with its reason, every command and its outcome, the night trace step by
step, deaths, and every DM, post and prompt the bot sends with its recipient. It never goes to Discord, the archive or the
log file. **The console shows every role. Do not share it or stream it during a game.**

- `--debug-file PATH` also writes the same lines to a file.
- Human chat in Town Centre, Mafia Lair, Jail, the Graveyard and DMs shows only its length (`CHAT #04 Sam in mafia (23
  chars)`). Add `--debug-chat` to print the text too.
- One event per line, `HH:MM:SS <game> <phase> <TAG> text`, so it can be searched (`grep DEATH`). Colour only when the
  console is a terminal and `NO_COLOR` is unset.
- Watch a simulated game without Discord: `python -m monke.sim.cli --games 1 --seed 7 --players 8 --debug`.

### Starting a game: lobby, quick start, explicit list

`monke setup` also creates **Monke Lobby**: visible to everyone, read-only except for the bot. It holds lobby embeds,
game-over summaries and rematch buttons. Running `monke setup` again adds it to an existing server.

- **Lobby (default):** `monke start` (or `/start`) with no players opens a lobby embed. Anyone can **Join** (the bot sends a
  test DM and refuses, with instructions, if DMs are closed) or **Leave**. Any Monke Admin, checked live when they press,
  can **Start** (enabled at 5 to 20 players with a valid role list; otherwise it says what is wrong), **Edit settings**,
  **Edit role list** or **Cancel**. `monke lobby add @x`, `monke lobby remove @x` and `monke lobby cancel` manage it from
  Monke Commands. Lobbies survive restarts and close after `lobby_timeout` (30 minutes) of inactivity.
- **Quick start:** `monke start @p1 @p2 ... @pN` uses the default role list for N and shows a confirmation with the players,
  role list and settings. Add `-y` to skip the confirmation.
- **Explicit list:** the older form still works unchanged: mentions, then the role list on the following lines, then options
  such as `preset=blitz night=3m`.
- **Play again:** the game-over embed has a button that opens a lobby with the same players (still in the server) and settings.

### Role cards, wills, death notes and your journal

At the start of the game, and on `/role`, you get a role card: an alignment colour (with a text label), your ability in plain
language with a link to the wiki, Attack and Defense, your abilities with uses left, your goal and tips. Mafia cards list your
teammates. The card has **Edit will** and, for roles whose ability kills, **Edit death note** buttons (also `/will` and
`/deathnote`).

- **Will:** up to 600 characters, editable any time while you are alive. It is shown in the death announcement for every
  cause (lynching and execution included) unless it is blank.
- **Death note:** up to 300 characters for the Godfather, Mafioso, Serial Killer, Veteran, Jailor and Jester. It is attached
  to a victim only when your attack succeeds; for the Mafia it is the note of the player who performed the kill. It stays until
  you edit it.
- Text you write is cleaned when saved: mentions neutralised, invite links removed, at most 10 line breaks; markdown is allowed.
  `allow_wills`, `allow_deathnotes`, `will_max` and `note_max` are settings.
- **Journal:** `/journal` shows everything private you have learned. At dawn all the private results of the night (results of
  investigations, heal and block notices, execution and haunt notices) arrive as one **Night N recap** DM.
- **Dawn report:** one message in Town Centre: the dawn line, each death (cause, role reveal, will, note) in slot order, who
  remains, and a stalemate warning when a draw is one quiet cycle away.

### Dead players, pausing, pacing and AFK

- **Dead players** stay in the game: they read Town Centre, talk with the other dead in the Graveyard (their permissions
  change before the death is announced, so nobody can type in Town Centre in the gap), and dead Mafia keep read-only access
  to the Lair. The first death pins the Graveyard rules; each death gets a welcome that mentions the player. Keeping the
  living in the dark is on the honour system; the rules message says so. Dead players keep `/role`, `/journal`, `/alive`,
  `/votes`, `/rolelist`, `/timer` and `/help`. Only a Jester's ghost with a pending haunt can still act.
- **Skip ahead** (`early_day`, on by default): the banner has a button during Day 1, Day and Afternoon. When a strict majority
  of the living (floor(alive/2)+1) have pressed it, Day moves to Noon and Day 1 or Afternoon move to Night. The banner shows
  `n/needed`. Noon and trials can never be skipped this way; an admin `skip` still ends any phase.
- **Early night** (`early_night`, off by default): each night prompt gets a Confirm button; when every player holding a prompt
  has confirmed, the night resolves at once. It leaks nothing about who holds an ability, but it makes the night feel hurried.
- **Pause:** `monke pause` and `monke resume` freeze and unfreeze the game; the remaining time is stored, every game channel
  is read-only, the banner shows the pause, and a pause survives restarts and never receives time compensation.
- **AFK** (`afk_cycles`, default 3, 0 disables): a living player has an inactive day when, between one dusk and the next, they
  send no Town Centre message, cast no vote or verdict, press no button and (if they hold a prompt) submit no night action.
  Day 1 is not counted and any activity resets the counter. At 2 inactive days they get a DM warning and the admin is told; at
  `afk_cycles` they are removed at the next dawn (cause: abandoned, role revealed, will shown). `modkill` covers anything the
  heuristic misses.
- The banner is edited in place (new deadline after `extend` or a restart, pause, skip votes) so its countdown stays right.

### Admin tools, game over and the replay tool

- `monke extend [time]` adds time (default 2 minutes) to the current phase; the banner and timer follow.
- `monke modkill @player [reason]` (confirm) removes a player with cause *moderated*, role revealed by the normal rules. By day it
  applies at once; at night it is queued and announced at dawn.
- `monke replace @old @new` (confirm) swaps a player mid-game: the new person must be in the server, not already playing, and
  reachable by DM. Role state, journal, will and notes carry over; the new person gets the role card, a journal summary and
  the current banner, and any open prompts; the old person loses all game roles. The public announcement names the slot and
  both people and nothing else. The archive shows both names.
- `monke settings [key=value ...]` shows or sets the server defaults (`preset`, `day`, `night`, `afk_cycles` ...); `monke
  reloadtext` reloads `flavour.yaml`.
- `monke diagnose [fix:true]` checks permissions (Attach Files included), role hierarchy, channels, overwrites, the 20 slot
  roles, intents, the database, backups, `flavour.yaml`, quarantined games and unfinished archives, a second running copy,
  and whether debug mode is on, with a one-line fix for each failure. `fix:true` recreates missing structures and reapplies
  planned permissions, and never changes a running game's roles. The report is spoiler-safe.
- **Game over:** the game-over embed lists the winning faction (and the Jester if they won) and every player's name, final role
  and fate, in Town Centre and in Monke Lobby (with a Play again button). A day-by-day recap built from the event log (deaths
  and causes, trials with counts and voters, jail and execution moments, what each investigation returned) is posted in Town
  Centre during the post-game window, and a short version in the Lobby. The archive zip is unchanged (`monke export`).
- **Replay tool:** `python -m monke.sim.replay data/game.json` (the file inside an archive zip) re-runs the seed and the command
  log through the engine and checks that the events are identical, printing the first divergence. Reproduce a reported game
  with it before fixing anything. Games archived before v1.1 have no start record and cannot be replayed.

### Commands

Every command is defined once in a registry (`monke/adapter/handlers.py`), which generates the slash commands, the
`monke ...` text forms, `/help` and the permission checks. Slash commands are primary; the `monke ...` prefix exists for
admin and server commands only.

**Players** (slash, answered privately; usable anywhere in the server by anyone in the game, dead players included):
`/vote [player]` (autocompletes living players, or use the vote panel posted at Noon), `/unvote`, `/votes`, `/alive`,
`/rolelist [count]`, `/timer`, `/role`, `/help` (shows only what works for you right now), `/resend`. Someone who is not in
the game is told so and nothing else.

**Admins** (Monke Admin role, checked live; only in Monke Commands; slash or `monke ...`): `start`, `status`, `skip`,
`abort`, `pause`, `resume`, `extend`, `modkill`, `replace`, `settings`, `diagnose`, `lobby`, `export [game_id]`, `admins`, `reloadtext`. `skip`, `abort` and `teardown` ask for confirmation with
Confirm / Cancel buttons that any Monke Admin may press and that expire after 60 seconds.
**Server managers:** `setup`, `teardown [--force]`.

During a phase the bot posts "Only N remain." when a quarter of it is left (at least 30 s before the end, at most 15 min;
phases under a minute get none), and at Night nudges by DM anyone who has a prompt but has not chosen yet. Old prompts are
edited to "Expired: ..." when their phase ends.

### Editing the text (`flavour.yaml`)

Everything players read lives in **`flavour.yaml`** in the project folder: banners, death and dawn lines, vote messages,
role descriptions, errors, admin replies. The engine contains no prose. A value is one text or a list of variants; the bot
draws variants from a shuffle bag so a line does not repeat until the others have been used. Each key has a comment saying
when it fires and which `{placeholders}` it may use.

- Edit the file, then run `reloadtext` in Monke Commands (or restart the bot). An invalid file is rejected, the previous
  text stays active and the problems are listed with their key and line. A key missing from your file falls back to the
  shipped default (`monke/data/flavour_default.yaml`; do not edit that copy).
- Keys that fire several times per game should have at least 3 variants; the checker warns when they have fewer.
- `python -m monke.text.check` validates the file from the command line.

### Role list tokens and settings

Tokens (case-insensitive, separated by spaces, commas or new lines): `Jailor`, `Godfather`, groups `TK TI TP TS MK NK NE`, random
`RT` (any Town, never Jailor), `RM` (any Mafia, never Godfather), `RN` (any Neutral) and `Any` (anything except Jailor and
Godfather). Specific role names (e.g. `Sheriff`) work too. `/rolelist 15` shows the default list for 15 players.

Presets (`preset=blitz|normal|relaxed|async`) and options combine in any order, e.g. `monke start preset=blitz night=3m`.
Durations are `90s`, `2m`, `1h`; **a bare number means minutes**. Minimums: 2 minutes for Day, Noon, Afternoon and Night, 15 seconds
for Defense and Verdict.

| Preset | Day | Noon | Afternoon | Night | Defense | Verdict |
|---|---|---|---|---|---|---|
| blitz | 2m | 2m | 2m | 2m | 15s | 15s |
| normal (default) | 4m | 3m | 2m | 2m | 30s | 20s |
| relaxed | 8m | 4m | 4m | 4m | 45s | 30s |
| async | 2h | 1h | 1h | 2h | 10m | 10m |

Day 1 is half of Day. Other options: `stalemate` (cycles without a death before a draw, 0 disables), `early_day` (on),
`early_night` (off), `afk_cycles` (3, 0 disables), `allow_wills`, `allow_deathnotes` (on), `will_max` (600), `note_max` (300),
`post_game_chat` (5m), `lobby_timeout` (30m), `downtime_compensation` (on). Settings resolve in three layers, once at game start:
built-in defaults, then server defaults (`monke settings`), then per-game options; the result is frozen in the game.

Admin authority is the live **Monke Admin** role, checked on every command; nothing about who is admin is stored. Every admin reply
starts with the admin's name and never pings.

## What players see

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
  `afternoon_timer`, `night_resolved`, `skip_early`, `trial_cancelled`. Noon also shows how many votes a trial needs. After `monke skip` the line starts with
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
python -m pytest                        # the whole suite: engine, text, composer, commands, lobby, cards, pacing,
                                        # reliability (the crash matrix F1 to F15 and a chaos test), archive, leaks
python -m monke.sim.cli --games 1000    # 1,000 random full games; every event is rendered through the real text system
python -m monke.sim.cli --games 1 --seed 7 --players 8 --debug     # watch one game
python -m monke.sim.replay data/game.json                         # reproduce a game from its archive
python -m monke.text.check                                         # validate flavour.yaml
```

## Live checks (a test server)

Everything above is tested offline against fakes; these need real Discord accounts and are the v1.1 sign-off:

1. A 5-player quick-start game, and a 10+ player lobby game, played to the end with real accounts.
2. Kill the bot (`kill -9`, or close the console) in Day, Noon, Defense, Verdict, Afternoon and Night with prompts pending, and
   during the archive. Each time the game continues with the time given back and no duplicate posts.
3. A debug-mode run (`--debug`) read from start to finish.
4. Read Monke Commands, Monke Lobby, every public post and every error during a full game as a non-player: no role, seed or
   private result (the automated version is `tests/test_leaks.py`).
5. After a game ends: the game channels are empty, players got the separator DM, the archive zip is in Monke Commands, and
   the game-over embed and Play again button are in Monke Lobby.

## Decisions (spec section 17) and interpretations

* **D1 Veteran defense:** the spec table says None; Town of Salem gives Basic defense while on alert. Implemented as **Basic on
  alert**. One switch: `VETERAN_ALERT_DEFENSE` in `roles/town.py`.
* **D11-D25 as written:** dead Mafia keep read-only Lair access; `early_day` on and `early_night` off; `RN` and `Any` tokens;
  default lists cap Neutrals at 2 and may repeat roles; Town stays strictly larger than Mafia plus Neutral; wills 600 and death
  notes 300 characters; AFK warning at 2 and removal at 3; Monke Lobby visible to everyone and read-only; wiki links point at the
  Town of Salem fandom page of each role (edit them per role in `flavour.yaml`; please verify the pattern); slash commands are
  primary and the `monke` prefix covers admin and server commands; time is frozen while the bot is offline and handed back in
  full (the alternative is to cap it); a built-in `--supervise` restarter; `post_game_chat` 5 minutes; debug mode never prints
  chat text without `--debug-chat`; any Monke Admin may press lobby and confirmation buttons.
* **Interpretations:** a bare number in a duration means minutes for every duration, defense and verdict included (write `30s`).
  AFK is evaluated at dusk (the start of Night): activity counts from one dusk to the next, so a night action counts toward the
  following day. Confirmation prompts for admin commands are posted in Monke Commands rather than ephemerally, because any admin
  may press them. A day prompt (the Jailor's) says "Choose before night falls" because its deadline is not known in advance. A
  recap or journal line may be worded differently from the original DM (the facts are the same) because the text system draws
  variants. The single instance guard treats a copy on the same machine whose process is gone as not running, so a supervisor can
  restart a crashed bot at once.
* **Text keys with no rule behind them yet** (kept in `flavour.yaml`, harmless): `attack.survived`, `vet.alert_on`,
  `dawn.deaths_intro`, `death.no_will`, `lobby.created`, `admin.export.ready`, `admin.restarted`, `ui.role.unknown`. The spec lists
  no rule that uses them (for instance, wills are shown only when written, so there is no "left no will" line).

## Known limits
Out of scope until 2.0: new roles, new win conditions, new phases, multiple simultaneous games, a web dashboard. Duplicate Sheriffs,
Doctors and so on are expected with the current ten-role roster. If the computer itself is off nothing runs; the game resumes,
time given back, at the next start.

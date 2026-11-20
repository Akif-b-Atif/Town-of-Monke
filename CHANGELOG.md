# Changelog

## [1.1.0] - 2026-11-20

The complete game with the original ten roles: everything except new roles. The bug-fix release 1.1.1 is next.

### Added
- **Lobby, quick start, rematch.** `monke setup` creates Monke Lobby (visible to all, read-only). `monke start` opens a lobby embed
  with Join, Leave, and (for any Monke Admin, checked live) Start, Edit settings, Edit role list and Cancel; `monke start @p1 ...
  @pN` uses the default role list for N with a confirmation (`-y` skips it); the explicit role-list form is unchanged. The
  game-over embed has a Play again button.
- **Defaults and presets.** Default role lists for 5 to 20 players (the 15-player list is the classic one), presets `blitz`,
  `normal`, `relaxed` and `async`, `key=value` options with durations like `90s`, `2m`, `1h` and did-you-mean errors, settings
  layers (built-in, server defaults via `monke settings`, per game), new tokens `RN` and `Any`.
- **Role cards, wills, death notes, journal.** A role card at start and on `/role` with Edit will and Edit death note buttons;
  wills (600 characters) shown for every cause of death; death notes (300) for killing roles, attached only when the attack
  succeeds; `/journal`; one "Night N recap" DM at dawn; the full dawn report.
- **Dead players and pacing.** The permission matrix is tested for every state; Graveyard welcome and rules; a vote panel at
  Noon with a live tally; Skip ahead (`early_day`) and an optional Confirm to end the night early (`early_night`); `pause`;
  warnings at 25% of a phase and nudges at night; prompts expire when their phase ends; AFK handling (`afk_cycles`).
- **Commands.** One registry generates slash commands, `monke ...` forms, `/help` and permission checks. New info commands
  `/alive /votes /rolelist /timer /role /journal /help`, `/vote` autocomplete, Confirm / Cancel buttons for destructive admin
  commands, and the admin commands `pause`, `extend`, `modkill`, `replace`, `settings`, `diagnose`, `lobby`, `reloadtext`.
- **Post-game.** The game-over embed with every player's role and fate in Town Centre and Monke Lobby, and a recap built from the
  event log. `python -m monke.sim.replay data/game.json` re-runs any archived game and prints the first divergence.
- **Text system.** All player-visible text is in `flavour.yaml`: validated with key and line, variants drawn from a shuffle bag,
  hot-reloaded with `monke reloadtext`, falling back per key to a shipped default. `python -m monke.text.check` validates it.
- **Debug console.** `python -m monke --debug` (also `--debug-file`, `--debug-chat`) prints every role, decision, DM and post; human
  chat shows only its length. `python -m monke.sim.cli --games 1 --seed N --debug` does the same for a simulated game.
- **Reliability.** Crash-safe restarts: time is frozen while the bot is offline and handed back, nothing is lost or posted twice
  (an outbox and ordered replay), failed posts are retried, chat said while offline is recovered, the bot refuses a second copy
  or a wrong database folder, and `--supervise` restarts it after a crash. WAL, integrity check and backups at every start and
  before every migration; rotating logs tagged with guild, game, phase and event number; graceful shutdown.

### Changed
- Saved games use schema version 2. A v1.0.1 game in progress loads, is upgraded and continues; a snapshot written by newer code is
  set aside, never rewritten.
- Afternoon uses its own `afternoon` setting; a bare number in a duration means minutes; `stalemate=0` disables the draw.
- The skip guard now measures from the start of the phase (`phase_started_at` is stored).
- A paused game is read-only in every channel, including the Graveyard and a prisoner's Jail.
- The pinned banner is remembered across restarts. Setup and teardown replies no longer ping.
- The invite permissions integer (2416045072, with Attach Files) is in the README; the version lives only in `monke/__init__.py`.
- `adapter/strings.py` is gone; the three command cogs are replaced by the registry.

### Fixed
- Failed Discord posts used to be lost for good; they are now retried in order.
- Restart gaps: orphaned STARTING games, overdue timers firing at once, one bad snapshot blocking recovery, a relative database
  path, no single-instance guard, and a chat gap while the bot was down.

## [1.0.1] - 2026-11-15

Quality-of-life release: clearer messages, safer admin tools and a post-game archive.

### Added
- **Post-game archive.** Chats, edits, deletes, bot posts, every command (accepted and rejected), a per-night trace and admin
  actions are recorded. After a game a zip (`README.txt`, `timeline.txt`, `chat/`, `abilities/`, `votes_and_trials.txt`,
  `data/game.json`) is posted in `#monke-commands`, the game channels are emptied and players get a DM separator.
- Fail-closed end sequence with saved progress: nothing is deleted before the upload is verified; a restart resumes without
  uploading twice. Zips over the server's file size limit are split.
- `monke export [game_id]`: retry a failed archive or re-post an old one (refuses during a game).
- `monke admins`: list current Monke Admin holders (Monke Admin or Manage Server, any channel).
- `monke teardown --force`; plain `monke teardown` now refuses while an archive is unfinished.
- Player names stored at game start and shown as `Maya (#3)` in the roster, votes, trials, verdicts, deaths and prompts.
- Phase banners with a reason line, heading, deadline and alive count; the newest banner is pinned.
- `send_logged`: single entry point for posts to the four game channels (no pings, long text and embeds split, max 10 embeds).
- `MONKE_ARCHIVE_DAYS` setting and a daily prune of old chat and command rows.
- Game-start post notes that game channels are logged.
- `adapter/strings.py` (all player-visible text) and `adapter/textutil.py` (`rel`, `clock`, `split_text`, `sanitize_name`).
- New SQLite tables `chat_log`, `game_commands`, `archive_jobs` (created automatically).
- Tests: 116 total (was 67). The simulator now fails if any phase change has no reason.

### Changed
- `#monke-commands` is readable by everyone; only Monke Admin can write there. Applied at `monke setup` and at every start.
- Every admin reply starts with the admin's name and never pings.
- `monke skip` is rejected within 3 seconds of another skip; a second `monke start` is rejected while a game is starting or running.
- A new game cannot start until the previous game's archive is finished.
- The internal-error notice no longer shows the seed or error text.
- Admin-only events are no longer posted while a game is live (they go to the archive).
- The bot now needs the **Attach Files** permission (`monke setup` checks it).
- Package version is 1.0.1 (`monke/__init__.py` and `pyproject.toml`).
- `check.py` now builds the invite URL from named permissions and includes **Attach Files**.

### Removed
- Engine announcements now covered by the phase banner: "Voting is open...", "Night N falls.", "Player N was pardoned.",
  "The town has pardoned three people today...", "Day N dawns."

### Upgrade notes
1. Give the bot's role **Attach Files**.
2. Run the new code; new tables are created on first start. Games saved before the upgrade show `Player N` instead of names.

### Not included
- Spec section 8 (PR 3: dawn report, warnings, info commands, graveyard welcome, night recap): not built yet.

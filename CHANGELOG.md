# Changelog

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

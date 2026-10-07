# Town of Monke Bot (v0.1 MVP)

A Town-of-Salem-style game run through Discord channel visibility, hidden numbered roles and DMs.
Implements the v1 design spec: 5-20 players, 10 roles, Day/Noon/Afternoon/Night cycle, voting and trials,
night resolution, anonymous jail relay, graveyard, win conditions, restart recovery.

## Architecture (the point of the design)

```
adapter/   Discord only: cogs, views, renderer (events -> messages), planner (state -> permissions), relay
service/   GameService: per-guild lock, timers, SQLite persistence, recovery, fail-closed
engine/    PURE: (state, command, now) -> (new_state, events). Zero Discord imports.
roles/     RoleDef data + handler per role, registered in a registry
sim/       Plays thousands of full games with fake players
```

* `engine` never imports discord; the whole game is testable and simulatable offline.
* Channel permissions come from one pure function, `adapter/planner.py`, diffed against what is applied.
* Every input goes through `GameService._commit`: lock -> `engine.handle` -> persist (one transaction) -> sync -> render -> re-arm timer.
* Stale timers and stale buttons are harmless: the engine ignores a mismatching `phase_id`, and prompts carry a freshness token.
* **Adding a role**: create a `RoleDef` + handler class and call `register()` (see `roles/town.py`). The night pipeline (`engine/night.py`) is the one place that needs new steps if the role introduces a new interaction.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env            # then edit .env and paste your token (or: export DISCORD_TOKEN=...)
python -m monke                 # run from the monke-bot folder; optional: MONKE_DB=path/to/monke.db in .env
```

Discord developer portal: enable the **Message Content** privileged intent. The bot also uses Guilds,
guild messages and DM messages (non-privileged). Invite it with Manage Roles, Manage Channels, Manage Messages,
View Channels, Send Messages, Embed Links, Read Message History, Use Application Commands (scopes: `bot`,
`applications.commands`). **Do not** give it Administrator. Its role must sit above the 20 slot roles and Monke Admin.

1. `monke setup` (needs Manage Server) creates the category, channels, `Monke Admin` and roles `1`-`20`.
2. Give the host the **Monke Admin** role. All admin commands work only in `#monke-commands`.
3. Players must allow DMs from server members (the start aborts and lists anyone who can't be DMed).

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
never Godfather). Specific role names (e.g. `Sheriff`) are also accepted as a convenience. Players: `/vote @p`,
`/unvote`, `/resend`; night actions and verdicts are buttons/menus. Admin: `monke status | skip | abort | resume | teardown`.

## Tests and simulation

```bash
python -m pytest                       # ~70 tests: night scenarios, phases, planner, service, 200-game fuzz
python -m monke.sim.cli --games 1000   # milestone M3: 1,000 random full games with invariants
```

## Status against the milestones

| M | State |
|---|---|
| M1-M3 engine, roles, night resolver, phases, voting, simulator | Done and tested |
| M4 persistence/service (lock, store, recovery, fail-closed) | Done and tested with a fake presenter |
| M5-M8 Discord layer | **Written but NOT yet run against a live Discord server.** Do M0-style spikes first (see below) |

### First live checks (the spec's M0 spikes)
1. `monke setup` creates 20 roles and the channels; the hierarchy check passes.
2. Start a 5-player game with alt accounts. Check each channel's visibility per phase against the matrix.
3. Restart the bot mid-night: prompts still work, timer resumes.
4. Jail relay both directions; the Jail channel is purged at dawn.

## Decisions (spec section 15) and where I deviated or interpreted

* **D1 Veteran defense:** the spec table says None; Town of Salem gives Basic defense while on alert. I implemented
  **Basic on alert** because the spec asked to verify this. One switch: `VETERAN_ALERT_DEFENSE` in `roles/town.py`.
* **Slot to player mapping is public.** A roster (`3 = @name`) is posted in Town Centre at start; otherwise nobody can
  vote for "Player 3". The role-to-player assignment is never printed. Slot roles have no colour/hoist/permissions.
* **Intents:** the spec lists Guilds + Message Content; receiving message events also needs `guild_messages` and `dm_messages`.
* **Dead Mafia** keep view-only on the Lair (matrix); other dead players get no Lair/Jail (D6). A **jailed Mafia** member can see but not talk in the Lair.
* **Jester haunt** stays available until used (not only the first night after the lynch).
* **Mafia cannot target Mafia** (Godfather and Mafioso target menus exclude teammates).
* A **blocked SK attacks the blocker even if he chose no target**. An Escort targeting the prisoner just gets "target in jail".
* **Win check extras:** if only Neutral Evil roles remain alive the game is a draw. Two living Serial Killers do not win (continues to stalemate).
* **Stalemate** counts full cycles (Day lynch + Night) with zero deaths; Day 1 + Night 1 is cycle 1.
* **Post-game:** Town Centre stays open to participants for 5 minutes (`GameService.post_game_seconds`), then roles are removed and channels hidden/purged.
* D2-D10 are implemented as written in the spec.

## Known limits (out of v1, as specified)
Last wills, Mafioso promotion, dead players reading living chats, multiple simultaneous games, lobby UI, early phase ending, web dashboard.

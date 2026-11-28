# Command reference

Every command in Town of Monke, who can use it, and where.

## How commands work

- **Slash commands** (`/vote`, `/start`, ...) work for everything. Start typing `/` and pick from the list.
- **`monke` text commands** (`monke start`, `monke skip`, ...) also work for **admin and server** commands. Type them as a
  normal message. They are not case-sensitive.
- **Player commands** are slash only. Replies are **private** (only you see them).
- **Admin commands** (everything under [Admin commands](#admin-commands)) work **only in `#monke-commands`** and only for
  members with the **Monke Admin** role. If a non-admin types a `monke` command, or an admin types one in the wrong
  channel, the bot **stays silent** to avoid spam. Slash versions answer with an error that only you see.
- Dangerous commands ask you to press **Confirm** or **Cancel**. Any Monke Admin can press them, and they expire after
  60 seconds.
- Use **`/help`** to see only the commands that work for you right now.

### Who is who

| Who | How you become one |
|---|---|
| **Player** | You are in the running game |
| **Monke Admin** | Holds the **Monke Admin** role (check with `monke admins`) |
| **Server manager** | Has Discord's **Manage Server** permission |

## Player commands

| Command | When | What it does |
|---|---|---|
| `/vote [player]` | Noon, alive | Vote to put a player on trial. With no player, shows the tally |
| `/unvote` | Noon, alive | Withdraw your vote |
| `/votes` | Any time | Show who has voted for whom (only open at Noon) |
| `/alive` | Any time | Show who is alive and who has died, with roles and causes |
| `/rolelist [count]` | Any time | This game's role list, or the default role list for `count` players |
| `/timer` | Any time | The current phase and when it ends |
| `/role` | Any time | Re-show your role card |
| `/journal` | Any time | Everything you have privately learned, oldest first |
| `/will` | Alive | Open a window to write your will |
| `/deathnote` | Alive | Open a window to write your death note |
| `/resend` | Day or Night | Resend your current action prompt to your DMs |
| `/help` | Any time | List the commands that work for you now |

`[player]` accepts a name, a slot number (`3` or `#3`), or an @mention, and autocompletes with living players
(excluding you and anyone already pardoned today).

### Things that are buttons, not commands

| Where | Button | Who | What it does |
|---|---|---|---|
| Lobby | Join, Leave | Everyone | Sign up / sign off |
| Lobby | Start, Edit settings, Edit role list, Cancel | Monke Admin | Control the lobby |
| Role card | Edit will, Edit death note | You | Same as `/will` and `/deathnote` |
| Noon vote panel | Player menu, Unvote | Alive players | Same as `/vote` and `/unvote` |
| Verdict message | Guilty, Innocent, Abstain | Alive players except the accused | Your verdict |
| Day banner | Skip ahead | Alive players | Vote to end the phase early |
| Night DM | Player menu or toggle (Alert, Execute) | Roles with abilities | Your night action |
| Night DM | Confirm | Players with prompts | Ends the night early (if `early_night` is on) |
| Game over | Play again | Everyone | Opens a lobby with the same players and settings |
| Admin confirmations | Confirm, Cancel | Monke Admin | Approve or cancel a dangerous command |

## Admin commands

Use in **`#monke-commands`**. Both the slash form and `monke <command>` work.

### Starting games

| Command | What it does |
|---|---|
| `monke start` | Open a **lobby** in #monke-lobby. You can add settings: `monke start preset=blitz night=3m` |
| `monke start @p1 @p2 ... @pN` | **Quick start** with the default role list for N players. Asks you to confirm. Add `-y` to skip the confirmation |
| `monke start @p1 ... @pN` followed by role names on following lines | Start with an **explicit role list** (no confirmation) |
| `/start players:... roles:... options:...` | The same, as a slash command |
| `monke lobby add @player` | Add a player to the open lobby (skips the DM test, but Start re-checks) |
| `monke lobby remove @player` | Remove a player from the open lobby |
| `monke lobby cancel` | Close the open lobby |

Example of an explicit start:

```
monke start @Ada @Ben @Cleo @Dev @Eli
Jailor
Godfather
TI
TP
RN
day=5 noon=3 night=2
```

Role names can be separated by spaces, commas, semicolons or new lines. Options (`key=value`) can be anywhere. See
[Role lists and settings](role-lists-and-settings.md).

Starting is refused if a game is already starting or running, or the **previous game's archive is not finished**.
A start is aborted, with a list, if any player cannot receive DMs.

### Running a game

| Command | What it does |
|---|---|
| `monke status` | Phase, timer and how many are alive. **Never shows roles** |
| `monke pause` | Freeze the game and its clock. Every channel becomes read-only |
| `monke resume` | Unfreeze it |
| `monke extend [time]` | Add time to the current phase (default 2 minutes). Examples: `monke extend 90s`, `monke extend 5m` |
| `monke skip` | End the current phase now (asks to confirm). Rejected if within 3 seconds of a phase change or another skip |
| `monke modkill @player [reason]` | Remove a player from the game (asks to confirm). Cause of death: "an admin". Takes effect at dawn if used at night |
| `monke replace @old @new` | Swap one player for another mid-game (asks to confirm). The new player must be in the server, not already playing, and have open DMs |
| `monke abort` | Cancel the running game (asks to confirm) |

### Housekeeping

| Command | What it does |
|---|---|
| `monke settings` | Show the server's default settings |
| `monke settings key=value ...` | Change the server defaults. Example: `monke settings preset=relaxed early_night=on` |
| `monke diagnose` | Check permissions, role order, channels and the database |
| `monke diagnose --fix` | Same, and repair what can safely be repaired. Never touches the roles of a running game |
| `monke export [game_id]` | Rebuild and post the archive zip, or retry a failed one. Not allowed during a game |
| `monke admins` | List current Monke Admins. Works in **any channel**, for Monke Admins and server managers |
| `monke reloadtext` | Reload `flavour.yaml` after editing it |

## Server commands

For members with **Manage Server**. Work in any channel.

| Command | What it does |
|---|---|
| `monke setup` | Create (or repair) the Town of Monke category, channels, **Monke Admin** role and slot roles `1` to `20`. Safe to run again |
| `monke teardown` | Delete all of the above (asks to confirm). Refused during a game, or while an archive is unfinished |
| `monke teardown --force` | As above even if an archive is unfinished (you may lose it) |

## Flag syntax for `monke` commands

Boolean flags can be written as `--fix` or `fix:true`. Examples: `monke diagnose --fix`, `monke teardown --force`.

## What the bot says when it cannot do something

| Message | Meaning and fix |
|---|---|
| "Only the Monke Admin can use that command." | You lack the Monke Admin role |
| "Admin commands only work in the Monke Commands channel." | Use `#monke-commands` |
| "This server is not set up yet." | A server manager must run `monke setup` |
| "You can only vote during Noon." | Voting is closed. See `/timer` |
| "You cannot do that right now. It works during ..." | Wrong phase for that ability |
| "Start aborted. These players must open their DMs ..." | Those players need to allow DMs |

For more, see [Troubleshooting](troubleshooting.md).

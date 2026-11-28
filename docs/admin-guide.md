# Admin guide

For the people who **set up the bot in a server** and **host games**. You do not need to know how the bot works
internally. This guide covers one-time setup, hosting a game from start to finish, handling problems mid-game, and
cleanup.

If you are **running the bot itself** (installing it, creating the Discord application, keeping it online), read
[Hosting the bot](hosting.md) first, then come back here.

## Contents

- [Two kinds of admin](#two-kinds-of-admin)
- [One-time server setup](#one-time-server-setup)
- [Hosting a game](#hosting-a-game)
- [During the game](#during-the-game)
- [Moderation tools](#moderation-tools)
- [After the game](#after-the-game)
- [Good habits](#good-habits)
- [Removing everything](#removing-everything)

## Two kinds of admin

| Role | Can do | Gets it by |
|---|---|---|
| **Server manager** | `monke setup`, `monke teardown`, `monke admins` | Discord **Manage Server** permission |
| **Monke Admin** | Everything else: start, pause, skip, settings, ... | The **Monke Admin** role the bot creates |

Anyone can be both. Being a Monke Admin does **not** let you see secret channels (Mafia Lair, Jail), and `monke status`
never reveals roles. That is deliberate, so that the host can play.

> **Warning:** people with Discord's **Administrator** permission (and the server owner) can see every channel
> regardless of the bot. If they play, they could read the Mafia Lair. They should only host, or only play and agree not
> to look.

## One-time server setup

### 1. Invite the bot

Use the invite link the bot's owner generated (see [Hosting the bot](hosting.md#4-invite-the-bot)). It needs these
permissions, and **not** Administrator:

Manage Roles, Manage Channels, Manage Messages, View Channels, Send Messages, Embed Links, Attach Files, Read Message
History, Use Application Commands.

### 2. Put the bot's role above the game roles

Discord only lets a bot assign roles **below** its own highest role. In **Server Settings > Roles**, drag the bot's role
**above** the `Monke Admin` and `1` to `20` roles (after step 3 creates them, or run setup once and then fix the order).

### 3. Run `monke setup`

As a server manager, type in any channel:

```
monke setup
```

(or `/setup`). The bot creates:

| Thing | Name | Purpose |
|---|---|---|
| Category | **Town of Monke** | Holds everything below (hidden by default) |
| Channel | **#monke-commands** | Admin commands. Everyone can read. Only Monke Admins write |
| Channel | **#monke-lobby** | Lobbies, visible to everyone and read-only |
| Channels | **#town-centre**, **#mafia-lair**, **#jail**, **#graveyard** | Game channels, hidden until a game needs them |
| Role | **Monke Admin** | Lets people host |
| Roles | **1** to **20** | One per player slot, used to grant channel access. They have no permissions or colour |

`monke setup` is **safe to run again**. It repairs missing pieces. It will tell you if a permission is missing or if the
role order is wrong.

### 4. Give your hosts the Monke Admin role

Assign **Monke Admin** to whoever will host. Check with `monke admins`.

### 5. Check everything

Run this in `#monke-commands`:

```
monke diagnose
```

It checks permissions, role order, channels, role settings and the database, and tells you how to fix each failure. Add
`--fix` to let it repair safe problems.

### 6. Tell your players

Send players the [Player guide](player-guide.md). The one thing to insist on: **allow DMs from server members**.

## Hosting a game

### Option A: use the lobby (recommended)

1. In `#monke-commands`, type `monke start`. Optionally add settings: `monke start preset=relaxed`.
2. A lobby appears in **#monke-lobby**. Share the link or ask people to press **Join**.
3. Wait for **5 to 20** players. Players are DM-tested when they join.
4. Optional: press **Edit settings** or **Edit role list**.
5. Press **Start**. (Start, Edit settings, Edit role list and Cancel only work for Monke Admins.)

The lobby expires after 30 minutes of inactivity. If you open a new lobby, the old one is cancelled.
`monke lobby add/remove/cancel` manage it from `#monke-commands`.

### Option B: quick start

If everyone is here already:

```
monke start @Ada @Ben @Cleo @Dev @Eli
```

The bot shows the default roles and settings and asks you to press **Confirm**. Add `-y` to skip the confirmation.

### Option C: full control

Give your own role list and settings. See the example in the [command reference](commands.md#starting-games) and the
syntax in [Role lists and settings](role-lists-and-settings.md).

### What happens at the start

1. The bot checks everyone can be DMed. If not, it **aborts** and lists the players who need to open their DMs.
2. Each player gets a **role card** by DM.
3. The roster and role list are posted in **#town-centre**.
4. Day 1 begins.

### Choosing a good game

| Players | Suggested |
|---|---|
| 5 to 7 | `preset=blitz` or `normal`. Small games are swingy |
| 8 to 12 | `normal` |
| 13 to 20 | `normal` or `relaxed`. More discussion needed |
| Spread over days | `preset=async` and expect the game to take days |

The [default role lists](role-lists-and-settings.md#default-role-lists) are balanced, so start there.

## During the game

The bot runs the game on its own timers. Your job is mostly to watch.

- `monke status`: current phase, time left, how many alive. Never shows roles.
- Phase banners in Town Centre show the phase, deadline and alive count. The newest one is pinned.
- **Warnings** go out at 25% of a phase's time left (between 30 seconds and 15 minutes), and players with an unset
  night action are nudged.

### Common situations

| Situation | What to do |
|---|---|
| Need a break | `monke pause`, then `monke resume` |
| People need more time | `monke extend 2m` |
| Everyone is ready, waiting for timer | `monke skip` (or players use **Skip ahead**) |
| Someone left | See [Replacing a player](#replacing-a-player) or [Removing a player](#removing-a-player) |
| Game is broken or abandoned | `monke abort` |
| Something looks off | `monke diagnose` |

## Moderation tools

### Replacing a player

```
monke replace @OldPlayer @NewPlayer
```

The new player takes over the same slot, with the same role, abilities already used and journal. The bot checks that
they are in the server, are not already playing and can be DMed. Everyone is told which slot changed hands, and
nothing else. The archive records both people.

### Removing a player

```
monke modkill @Player optional reason
```

The player dies with the cause "an admin", and their role is revealed like any other death. During the day it is
immediate. At night it happens at dawn.

### Skipping, pausing and extending

- `monke pause` freezes timers and makes **every channel read-only**, including the Graveyard and the Jail.
- `monke resume` continues with the remaining time.
- `monke extend 90s` adds time to the current phase. In a paused game it adds to the remaining time.
- `monke skip` ends the current phase now. The bot refuses a skip within 3 seconds of a phase change.

### Settings

`monke settings` shows the server's default settings. `monke settings preset=relaxed early_night=on` changes them for
all future games. Settings are frozen when a game starts.

## After the game

1. The bot posts **game over** with every player's role and fate, in Town Centre and in **#monke-lobby**, with a
   **Play again** button.
2. Players can keep chatting in Town Centre for 5 minutes (`post_game_chat`).
3. Then the bot builds the **archive**, a zip with:
   - `README.txt`, `timeline.txt`
   - `chat/` (all channel chat, including edits and deletes)
   - `abilities/` (night by night what each role did)
   - `votes_and_trials.txt`
   - `data/game.json` (can be replayed)
4. It posts the zip in **#monke-commands**, **empties the game channels** and DMs each player a separator.

If the archive fails, nothing is deleted. Use `monke export` to retry. A new game cannot start until the archive is
finished.

Chat is kept in the bot's database for 7 days (configurable by whoever runs the bot) and then pruned. The zip itself
stays in Discord.

## Good habits

- **Run `monke diagnose` before game night.**
- **Do not rename or edit** the `Monke Admin` role, the number roles, or the Town of Monke channels and their permissions
  by hand. The bot re-applies permissions as phases change, and manual changes can leak information. `monke setup`
  restores anything you broke.
- **Do not reorder roles** so that the bot's role falls below the game roles.
- **Don't give anyone Administrator** if they are playing.
- **Announce the rules** you want to enforce (see [Conduct](rules.md#conduct)).
- **Keep admins out of Town Centre** during a game unless they are playing, so people don't wonder who is looking.

## Removing everything

```
monke teardown
```

Asks for confirmation, then deletes the Town of Monke category, all its channels and the Monke Admin and number roles. It
is refused during a game, or if an archive has not finished (use `--force` to override). Server managers only.

# Role lists and settings

How to decide **which roles** are in a game and **how long each phase lasts**.

## Contents

- [Role lists](#role-lists)
- [Default role lists](#default-role-lists)
- [Settings](#settings)
- [Presets](#presets)
- [Where settings come from](#where-settings-come-from)

## Role lists

A **role list** has exactly **one entry per player**, so a 10-player game has 10 entries. Entries are either:

- an **exact role** (`Sheriff`, `Serial Killer`), or
- a **group token** such as `TI` (Town Investigative), or
- a **random token** such as `RT` (random Town).

Tokens are explained in the [Roles overview](roles/README.md#role-types-and-the-tokens-you-use-in-role-lists).

### Rules

1. The list must contain **exactly one `Jailor`** and **exactly one `Godfather`**.
2. The length must match the number of players (5 to 20).
3. **Unique** roles (Jailor, Veteran, Godfather, Mafioso) cannot appear twice. If a token would have to draw a unique
   role that is already used up, the game cannot start. (Example: `TK TK` fails, because there is only one Veteran.)
4. Names are case-insensitive. `serial killer`, `Serial_Killer` and `SerialKiller` all work.
5. Separate entries with spaces, commas, semicolons or new lines.

### How roles are drawn

1. Exact roles are placed first.
2. Group tokens (`TK`, `TI`, ...) are drawn next.
3. Random tokens (`RT`, `RM`, `RN`, `Any`) are drawn last.
4. Roles are then shuffled onto players, and slot numbers are shuffled independently.

Every draw is logged in the archive, so a game can be replayed.

### Examples

A classic 15-player list:

```
Jailor, TK, TI, TI, TP, TP, TS, RT, RT, Godfather, MK, RM, RM, NK, NE
```

A tiny 5-player game with a random neutral:

```
Jailor, TI, TP, Godfather, RN
```

A chaotic 10-player game:

```
Jailor, Godfather, Any, Any, Any, Any, Any, Any, Any, Any
```

You can set a list three ways: type it after `monke start @players...`, press **Edit role list** in the lobby, or accept
the default.

## Default role lists

If you do not specify a list, the bot builds one for the number of players. Town always outnumbers Mafia and Neutral
combined.

| Players | Town / Mafia / Neutral | Role list |
|---|---|---|
| 5 | 3 / 1 / 1 | Jailor, TI, TP, Godfather, RN |
| 6 | 4 / 1 / 1 | Jailor, TK, TI, TP, Godfather, RN |
| 7 | 4 / 2 / 1 | Jailor, TK, TI, TP, Godfather, MK, RN |
| 8 | 5 / 2 / 1 | Jailor, TK, TI, TP, TS, Godfather, MK, RN |
| 9 | 6 / 2 / 1 | Jailor, TK, TI, TI, TP, TS, Godfather, MK, RN |
| 10 | 6 / 3 / 1 | Jailor, TK, TI, TI, TP, TS, Godfather, MK, RM, RN |
| 11 | 7 / 3 / 1 | Jailor, TK, TI, TI, TP, TP, TS, Godfather, MK, RM, RN |
| 12 | 7 / 3 / 2 | Jailor, TK, TI, TI, TP, TP, TS, Godfather, MK, RM, NK, NE |
| 13 | 8 / 3 / 2 | Jailor, TK, TI, TI, TP, TP, TS, RT, Godfather, MK, RM, NK, NE |
| 14 | 8 / 4 / 2 | Jailor, TK, TI, TI, TP, TP, TS, RT, Godfather, MK, RM, RM, NK, NE |
| 15 | 9 / 4 / 2 | Jailor, TK, TI, TI, TP, TP, TS, RT, RT, Godfather, MK, RM, RM, NK, NE |
| 16 | 10 / 4 / 2 | Jailor, TK, TI, TI, TP, TP, TS, RT, RT, RT, Godfather, MK, RM, RM, NK, NE |
| 17 | 10 / 5 / 2 | Jailor, TK, TI, TI, TP, TP, TS, RT, RT, RT, Godfather, MK, RM, RM, RM, NK, NE |
| 18 | 11 / 5 / 2 | Jailor, TK, TI, TI, TP, TP, TS, 4x RT, Godfather, MK, RM, RM, RM, NK, NE |
| 19 | 12 / 5 / 2 | Jailor, TK, TI, TI, TP, TP, TS, 5x RT, Godfather, MK, RM, RM, RM, NK, NE |
| 20 | 13 / 5 / 2 | Jailor, TK, TI, TI, TP, TP, TS, 6x RT, Godfather, MK, RM, RM, RM, NK, NE |

The 15-player list is the classic one. Check any game's defaults with `/rolelist <count>`.

> **Today vs 2.0:** because each role type currently has only one role, small games repeat roles (two Sheriffs, two
> Doctors) and `RT` often gives duplicates. When 2.0 adds more roles per type, the same lists will give much more variety.

## Settings

Settings are `key=value` pairs. Put them after `monke start`, in the lobby's **Edit settings** window (one per line or
comma-separated), or save server-wide defaults with `monke settings`.

### Durations

Written as `90s`, `2m`, `1h`. **A bare number means minutes** (`night=3` is 3 minutes).

| Key | Default | What it controls | Minimum |
|---|---|---|---|
| `day` | 4m | Day discussion. **Day 1 is half of this** | 2m |
| `noon` | 3m | Voting window | 2m |
| `afternoon` | 2m | Afternoon discussion | 2m |
| `night` | 2m | Night | 2m |
| `defense` | 30s | The accused's defense | 15s |
| `verdict` | 20s | Verdict voting | 15s |
| `post_game_chat` | 5m | How long players keep Town Centre after the game ends | 0 |
| `lobby_timeout` | 30m | Lobby closes after this much inactivity (server default only) | 1m |

### Numbers

| Key | Default | What it controls |
|---|---|---|
| `stalemate` | 3 | Quiet cycles (no deaths) before a draw. `0` turns it off |
| `afk_cycles` | 3 | Inactive days before a player is removed. `0` turns it off |
| `will_max` | 600 | Max characters in a will |
| `note_max` | 300 | Max characters in a death note |

### Switches

Accepted values: `on`/`off`, `true`/`false`, `yes`/`no`, `1`/`0`.

| Key | Default | What it controls |
|---|---|---|
| `early_day` | on | Majority can press **Skip ahead** during day phases |
| `early_night` | off | Night ends early once everyone with an action confirms |
| `allow_wills` | on | Wills are enabled |
| `allow_deathnotes` | on | Death notes are enabled |
| `downtime_compensation` | on | Give time back after the bot has been offline |

### Typos

The bot catches mistakes and suggests a fix, e.g. `nigth=3m` gets "did you mean `night`?".

## Presets

A preset sets all the phase lengths at once. Explicit durations always win over a preset, regardless of order:
`preset=blitz night=3m` is Blitz with a 3-minute night.

| Preset | Day | Noon | Afternoon | Night | Defense | Verdict | Best for |
|---|---|---|---|---|---|---|---|
| `blitz` | 2m | 2m | 2m | 2m | 15s | 15s | A quick game when everyone is online |
| `normal` | 4m | 3m | 2m | 2m | 30s | 20s | The default |
| `relaxed` | 8m | 4m | 4m | 4m | 45s | 30s | Newer players, or chatty groups |
| `async` | 2h | 1h | 1h | 2h | 10m | 10m | Play over days, check in a few times a day |

Day 1 is always half of `day`.

## Where settings come from

Settings are layered, and later layers override earlier ones:

1. **Built-in defaults** (the `normal` preset and the values above)
2. **Server defaults**, saved with `monke settings key=value`
3. **Per-game settings**, from `monke start`, the lobby, or **Play again**

The result is **frozen when the game starts**. Changing server defaults mid-game does not affect it. The archive records
the layers.

If a value is below the minimum (for example a 30-second night), the game refuses to start and tells you which setting
to fix.

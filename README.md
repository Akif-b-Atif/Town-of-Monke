# Town of Monke

**A Discord bot that runs a full game of *Town of Salem* with your friends**, using channels, buttons and direct messages.
Hidden roles, night actions, trials, lynches, an anonymous Jailor, a Mafia chat, and a graveyard, all inside your server.

> **Version 1.1.0.** 10 roles (one per role type), 5 to 20 players. **Version 2.0** will add many more roles.

## What a game looks like

1. The host opens a **lobby**; players press **Join**.
2. The bot DMs everyone a secret **role card**.
3. **Day:** everyone talks in **#town-centre**. At **Noon** the town votes someone onto trial, hears their defense, and votes
   Guilty or Innocent.
4. **Night:** roles act through DM menus. The Mafia plot in their private chat. The Jailor interrogates a prisoner
   anonymously.
5. **Dawn:** deaths and roles are revealed. Repeat until Town, Mafia or a Serial Killer wins (or the Jester gets lynched).

Channels appear and disappear automatically so players only see what they should. Afterwards the bot posts a full archive
(chat, votes, every night action) and tidies up.

## Features

- **Lobby with buttons**: Join, Leave, Start, edit settings and role list, plus **Play again**
- **Quick start**: `monke start @a @b @c @d @e` builds a sensible role list for you
- **Role lists with tokens** (`TI`, `RT`, `Any`, ...), plus default lists for 5 to 20 players
- **Presets** (`blitz`, `normal`, `relaxed`, `async`) and fine-grained settings for every phase
- **Wills, death notes and a private journal**
- **Pacing tools**: Skip ahead, early night end, pause, extend, AFK removal
- **Moderation**: replace a player, remove a player, diagnose problems
- **Crash-safe**: games survive restarts, and nothing is lost or posted twice
- **Post-game archive** posted as a zip, and replayable
- **Fully editable text**: all messages live in `flavour.yaml`

## The roles

| Team | Roles |
|---|---|
| **Town** | Jailor, Veteran, Sheriff, Doctor, Escort |
| **Mafia** | Godfather, Mafioso, Consigliere |
| **Neutral** | Serial Killer, Jester |

Details, abilities and interactions: **[docs/roles](docs/roles/README.md)**.

## Documentation

| I want to... | Read |
|---|---|
| **Play** | [Player guide](docs/player-guide.md), [Roles](docs/roles/README.md), [Rules](docs/rules.md) |
| **Host games** in a server | [Admin guide](docs/admin-guide.md), [Role lists and settings](docs/role-lists-and-settings.md), [Commands](docs/commands.md) |
| **Run the bot** | [Hosting the bot](docs/hosting.md) |
| Fix something | [Troubleshooting](docs/troubleshooting.md) |
| **Contribute** or add a role | [Development guide](docs/development.md) |

Start at the **[documentation index](docs/README.md)**.

## Quick start

**1. Install**

```bash
git clone https://github.com/Akif-b-Atif/Town-of-Monke.git
cd Town-of-Monke
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # then paste your bot token into .env
```

**2. Create the bot** in the [Discord Developer Portal](https://discord.com/developers/applications): copy the token and
enable the **Message Content Intent**.

**3. Invite it.** `python check.py` prints the invite URL with the correct permissions (**not** Administrator).

**4. Run it**

```bash
python -m monke
```

**5. Set up your server.** In Discord, as someone with Manage Server:

```
monke setup
```

Give your host the **Monke Admin** role, move the bot's role above the game roles, then run `monke diagnose` in
`#monke-commands`.

**6. Play.** In `#monke-commands`:

```
monke start
```

Players press **Join** in `#monke-lobby`. Full instructions are in the [Admin guide](docs/admin-guide.md) and
[Hosting guide](docs/hosting.md).

## Command cheat sheet

| Players | Admins (in `#monke-commands`) | Server managers |
|---|---|---|
| `/vote` `/unvote` `/votes` | `monke start` `lobby` `status` | `monke setup` |
| `/alive` `/timer` `/rolelist` | `monke pause` `resume` `extend` `skip` `abort` | `monke teardown` |
| `/role` `/journal` `/resend` | `monke modkill` `replace` | |
| `/will` `/deathnote` `/help` | `monke settings` `diagnose` `export` `admins` `reloadtext` | |

Everything is explained in the **[command reference](docs/commands.md)**.

## Architecture

```
adapter/   Discord only: command registry, views, renderer (events -> messages), planner (state -> permissions), relay
service/   GameService: per-guild lock, timers, SQLite persistence, recovery, fail-closed
engine/    PURE: (state, command, now) -> (new_state, events). Zero Discord imports
roles/     RoleDef data + a handler per role, collected in a registry
sim/       Plays thousands of full games with fake players
```

The engine never imports `discord`, so the whole game is testable and simulatable offline. More in the
[Development guide](docs/development.md).

## Tests and simulation

```bash
python -m pytest                          # the full test suite
python -m monke.sim.cli --games 1000      # 1,000 random full games with invariants
python -m monke.text.check                # validate flavour.yaml
```

## Roadmap

- **2.0:** many more roles in every category. The docs are already structured for it.
- Not planned for 1.x: Mafioso promotion, multiple simultaneous games per server, a web dashboard.

See the [CHANGELOG](CHANGELOG.md) for what has shipped.

# Development guide

For contributors and for future-you. How the code is laid out, how to test it, and how to add things (especially roles
for v2.0) without breaking either the game or the documentation.

## Layout

```
monke/
  engine/    PURE game logic. (state, command, now) -> (new_state, events). No Discord imports
  roles/     RoleDef data + one handler per role, collected in a registry
  adapter/   Discord only: command registry, views (buttons), renderer (events -> messages),
             planner (state -> channel permissions), jail relay, lobby, setup
  service/   GameService: per-guild lock, timers, SQLite persistence, recovery, outbox, archive
  archive/   Builds the post-game zip
  text/      The text system: loads and validates flavour.yaml
  sim/       Plays thousands of full games with fake players; replays archived games
  data/      Shipped default text (flavour_default.yaml)
tests/       pytest suite
flavour.yaml  Every player-visible string (copied from monke/data/flavour_default.yaml)
docs/        You are here
```

Key ideas:

- **`engine` never imports `discord`.** The whole game is testable and simulatable offline.
- **Every input goes through one path:** lock, `engine.handle`, persist in one transaction, sync permissions, render,
  re-arm the timer.
- **Channel permissions come from one pure function** (`adapter/planner.py`), diffed against what is applied. Handlers
  never edit permissions directly.
- **Stale timers and stale buttons are harmless.** The engine ignores a mismatching `phase_id`, and prompts carry a
  freshness token.
- **All player-visible text is data** in `flavour.yaml`. The engine emits text *keys* and variables, and the renderer
  turns them into words.
- **One command registry** (`adapter/handlers.py`) generates slash commands, `monke` text commands, `/help` and the
  permission checks.

## Running the tests and tools

```bash
python -m pytest                          # the full suite (hundreds of tests, about 30 seconds)
python -m monke.sim.cli --games 1000      # 1,000 random full games with invariant checks
python -m monke.sim.cli --games 1 --seed 7 --players 12 --debug   # one game, every event printed
python -m monke.text.check                # validate flavour.yaml
python -m monke.sim.replay path/to/game.json   # replay an archived game, print the first divergence
python -m monke --debug                   # run the bot and print every role and decision (spoils live games)
```

## Adding a role (checklist)

The README used to say "create a `RoleDef` and a handler and call `register()`". In full:

### Code

1. In `monke/roles/town.py`, `mafia.py` or `neutral.py`, define a `RoleDef` (see the existing ones) with:
   id, name, alignment, group (`TK TI TP TS MK MS NK NE`), unique flag, attack level, defense level, roleblock
   immunity, Sheriff result, win faction, and its `AbilityDef`s.
2. Add a `RoleHandler` subclass for its state, targets and validation, and call `register()`.
3. If the role introduces a **new interaction**, add the step in `engine/night.py` (the single place the night order lives).
   Keep the ordering rules in one place.
4. If it changes how the game is won, update `engine/wincheck.py`.
5. Because groups and tokens (`TK`, `RT`, ...) draw from the registry automatically, the default role lists will start
   using the new role right away. Check that `default_rolelist` still produces sensible lists.

### Text

6. Add the role's keys to `flavour.yaml` and `monke/data/flavour_default.yaml` (keep them identical): `role.<id>.name`,
   `.intro`, `.goal`, `.tips`, `.reveal`, `.wiki`, plus any new notes or cause-of-death lines.
7. Run `python -m monke.text.check`.

### Tests

8. Add scenarios to `tests/test_night.py` (and others as needed), and run the simulator. The fuzz test and
   `monke.sim.cli` will exercise the new role in random games.

### Documentation (do not skip)

9. Add an entry to the right category page under `docs/roles/` using [`docs/roles/TEMPLATE.md`](roles/TEMPLATE.md).
10. Update the "at a glance" and token tables in [`docs/roles/README.md`](roles/README.md).
11. If the night order changed, update [How the night resolves](rules.md#how-the-night-resolves) and the Mafia kill chain
    section if relevant.
12. If default role lists changed, update the [table of default role lists](role-lists-and-settings.md#default-role-lists).
    You can regenerate it with:

    ```python
    from monke.engine.rolelist import default_rolelist
    for n in range(5, 21):
        print(n, " ".join(default_rolelist(n)))
    ```
13. Add a line to [`CHANGELOG.md`](../CHANGELOG.md).

## Design decisions worth knowing

- **Veteran defense on alert.** The original spec table said None, but Town of Salem gives Basic defense while on alert.
  Basic is implemented. It is one switch: `VETERAN_ALERT_DEFENSE` in `monke/roles/town.py`. If you change it, update the
  [Veteran page](roles/town.md#veteran) and the [attack and defense table](roles/README.md#attack-and-defense-levels).
- **Slot-to-player mapping is public**, and the role-to-player mapping never is. Slot roles (`1` to `20`) have no colour,
  hoist or permissions.
- **Mafia cannot target Mafia.** Godfather and Mafioso target menus exclude teammates.
- **A blocked Serial Killer attacks the blocker**, even without a chosen target. An Escort who targets the prisoner just
  gets "target in jail".
- **Win check extras:** only Neutral Evil roles left is a draw, and two living Serial Killers do not win (the game goes on to
  the stalemate rule).
- **Stalemate** counts full cycles (Day lynch plus Night) with zero deaths. Day 1 plus Night 1 is cycle 1.

## Documentation conventions

- **One source of truth per fact.** Rules live in `rules.md`. Role pages describe roles and link to rules instead of
  repeating them.
- **Describe behaviour, not code.** Say what a player sees. Keep code references to the development guide.
- **Version notes.** If a limit is expected to go away (for example repeated roles in small games), say so in a note, so
  readers know it is temporary.
- **Link, do not duplicate.** Use relative links between pages.
- When changing a default (phase length, defaults per player count, minimums), search `docs/` for the old value.

## Known limits (out of scope for 1.x)

Mafioso promotion, dead players reading the Mafia Lair (unless they were Mafia), multiple simultaneous games in one server,
early phase ending beyond Skip ahead and early night end, and a web dashboard.

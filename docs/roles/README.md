# Roles

> **Version note.** Town of Monke 1.x ships with **10 roles**, exactly one per role type. Version 2.0 will add many more
> roles to each category. This section is organised so new roles slot in without changing how you read it: the
> category pages ([Town](town.md), [Mafia](mafia.md), [Neutral](neutral.md)) simply gain entries, and the tables below
> gain rows.

Every player gets one secret role at the start of the game. Your role decides your **team**, your **goal** and what
you can do at night (or during the day).

## The roles at a glance

| Role | Team | Type | Ability | Attack | Defense | Sheriff sees | Unique* |
|---|---|---|---|---|---|---|---|
| [Jailor](town.md#jailor) | Town | Leader | Jail one player by day, interrogate and optionally execute at night | Unstoppable | None | Innocent | Yes |
| [Veteran](town.md#veteran) | Town | Killing | Go on alert; shoot every visitor | Powerful | None (Basic on alert) | Innocent | Yes |
| [Sheriff](town.md#sheriff) | Town | Investigative | Check whether a player is suspicious | None | None | Innocent | No |
| [Doctor](town.md#doctor) | Town | Protective | Heal one player; self-heal once | None | None | Innocent | No |
| [Escort](town.md#escort) | Town | Support | Roleblock one player | None | None | Innocent | No |
| [Godfather](mafia.md#godfather) | Mafia | Leader | Order the Mafia's nightly kill | Basic | Basic | **Innocent** | Yes |
| [Mafioso](mafia.md#mafioso) | Mafia | Killing | Carry out the nightly kill | Basic | None | Suspicious | Yes |
| [Consigliere](mafia.md#consigliere) | Mafia | Support | Learn a player's exact role | None | None | Suspicious | No |
| [Serial Killer](neutral.md#serial-killer) | Neutral | Killing | Kill one player each night | Basic | Basic | Suspicious | No |
| [Jester](neutral.md#jester) | Neutral | Evil | Get lynched, then haunt a voter | Unstoppable (haunt only) | None | Innocent | No |

\* **Unique** roles can appear at most once per game. Non-unique roles can appear more than once, which is how small
games can end up with two Sheriffs or two Doctors (the default role lists do this on purpose).

## Role types and the tokens you use in role lists

Role lists (see [Role lists and settings](../role-lists-and-settings.md)) can contain exact role names or *tokens*
that stand for "any role of this type". Tokens are what make a game unpredictable.

| Token | Meaning | Currently draws from |
|---|---|---|
| `Jailor` | The Jailor (exactly one required in every game) | Jailor |
| `Godfather` | The Godfather (exactly one required in every game) | Godfather |
| `TK` | Town Killing | Veteran |
| `TI` | Town Investigative | Sheriff |
| `TP` | Town Protective | Doctor |
| `TS` | Town Support | Escort |
| `MK` | Mafia Killing | Mafioso |
| `MS` | Mafia Support | Consigliere |
| `NK` | Neutral Killing | Serial Killer |
| `NE` | Neutral Evil | Jester |
| `RT` | Random Town | Any Town role except the Jailor |
| `RM` | Random Mafia | Any Mafia role except the Godfather |
| `RN` | Random Neutral | Any Neutral role |
| `Any` | Anything | Any role except Jailor and Godfather |

Right now each type holds a single role, so `TI` always means Sheriff. In 2.0, `TI` will mean "a random Town
Investigative role" and the same role list will produce much more varied games.

## Attack and defense levels

Every kill has an **attack level** and every player has a **defense level**. An attack only kills if its level is
**higher** than the target's defense.

| Level | Name | Examples |
|---|---|---|
| 0 | None | Sheriff, Doctor, Escort, Consigliere |
| 1 | Basic | Mafioso and Godfather attacks, Serial Killer attacks. Godfather, Serial Killer, and an alert Veteran have Basic defense |
| 2 | Powerful | Veteran shots |
| 3 | Unstoppable | Jailor executions, Jester haunts |

Two extra rules:

- A **heal** from a Doctor stops any attack below Unstoppable, regardless of defense.
- Unstoppable attacks ignore both defense and healing.

So a Mafioso (Basic) cannot kill a Godfather, a Serial Killer, or a Veteran on alert, and a Doctor can never save
someone from an execution or a haunt.

## Roleblock immunity

The **Jailor**, **Veteran** and **Escort** cannot be roleblocked. Everyone else can.

## What the Sheriff sees

| Result | Roles |
|---|---|
| Innocent | All Town roles, the **Godfather**, the **Jester** |
| Suspicious | Mafioso, Consigliere, Serial Killer |

Remember: an "innocent" result is not proof of Town. The Godfather and the Jester both pass.

## Which teams win how

See [Win conditions](../rules.md#win-conditions).

## Adding documentation for a new role (v2.0 prep)

When a role is added, follow [`TEMPLATE.md`](TEMPLATE.md) and also update:

1. The "at a glance" table above.
2. The token table above (new roles change what a token draws from).
3. The relevant category page.
4. [`../rules.md`](../rules.md#how-the-night-resolves) if the role adds a new step to the night order.
5. [`../../CHANGELOG.md`](../../CHANGELOG.md).

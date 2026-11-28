# Neutral roles

Neutral roles do not belong to the Town or the Mafia. Each has its own goal.

Back to the [roles overview](README.md).

---

## Serial Killer

| | |
|---|---|
| **Team / type** | Neutral Killing (`NK`) |
| **Unique** | No |
| **Attack / defense** | Basic / Basic |
| **Roleblock immune** | No |
| **Sheriff result** | Suspicious |

### Goal
Be the last one standing, with nobody left who could stop you. In practice: **be the only killer left, with no Town and
no Mafia alive.**

### What it does
Each night you may kill one player. You have **Basic defense**, so Mafioso kills cannot hurt you.

### Interactions
- **Roleblocked:** you lash out and **attack whoever roleblocked you**, even if you had picked no target.
- **Jailed:** you lash out and **attack the Jailor** (a Basic attack; they die unless healed).
- Your Basic attack cannot kill a Godfather, another Serial Killer or an alert Veteran.
- A healed target survives your attack.
- Sheriffs see you as suspicious.

### Notes
- If two Serial Killers (possible only with a custom role list such as `NK NK`) are the last two alive, neither wins
  and the game continues until the stalemate rule ends it in a draw.
- You win alone, not with a team.

### Tips
- Do not draw attention. Both Town and Mafia want you dead.
- Beware the Jailor and the Escort: they punish you, but only if you attack them.

---

## Jester

| | |
|---|---|
| **Team / type** | Neutral Evil (`NE`) |
| **Unique** | No |
| **Attack / defense** | Unstoppable (haunt only) / None |
| **Roleblock immune** | No |
| **Sheriff result** | Innocent |

### Goal
Get yourself **lynched** by the town.

### What it does
You have no ability while alive. If the town lynches you:

1. **You win**, and the town is told so. **The game keeps going** for everyone else.
2. Your ghost may **haunt** one living player **who voted guilty** against you. Haunting is an **Unstoppable** attack
   and kills them.
3. The haunt is a night action. It stays available until you use it, so you can wait until a later night.

### Interactions
- Doctors cannot stop a haunt.
- If everyone who voted guilty is already dead, there is nobody left to haunt.
- Neutral Evil roles do **not** stop the Town or the Mafia from winning. If *only* Neutral Evil roles remain alive, the
  game ends in a **draw**.
- The Jester appears **innocent** to the Sheriff.

### Tips
- Be suspicious, but not too suspicious. If the town is sure you are the Jester, they will not lynch you.
- Your "win" is shared with whichever team finishes the game.

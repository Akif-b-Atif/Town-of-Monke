# Mafia roles

The Mafia wins when **no Town and no Serial Killer remain alive** (Neutral roles that do not kill do not matter).
Their goal on the role card is *"Kill everyone who would oppose the Mafia."*

Back to the [roles overview](README.md).

**How the Mafia works as a team**

- Mafia members are told who their teammates are on their role card.
- At **night**, living Mafia can talk in the **Mafia Lair** channel. During the day they can read it but not write.
  (A jailed Mafia member can read but not write.)
- The Mafia gets **exactly one kill per night**. Who performs it depends on who is alive and free; see
  [The Mafia kill chain](../rules.md#the-mafia-kill-chain).
- Mafia members **cannot target each other** with kills or orders.
- Dead Mafia keep read-only access to the Lair.

---

## Godfather

| | |
|---|---|
| **Team / type** | Mafia Leader (`Godfather`) |
| **Unique** | Yes. Every game has exactly one Godfather |
| **Attack / defense** | Basic / Basic |
| **Roleblock immune** | No |
| **Sheriff result** | **Innocent** |

### What it does
Each night you **order the Mafioso to kill** a target of your choice. If there is no Mafioso (dead, or roleblocked or
jailed that night), **you carry out the kill yourself**.

You have **Basic defense**, so a Mafioso or Serial Killer cannot kill you at night, and the Sheriff sees you as
**innocent**.

### What you see
Your role card lists your teammates. If the Mafioso is unavailable, you are told you had to take over the kill.

### Interactions
- Your order overrides whatever the Mafioso wanted to do.
- **Roleblocked or jailed:** your order is lost and the Mafioso picks a target alone.
- With a small game (5 or 6 players) the default role list has **no Mafioso**, so you do all the killing.

### Tips
- Let the Mafioso take the risk. If your kill is the one that happens, you will be exposed if it fails.
- Your Sheriff result is your best asset when defending yourself.

---

## Mafioso

| | |
|---|---|
| **Team / type** | Mafia Killing (`MK`) |
| **Unique** | Yes |
| **Attack / defense** | Basic / None |
| **Roleblock immune** | No |
| **Sheriff result** | Suspicious |

### What it does
You carry out the Godfather's kill. If the Godfather gives **no order**, you choose a victim yourself.

### What you see
You are told when you receive an order from the Godfather.

### Interactions
- If you are **roleblocked or jailed**, the Godfather performs the kill himself (if he is free).
- You cannot target other Mafia.
- A Basic attack cannot kill a Godfather, a Serial Killer, or a Veteran on alert, and a healed target survives.

### Tips
- Stay quiet by day. You are the first to die if the town suspects the Mafia.

---

## Consigliere

| | |
|---|---|
| **Team / type** | Mafia Support (`MS`) |
| **Unique** | No |
| **Attack / defense** | None / None |
| **Roleblock immune** | No |
| **Sheriff result** | Suspicious |

### What it does
Each night you investigate one player and learn their **exact role** (not just innocent or suspicious).

### What you see
The player's role in your dawn recap, and in `/journal`.

### Interactions
- **Roleblocked** or **jailed:** you learn nothing.
- Visiting a Veteran on alert gets you shot.

### Tips
- Pass information to your family in the Lair, and point them at the Sheriff, Doctor and Jailor before the town
  finds you.

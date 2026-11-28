# Town roles

The Town wins by eliminating every threat: all the Mafia and all Serial Killers. Neutral roles that do not kill (like
the Jester) do not have to be removed. Town roles all share the goal *"Lynch every criminal and evildoer."*

Back to the [roles overview](README.md).

---

## Jailor

| | |
|---|---|
| **Team / type** | Town Leader (`Jailor`) |
| **Unique** | Yes. Every game has exactly one Jailor |
| **Attack / defense** | Unstoppable (execution) / None |
| **Roleblock immune** | Yes |
| **Sheriff result** | Innocent |

### What it does
Each **day** you choose one player to jail. At dusk that player is locked up for the night. While they are jailed you
can talk to them privately and, if you want, **execute** them.

- The prisoner **cannot use their ability** tonight, and **nobody can harm them** (attacks against them fail).
- The conversation is **anonymous**: the prisoner sees you only as "Jailor" in the Jail channel, and you talk to them by
  sending messages to the bot in your DMs.
- **Execute** is a button on your night prompt. An execution is an Unstoppable attack, so Doctors cannot save the
  victim.
- If you execute a **Town** member, you **lose your executions for the rest of the game**. You can still jail.

### What you see
- A prompt each day to pick a prisoner (you can change your pick until the day ends).
- At night, a prompt with an Execute toggle, and the prisoner's messages relayed to your DMs. Only messages that do
  not start with `monke ` are relayed.

### Night order
Jail takes effect first (the prisoner's action is cancelled), and the execution resolves with the other attacks. See
[How the night resolves](../rules.md#how-the-night-resolves).

### Interactions
- **Jailed Serial Killer:** lashes out and attacks you. Basic attack versus your lack of defense: you die unless a Doctor heals you.
- **Jailed Mafia member:** can read the Mafia Lair but cannot talk there tonight. If it is the Godfather, his order is
  lost and the Mafioso decides alone.
- **Visits to the prisoner fail.** The visitor is told the target was in jail. Attackers are told their attack was
  stopped, and the prisoner is told they were attacked in jail (once, however many tried).
- If the Jailor dies during the day, no one is jailed that night.

### Tips
- Interrogate before you execute. You have no way to verify what a prisoner says, so look for contradictions.
- Jailing a confirmed or suspected killer also protects the town for the night.
- Revealing yourself is risky, but a believable Jailor can anchor the town.

---

## Veteran

| | |
|---|---|
| **Team / type** | Town Killing (`TK`) |
| **Unique** | Yes |
| **Attack / defense** | Powerful / None (Basic while on alert) |
| **Roleblock immune** | Yes |
| **Sheriff result** | Innocent |

### What it does
On any night you may **go on alert**. Everyone who visits you that night is shot, friend or foe. You have a limited
number of alerts, equal to **one per five players in the game, minimum one** (so 5 to 9 players: 1 alert; 10 to 14: 2;
15 to 19: 3; 20: 4).

While on alert you have **Basic defense**, so a Mafioso or Serial Killer attack cannot kill you.

### What you see
- A toggle button on your night prompt, with your alerts remaining.
- A note at dawn if you shot a visitor.

### Interactions
- Visits that trigger a shot: investigating, healing, roleblocking and killing. Jailing, executing and haunting are not
  visits.
- An **Escort** who targets you cannot block you, and is shot for visiting.
- A **killer** who visits you on alert is shot **and** their attack fails.
- Alerting uses up an alert even if nobody visits.
- Being **roleblocked** does not apply to you, but being **jailed** does cancel your alert.

### Tips
- Alerts are scarce. Save them for nights you expect trouble, such as after you have claimed Veteran.
- You can kill Town by accident. Think twice before alerting if you trust the town's investigators.

---

## Sheriff

| | |
|---|---|
| **Team / type** | Town Investigative (`TI`) |
| **Unique** | No |
| **Attack / defense** | None / None |
| **Roleblock immune** | No |
| **Sheriff result** | Innocent |

### What it does
Each night you investigate one player and learn whether they are **innocent** or **suspicious**.

| Result | Meaning |
|---|---|
| Innocent | Any Town role, the **Godfather** or the **Jester** |
| Suspicious | The Mafioso, the Consigliere or a Serial Killer |

### What you see
A line in your dawn recap. Everything you learn is also saved in `/journal`.

### Interactions
- **The Godfather looks innocent.** A clean result is not a guarantee.
- **Roleblocked:** you learn nothing and are told you were blocked.
- **Jailed:** you cannot investigate.

### Tips
- Do not out yourself too early; the Mafia will want you dead.
- Combine results with other information. "Innocent" can still be the Godfather or the Jester.

---

## Doctor

| | |
|---|---|
| **Team / type** | Town Protective (`TP`) |
| **Unique** | No |
| **Attack / defense** | None / None |
| **Roleblock immune** | No |
| **Sheriff result** | Innocent |

### What it does
Each night you protect one player. A healed player survives any attack **below Unstoppable**, regardless of their
defense. You may **heal yourself once** per game.

### What you see
- If your patient was attacked, you are told so.
- The patient is told they were attacked and saved.
- Attackers are told their target was healed.

### Interactions
- **Cannot** stop Jailor executions or Jester haunts (Unstoppable).
- Healing a Veteran who is on alert does not stop the Veteran from shooting you.
- **Roleblocked** or **jailed:** the heal does not happen.

### Tips
- Guess what the killers want. Healing the player who is most loudly "claiming" a strong role often pays off.
- Save your one self-heal for when you think you are a target.

---

## Escort

| | |
|---|---|
| **Team / type** | Town Support (`TS`) |
| **Unique** | No |
| **Attack / defense** | None / None |
| **Roleblock immune** | Yes |
| **Sheriff result** | Innocent |

### What it does
Each night you **roleblock** one player: their night ability does not work. They are told they were blocked.

- The **Jailor**, **Veteran** and other **Escorts** are immune. You are told the target is immune.
- Roleblocking a **Serial Killer** makes them attack **you** instead of their target.
- Roleblocking the **Godfather** or **Mafioso** cancels their part of the kill (see
  [The Mafia kill chain](../rules.md#the-mafia-kill-chain)).

### Interactions
- Visiting a Veteran on alert gets you shot.
- If your target is in jail, the roleblock fails ("target in jail").

### Tips
- Blocking a killer is as good as saving their victim, but blocking a Serial Killer is dangerous for you.
- Blocking someone who "should" have used an ability and getting a result of nothing can reveal their role.

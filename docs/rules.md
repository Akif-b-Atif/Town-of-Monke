# Game rules

The complete rules of Town of Monke 1.x, from the lobby to the final win check. If you only want the short version,
read the [Player guide](player-guide.md) first.

Numbers below (phase lengths and so on) are the defaults of the **normal** preset. Your host can change them. See
[Role lists and settings](role-lists-and-settings.md).

## Contents

- [The idea](#the-idea)
- [Players, slots and teams](#players-slots-and-teams)
- [The day and night cycle](#the-day-and-night-cycle)
- [Voting and trials](#voting-and-trials)
- [How the night resolves](#how-the-night-resolves)
- [The Mafia kill chain](#the-mafia-kill-chain)
- [Jail](#jail)
- [Death, wills and death notes](#death-wills-and-death-notes)
- [Win conditions](#win-conditions)
- [Stalemate and draws](#stalemate-and-draws)
- [Inactivity (AFK)](#inactivity-afk)
- [Pausing, skipping and early endings](#pausing-skipping-and-early-endings)
- [What is public and what is secret](#what-is-public-and-what-is-secret)
- [Conduct](#conduct)

## The idea

Monke Town has a few secret criminals. The Town has to find and lynch them. The Mafia and other evil roles kill by
night and lie by day. Everyone has a secret role, handed out by DM.

A game needs **5 to 20 players**. The bot runs the whole game through Discord channels (which appear and disappear
for you depending on the phase) and private messages.

## Players, slots and teams

- Each player gets a **slot number** (1 to 20), assigned at random. Slots are **public**. The roster, such as
  `Maya (#3)`, is posted when the game starts, and you vote using names or numbers.
- Your **role** is secret and handed to you by DM.
- The **role list** (which roles are in the game) is public, but **which player has which role is never shown** until
  they die or the game ends.
- Roles belong to one of three teams: **Town**, **Mafia** and **Neutral**. See [Roles](roles/README.md).

## The day and night cycle

A game is a repeating loop of phases. At the default settings:

| Phase | Length | What happens |
|---|---|---|
| **Day 1** | 2 min | Half-length first day. Talk and plan. **No voting.** Jailor can pick a prisoner |
| **Night** | 2 min | Roles act. Mafia talk in the Lair. Town Centre is read-only |
| **Day** *(Day 2 onward)* | 4 min | Dawn report, then open discussion in Town Centre |
| **Noon** | 3 min | Voting opens. Reaching a majority starts a trial |
| **Trial: Defense** | 30 s | Only the accused can talk |
| **Trial: Verdict** | 20 s | Everyone else votes Guilty, Innocent or Abstain |
| **Afternoon** | 2 min | Discussion continues. No more voting |
| **Night** | 2 min | And so on |

The pattern is **Day 1, Night 1, Day 2 (talk, Noon, Afternoon), Night 2, Day 3, ...** until someone wins.

Notes:

- **Day 1 is half the length of a normal Day** and has no vote, no Noon.
- The Noon timer **pauses during a trial** and resumes afterwards if the town pardons the accused, so a trial does
  not eat into the remaining voting time.
- Phase lengths come from a preset (`blitz`, `normal`, `relaxed`, `async`) or from custom settings.

### Who can talk where

| Phase | Town Centre | Mafia Lair | Jail |
|---|---|---|---|
| Day 1, Day, Noon, Afternoon | Everyone alive can talk | Mafia read-only | Closed |
| Defense | Only the accused talks, others read | Mafia read-only | Closed |
| Verdict | Everyone read-only (use the buttons) | Mafia read-only | Closed |
| Night | Everyone read-only | **Living Mafia talk** (not if jailed) | **The prisoner talks** (to the Jailor, anonymously) |
| Dead players | Read-only | Dead Mafia read-only | None |

Dead players have the **Graveyard** to talk in. See [Death](#death-wills-and-death-notes).

## Voting and trials

Voting happens only at **Noon**.

1. Vote with the panel posted in Town Centre (a menu, plus an **Unvote** button) or with `/vote`. You can **change
   or withdraw** your vote at any time during Noon.
2. Each vote is announced publicly with a running count such as `(2/5)`.
3. A player goes on trial the moment they reach a **strict majority of the living players**:
   `floor(alive / 2) + 1`. With 9 alive you need 5, with 10 alive you need 6.

Voting rules:

- You cannot vote for yourself or for a dead player.
- You cannot vote for someone who was **already pardoned today**.
- Your vote stays on its target until you change it. Votes are cleared when a trial ends.

### The trial

1. **Defense (30 s):** the accused is the only one allowed to talk.
2. **Verdict (20 s):** every living player **except the accused** presses **Guilty**, **Innocent** or **Abstain**.
   Not pressing anything counts as **Abstain**.
3. The result is revealed **by name**: who voted guilty, innocent and abstained.
4. **More Guilty than Innocent** votes means the accused is **lynched**. A tie, or more Innocent votes, means they are
   **pardoned**. Abstentions do not count either way.

What happens next:

| Outcome | Next |
|---|---|
| Lynched | The role is revealed. The day moves on to **Afternoon** (no more trials today) |
| Pardoned | Back to **Noon** with the time that was left. The pardoned player cannot be voted for again today |
| **Three pardons** in one day | No more trials. Straight to **Afternoon** |
| Noon ends with no trial | **Afternoon** |

At most **one lynching per day**.

## How the night resolves

At the end of the night (or earlier, if early night end is enabled and everyone confirms) the bot works out
everything at once. The order below always applies, and matters for strange cases.

1. **Freeze.** Each player's *latest* choice is used. Dead players' actions (except a Jester's haunt) and invalid
   targets are dropped.
2. **Jail.** The prisoner's own action is cancelled. If the Jailor chose to execute, it is queued.
3. **Roleblocks.** Escorts block their targets. Blocked players' actions are cancelled and they are told. Targets in
   jail cannot be blocked. Roleblock-immune roles (Jailor, Veteran, Escort) stay active and the Escort is told.
   A blocked **Serial Killer** is marked to strike the Escort.
4. **Mafia kill chain.** The Godfather's order and the Mafioso's choice become one kill. See below.
5. **Alerts.** A Veteran who chose to alert (and is not jailed or blocked) goes on alert and uses one alert.
6. **Visits.** All investigate, heal, roleblock and kill actions become *visits*. A visit to the prisoner **fails**, and
   the visitor is told. Jailing, executing, alerting and haunting are **not** visits.
7. **Alert shots.** Every visitor to an alert Veteran is shot (a Powerful attack).
8. **Heals.** Doctors' healing is applied (a self-heal uses up the one-time self-heal).
9. **Attacks.** Mafia kill, Serial Killer kills, the SK's revenge on blockers or on the Jailor, executions and haunts
   are all evaluated **at the same time** against the state *before* any deaths. An attack succeeds if it is
   **Unstoppable**, or if the target is **not healed** and the attack level is **higher than their defense**.
10. **Investigations.** The Sheriff and the Consigliere get their results.
11. **Feedback.** Players are told what happened to *their* actions (target healed, target too strong, you were
    attacked, and so on).
12. **Deaths.** All deaths are applied at once, and announced at dawn. If a Jailor executed a **Town** member, they lose
    their executions permanently.

Consequences worth remembering:

- Because attacks resolve simultaneously, two killers can kill the same person (they die once, with several causes),
  and two people can kill each other.
- A **heal protects against everything except Unstoppable attacks**, including attacks from several killers.
- Your **journal** (`/journal`) keeps every private result you have received.

### Attack and defense

| Attack | Beats defense |
|---|---|
| Basic (1) | None |
| Powerful (2) | None, Basic |
| Unstoppable (3) | Everything, and ignores healing |

See [the table of attack and defense per role](roles/README.md#attack-and-defense-levels).

## The Mafia kill chain

The Mafia kills **one player per night**, and the bot decides who carries it out:

| Situation | Who kills | Whom |
|---|---|---|
| Godfather gave an order, Mafioso is free | Mafioso | The Godfather's target |
| Godfather gave an order, Mafioso is dead, blocked or jailed | Godfather | The Godfather's target |
| No order, Mafioso is free and chose a target | Mafioso | The Mafioso's target |
| Godfather blocked or jailed, Mafioso is free | Mafioso | The Mafioso's target |
| Neither is free | Nobody | |

Mafia members **cannot target other Mafia**.

If the target of the kill is a prisoner, the attack fails and the prisoner is told they were attacked in jail.

## Jail

1. During the day, the Jailor picks one living player (not themself).
2. At dusk that player is **jailed**. They are told, and a private **Jail channel** opens for them. Only they can see it.
3. They talk in the channel. The bot relays their messages to the Jailor's DMs, and the Jailor's DM replies back into the
   channel as `Jailor:`. Neither side learns the other's name. A ✅ appears on the Jailor's message once it has been
   relayed.
4. The prisoner **cannot use their ability tonight** and **cannot be harmed** by anyone else. A killer who targets the
   prisoner fails and is told so.
5. The Jailor can also choose to **execute** (an Unstoppable attack). If the prisoner was Town, the Jailor loses
   executions for good.
6. At dawn the prisoner is released and the Jail channel is emptied.

If the Jailor or the chosen player has died before dusk, nobody is jailed.

## Death, wills and death notes

When a player dies:

- Their **role is revealed** to everyone (and it is a role, never an alignment guess).
- Their **will**, if they wrote one, is posted with the death for **every cause** of death (including lynching).
- A **death note** left by their killer is posted, but **only if the attack actually succeeded**.
- They lose access to the day chats (they can read Town Centre but cannot write) and gain access to the
  **Graveyard**, where the dead talk freely.
- Dead players **must not** pass information to the living, in DMs or elsewhere.

Wills are up to 600 characters and death notes up to 300 (your host can change these or turn them off). Write them
with `/will` and `/deathnote`, or with the buttons on your role card.

### Causes of death

| Cause | Meaning |
|---|---|
| Lynched | Voted guilty by the town |
| Mafia | A Mafia kill |
| Serial Killer | A Serial Killer's attack |
| Veteran | Shot while visiting an alert Veteran |
| Jailor | Executed |
| Jester haunt | Haunted by a lynched Jester |
| Abandonment | Removed for being inactive for too long |
| Admin | Removed by a moderator (`modkill`) |

## Win conditions

The game is checked after every death.

| Winner | Condition |
|---|---|
| **Town** | At least one Town player is alive, and no Mafia and no Serial Killer is alive |
| **Mafia** | At least one Mafia member is alive, and no Town and no Serial Killer is alive |
| **Serial Killer** | One Serial Killer is alive, and no Town and no Mafia |
| **Jester** | Is lynched. This is separate. The Jester wins **and the game continues** |
| **Draw** | Nobody alive, only non-killing Neutral roles remain, or the [stalemate rule](#stalemate-and-draws) triggers |

Notes:

- Non-killing Neutral roles, like the Jester, **never block** Town or Mafia from winning.
- Town and Mafia do **not** have to be a majority. They win only when the opposing killers are all gone.
- If the Mafia and a Serial Killer are alive and Town is gone, the game continues until one is eliminated or a
  stalemate is reached.

## Stalemate and draws

If **3 full cycles** pass with **no deaths** (Day lynch plus Night), the game ends in a **draw**. Day 1 plus Night 1
counts as cycle 1. The bot warns the town after the second quiet cycle. The limit can be changed with the `stalemate`
setting, and `stalemate=0` turns it off.

## Inactivity (AFK)

A living player who does **nothing** for a whole day (no message in Town Centre, no vote, no verdict, no button, no night
action, no will) has an **inactive day**. Day 1 is not counted.

- After **2** inactive days in a row, the player is warned and the admin is told.
- After **3** (the `afk_cycles` setting), the player is removed at the next dawn. Cause of death: abandonment.
- Any activity resets the counter.

Talking in Town Centre counts as activity, and so does voting, pressing a button or acting at night. Talking only in the
Mafia Lair does **not** count, so Mafia members should also say something in Town Centre.

## Pausing, skipping and early endings

- An admin can **pause** the game. Everything freezes: timers stop, and every channel becomes read-only. It is resumed
  with `monke resume`.
- An admin can **extend** the current phase or **skip** it.
- **Skip ahead:** during Day 1, Day and Afternoon, a majority of the living (`floor(alive/2)+1`) can press **Skip ahead**
  and move on early. (Noon and trials cannot be skipped this way.) Enabled by default (`early_day`).
- **Early night end:** an optional setting (`early_night`, off by default). When on, every night prompt gets a Confirm
  button, and when everyone who has a prompt confirms, the night ends right away.
- If the bot restarts, the game continues. The clock is frozen while the bot is offline and given back.

## What is public and what is secret

| Public | Secret (until death or end of game) |
|---|---|
| Slot numbers and names | Everyone's role |
| The role list | Who the Mafia are (except to the Mafia) |
| Votes and verdicts, by name | Night actions and their results |
| Deaths, and the role of anyone who dies | The Jailor's conversations (the prisoner does not know who the Jailor is) |
| Wills and death notes | What a Sheriff or Consigliere learns |

Channels are logged for the post-game archive. Do not assume private chat is unrecorded.

## Conduct

The bot cannot see what you do outside Discord's channels, so the game relies on honesty:

- **Do not show your role or screenshots** of your DMs to anyone. Claiming a role in chat is fine. Proving it with a
  screenshot is against the spirit of the game.
- **Dead players do not talk to the living.** The Graveyard is for the dead.
- **Do not coordinate outside the game** (voice chat, other servers) unless the whole table has agreed to.
- Players who have left or gone silent will be removed (see [AFK](#inactivity-afk)) or replaced by an admin.

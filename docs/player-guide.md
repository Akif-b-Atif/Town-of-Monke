# Player guide

Everything you need to join a game of Town of Monke and play it well, with no prior knowledge. If you have played
*Town of Salem* before, you will feel at home, but skim the [differences](#if-you-know-town-of-salem) first.

## The 60-second version

1. Open your **Discord DMs** to server members (the bot cannot start a game with you otherwise).
2. Press **Join** on the lobby message in **#monke-lobby**.
3. When the game starts, the bot **DMs you a role card**. Your role is secret.
4. **Day:** talk in **#town-centre**. At **Noon**, vote to put someone on trial. The accused defends themself, then
   everyone votes Guilty or Innocent.
5. **Night:** the bot DMs you a menu if your role can act. Pick a target (or **Do nothing**).
6. **Dawn:** find out who died, and repeat until one team wins.

## Before the game

### Allow DMs from the server

The bot gives out roles and night actions by direct message. In Discord:

> **Server name > Privacy Settings > Direct Messages: on**
> (on mobile, tap the server name and then *Privacy Settings*)

When you press **Join**, the bot sends you a test DM. If it cannot, it refuses and tells you how to fix it. The game
cannot start if any player's DMs are closed.

### Joining a lobby

Your host (called the **Monke Admin**) opens a lobby. You will see an embed in **#monke-lobby** listing the players,
the role list and the settings.

| Button | Who can use it | What it does |
|---|---|---|
| **Join** | Everyone | Adds you to the game (sends a test DM) |
| **Leave** | Everyone | Removes you |
| **Start**, **Edit settings**, **Edit role list**, **Cancel** | Monke Admin only | Controls the lobby |

Between **5 and 20** players are needed. A lobby closes on its own after 30 minutes of nothing happening. After a game,
a **Play again** button lets the same group start a fresh lobby.

Sometimes the host skips the lobby and just starts a game with a list of mentioned players. In that case you will be
added automatically, so make sure your DMs are open.

## The channels

The bot creates a **Town of Monke** category. You only see the channels you are allowed to see right now:

| Channel | Who | Purpose |
|---|---|---|
| **#monke-lobby** | Everyone (read-only) | Lobbies and game-over messages |
| **#monke-commands** | Everyone can read, only admins write | Admin actions, and the game archive after each game |
| **#town-centre** | Everyone playing | The main chat: day discussion, votes, trials and dawn reports |
| **#mafia-lair** | Mafia only | Mafia private chat (night only) |
| **#jail** | The prisoner only | Anonymous chat with the Jailor |
| **#graveyard** | The dead | The dead can chat freely |

Channels appear and vanish as phases change. Do not worry if a channel disappears. That is how the game keeps secrets.

## Your role card

At the start of the game the bot DMs you an **embed** with:

- Your **role** and **team**
- Your **ability** and any limits (for example, how many alerts you have)
- Your **goal**
- Tips and a link to the Town of Salem wiki page for the role
- If you are **Mafia**, who your teammates are
- Buttons **Edit will** and, for roles that can kill, **Edit death note**

Lost it? Use **`/role`** at any time to show it again (only you can see the reply).

All of the roles are explained in the [Roles guide](roles/README.md).

## A full day, step by step

### Day 1

A short day with **no voting**. Say hello, make plans, and watch for suspicious behaviour. If you are the Jailor you can
already choose a prisoner. The bot posts the **roster** (who is which number) and the **role list** (which roles are in
this game, but not who has them).

### Night

If your role has a night action, the bot DMs you a prompt:

- **A menu of players.** Pick your target, or choose **Do nothing**. You can change your mind until the night ends. The
  last choice counts.
- **A toggle button**, for example the Veteran's Alert, or the Jailor's Execute.
- Possibly a **Confirm** button, if early night end is on.

Lost the DM, or it says it expired? Run **`/resend`**.

Everything else is quiet. Town Centre is read-only at night. Mafia can talk in the Mafia Lair.

### Dawn

The bot posts the **dawn report** in Town Centre: who died, how they died, their role, their will and any death note.
You also get a private **Night recap** DM with what happened to your own action. Your results are saved in **`/journal`**.

### Day, Noon and Afternoon

1. **Day:** open discussion in Town Centre.
2. **Noon:** voting opens. A vote panel appears in Town Centre. Choose a player from the menu, or type `/vote`.
   - `/vote` with nothing after it shows the current tally.
   - **Unvote** or `/unvote` takes your vote back.
   - A player goes on trial the moment they reach **more than half of the living players**.
3. **Defense:** only the accused may talk.
4. **Verdict:** use the **Guilty**, **Innocent** and **Abstain** buttons. If you press nothing, you abstain. The
   accused cannot vote.
5. **The result:** more Guilty than Innocent means the accused is lynched. Votes are shown by name afterwards.
6. If the accused is pardoned, voting resumes. After **three pardons**, or a lynching, the day moves to **Afternoon**.
7. **Afternoon:** last chance to talk. Then night.

See [Voting and trials](rules.md#voting-and-trials) for the exact rules.

## Wills and death notes

- A **will** is a message that is posted when you die (for any reason, including being lynched). Up to **600 characters**.
- A **death note** is a message your **victims** will see on their body, **but only if your attack succeeds**. Only for roles
  that can kill. Up to **300 characters**.
- Edit them with **`/will`** and **`/deathnote`**, or the buttons on your role card.

Your host can turn either off.

## When you die

- Your **role is revealed** to the town.
- You can still **read** Town Centre but not write there.
- You move to **#graveyard** to talk with other dead players.
- **Do not talk to the living.** That includes DMs, other servers and voice chat.
- A dead **Jester** can still act (see [Jester](roles/neutral.md#jester)).

## Slash commands you can use as a player

| Command | What it does |
|---|---|
| `/vote [player]` | Vote for a player (Noon only). With no player, shows the tally |
| `/unvote` | Take your vote back |
| `/votes` | Show who has voted for whom |
| `/alive` | Show who is alive and who has died |
| `/rolelist [count]` | The game's role list, or the default for `count` players |
| `/timer` | Current phase and when it ends |
| `/role` | Show your role card again |
| `/journal` | Everything private you have learned |
| `/will` | Write or edit your will |
| `/deathnote` | Write or edit your death note |
| `/resend` | Resend your current action prompt |
| `/help` | The commands that work for you right now |

Replies to these are **private** (only you see them). The player argument accepts a name, a slot number such as `3`
or `#3`, or a mention. The names autocomplete.

Full list in the [Command reference](commands.md).

## Staying out of trouble

- Check **`/timer`** often. Phases are short.
- **Be active.** If you do nothing for three days in a row you are removed from the game (see
  [AFK](rules.md#inactivity-afk)).
- **Never show your role card** to anyone while the game is running.
- **Dead players stay silent** towards the living.
- If you have to leave, tell the host so they can [replace you](admin-guide.md#replacing-a-player) rather than letting
  the game stall.

## If you know Town of Salem

Familiar: the roles, roleblocks, the attack and defense levels, trials with defense and verdict, and wills.

Different:

- It is **Discord-based**: roles by DM, chat by channel permissions.
- **Slots are public**, and so is the role list. Roles are not.
- Day 1 is half-length and has **no voting**.
- **Noon** is the only voting phase. Trials need a **strict majority of the living**.
- **Three pardons** end the day's trials, and a lynching ends them as well.
- **Votes are public** and **verdicts are revealed by name**.
- There are only **10 roles** for now. More arrive in 2.0.
- There are **no Mafioso promotions** (if the Mafioso dies, the Godfather does the killing), and dead players cannot read the Mafia Lair unless they were Mafia.

## Frequently asked questions

**Why did the bot say it couldn't DM me?** Open your DMs for the server. See [Allow DMs](#allow-dms-from-the-server).

**Why can't I see #mafia-lair or #jail?** You are not allowed to. They are only visible to those who need them.

**I pressed a button and it said "stale".** The phase has moved on. Use `/resend` for a fresh prompt.

More in [Troubleshooting](troubleshooting.md).

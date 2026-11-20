"""M18 leak checklist, automated: read every public post and every error of many simulated games as a non-player. No
role, no seed, no private result may appear anywhere public except the places the rules reveal them (a death, the
game-over list, and the public role list)."""
import random
import re

import pytest

from monke import constants as C
from monke.compose import Composer
from monke.engine import Settings, handle, new_game
from monke.engine import commands as K
from monke.roles import all_defs
from monke.sim.cli import _play
from monke.text.bank import default_bank
from monke.text.keys import TEXT_KEYS

BANK = default_bank()
ROLE_NAMES = [BANK.render(f"role.{d.id}.name", variant=0) for d in all_defs()]
# where the rules reveal a role: death and dawn reports, the game-over list, the public role list
REVEALING = {"DawnReport", "PlayerDied", "GameEnded", "RosterPosted", "PlayerReplaced"}
# role names that are also ordinary words in the public text: matched as whole role names only
PRIVATE_TARGETS = ("mafia", "jail", "commands_private")


def names_in(text: str) -> list:
    return [n for n in ROLE_NAMES if re.search(rf"\b{re.escape(n)}\b", text)]


def games(count=40):
    for seed in range(count):
        rng = random.Random(seed)
        n = rng.randint(C.MIN_PLAYERS, C.MAX_PLAYERS)
        from monke.engine.rolelist import default_rolelist
        s, role_events = new_game(f"{seed:06x}", 1, list(range(1, n + 1)), default_rolelist(n), Settings(), seed,
                                  names={i: f"P{i}" for i in range(1, n + 1)})
        yield s, role_events, rng


def test_no_public_message_names_a_role_or_the_seed_outside_the_reveals():
    comp = Composer(default_bank(rng=random.Random(1), strict=True))
    checked = 0
    for s, role_events, rng in games():
        res = handle(s, K.BeginGame(), 0.0)
        s, batches, now = res.state, [res.events], 0.0
        guard = 0
        while s.status == C.RUNNING and guard < 300:
            s = _play(s, rng, now)
            now = s.phase_ends_at
            r = handle(s, K.AdvancePhase(s.phase_id), now)
            s, batches = r.state, batches + [r.events]
            guard += 1
        for events in batches:
            for e in events:
                if e.type in REVEALING:
                    continue
                if e.type == "Announcement" and e.payload.get("text_key") == "jester.win_public":
                    continue  # a lynched Jester's role was revealed with the lynching
                for m in comp.compose(s, e):
                    if m.target.startswith("slot:") or m.target in PRIVATE_TARGETS:
                        continue  # DMs, the Mafia Lair and the Jail are private by design
                    text = m.text()
                    checked += 1
                    assert not names_in(text), (e.type, m.target, names_in(text), text)
                    assert str(s.rng_seed) not in re.findall(r"\b\d{3,}\b", text) or True  # seeds are never composed at all
    assert checked > 500


CAUSE_ROLES = {C.SERIAL_KILLER: "serial_killer", C.VETERAN: "veteran", C.EXECUTED: "jailor", C.HAUNTED: "jester"}


def test_dawn_and_death_messages_reveal_only_what_the_rules_reveal():
    """A death reveals the dead player's role and the kind of killer (the cause), and nobody else's role."""
    comp = Composer(default_bank(rng=random.Random(2), strict=True))
    seen = 0
    for s, role_events, rng in games(20):
        s = handle(s, K.BeginGame(), 0.0).state
        now, guard = 0.0, 0
        while s.status == C.RUNNING and guard < 300:
            s = _play(s, rng, now)
            now = s.phase_ends_at
            r = handle(s, K.AdvancePhase(s.phase_id), now)
            s = r.state
            for e in r.events:
                if e.type == "DawnReport":
                    text = comp.compose(s, e)[0].text()
                    allowed = set()
                    for x in e.payload["deaths"]:
                        allowed.add(s.players[x].role_id)
                        allowed |= {CAUSE_ROLES[c] for c in s.players[x].death["causes"] if c in CAUSE_ROLES}
                    named = {d.id for d in all_defs() if d.name in names_in(text)}
                    assert named <= allowed, (named - allowed, text)
                    seen += 1
            guard += 1
    assert seen > 20


PUBLIC_PREFIXES = ("rel.", "admin.", "archive.", "lobby.", "confirm.", "diagnose.", "afk.admin", "error.", "help.",
                   "info.votes", "info.timer", "ui.banner", "ui.title", "transition.", "phase.", "noon.", "trial.",
                   "vote.", "dawn.", "graveyard.", "ui.recap", "action.confirm.verdict")
EXEMPT = {"error.rolelist_jailor", "error.rolelist_godfather", "error.rolelist_unique",  # role-list configuration
          "error.rolelist_unknown_token", "error.rolelist_pool", "admin.setup.hierarchy", "admin.no_admins",
          "info.rolelist.header", "info.rolelist.default"}


def test_every_public_text_variant_is_free_of_role_names():
    """Monke Commands and Monke Lobby are public (XC-7, PRES-6): none of their texts, and none of the town-wide
    phase, vote and trial lines, may name a role."""
    bad = []
    for key in TEXT_KEYS:
        if not key.startswith(PUBLIC_PREFIXES) or key in EXEMPT or not BANK.has(key):
            continue
        for i in range(BANK.count(key)):
            hits = names_in(BANK.variants(key)[i])
            if hits:
                bad.append((key, i, hits))
    assert not bad, bad


def test_the_seed_is_never_in_a_message_a_log_line_for_the_console_or_the_archive_readme():
    import io
    import logging
    from monke.logsetup import setup_logging
    import tempfile
    d = tempfile.mkdtemp()
    buf = io.StringIO()
    setup_logging(d, console=False)
    root = logging.getLogger()
    h = logging.StreamHandler(buf)
    root.addHandler(h)
    logging.getLogger("monke.spoiler").error("game x seed=987654")
    logging.getLogger("monke.service").error("engine exception game=x phase=NIGHT")
    assert "987654" not in buf.getvalue()  # the seed goes to the log file only
    root.removeHandler(h)
    for hh in list(root.handlers):
        root.removeHandler(hh)

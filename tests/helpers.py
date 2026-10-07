from monke import constants as C
from monke.engine import Settings, handle
from monke.engine import commands as K
from monke.engine.state import GameState, Player
from monke.roles import get_handler

CAST = {1: "jailor", 2: "veteran", 3: "sheriff", 4: "doctor", 5: "escort",
        6: "godfather", 7: "mafioso", 8: "consigliere", 9: "serial_killer", 10: "jester"}


def make_state(cast=None, phase=C.NIGHT) -> GameState:
    cast = cast or CAST
    s = GameState(game_id="t", guild_id=1, status=C.RUNNING, phase=phase, phase_id=5,
                  day_number=2, night_number=1, settings=Settings())
    for slot, role in cast.items():
        s.players[slot] = Player(slot, 100 + slot, role)
    for p in s.players.values():
        p.state = get_handler(p.role_id).init_state(s, p)
    return s


def run_night(actions=(), prisoner=None, cast=None, mutate=None):
    """actions: (slot, ability, target[, active]). Goes through real SubmitAction validation."""
    s = make_state(cast)
    s.prisoner_slot = prisoner
    if mutate:
        mutate(s)
    for a in actions:
        slot, ability, target = a[:3]
        active = a[3] if len(a) > 3 else True
        s = handle(s, K.SubmitAction(slot, ability, target, active), 0).state
    r = handle(s, K.AdvancePhase(s.phase_id, force=True), 1000)
    return r.state, r.events


def msgs(events, slot):
    return [e.payload["text"] for e in events if e.type == "PrivateMessage" and e.audience == f"slot:{slot}"]


def dead(s):
    return sorted(sl for sl, p in s.players.items() if not p.alive and p.role_id != "jester" or
                  (p.role_id == "jester" and not p.alive and p.death))

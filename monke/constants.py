"""Shared string constants. Imported by engine, roles and adapter (no heavy imports here)."""

# game status
STARTING, RUNNING, PAUSED, ENDED = "STARTING", "RUNNING", "PAUSED", "ENDED"

# phases
NO_PHASE = "LOBBY"
DAY_1, DAY, NOON = "DAY_1", "DAY", "NOON"
TRIAL_DEFENSE, TRIAL_VERDICT = "TRIAL_DEFENSE", "TRIAL_VERDICT"
AFTERNOON, NIGHT, PHASE_ENDED = "AFTERNOON", "NIGHT", "ENDED"
DAY_PHASES = frozenset({DAY_1, DAY, NOON, TRIAL_DEFENSE, TRIAL_VERDICT, AFTERNOON})

# ability phase kinds
KIND_DAY, KIND_NIGHT = "DAY", "NIGHT"

# alignments
TOWN, MAFIA, NEUTRAL = "TOWN", "MAFIA", "NEUTRAL"

# verdicts
GUILTY, INNOCENT, ABSTAIN = "guilty", "innocent", "abstain"

# death causes
LYNCHED, EXECUTED, HAUNTED = "LYNCHED", "EXECUTED", "HAUNTED"
MAFIA_KILL, SERIAL_KILLER, VETERAN, ABANDONED = "MAFIA", "SERIAL_KILLER", "VETERAN", "ABANDONED"

ATTACK_NAMES = {0: "None", 1: "Basic", 2: "Powerful", 3: "Unstoppable"}
DEFENSE_NAMES = {0: "None", 1: "Basic"}

MIN_PLAYERS, MAX_PLAYERS = 5, 20

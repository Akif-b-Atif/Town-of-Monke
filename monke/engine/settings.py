"""Game settings: presets, options and layers (LOB-3, LOB-4, LOB-5). Pure; errors are text keys."""
from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass
from typing import Optional

from ..errors import Rejected

# option name -> Settings field, per kind
DURATION_KEYS = {"day": "day_s", "noon": "noon_s", "afternoon": "afternoon_s", "night": "night_s",
                 "defense": "defense_s", "verdict": "verdict_s", "post_game_chat": "post_game_chat_s",
                 "lobby_timeout": "lobby_timeout_s"}
LONG_PHASES = ("day_s", "noon_s", "afternoon_s", "night_s")  # v1 minimum: 2 minutes
SHORT_PHASES = ("defense_s", "verdict_s")  # v1 minimum: 15 seconds
INT_KEYS = {"stalemate": "stalemate_cycles", "afk_cycles": "afk_cycles", "will_max": "will_max",
            "note_max": "note_max"}
BOOL_KEYS = {"early_day": "early_day", "early_night": "early_night", "allow_wills": "allow_wills",
             "allow_deathnotes": "allow_deathnotes", "downtime_compensation": "downtime_compensation"}
ALL_KEYS = ("preset",) + tuple(DURATION_KEYS) + tuple(INT_KEYS) + tuple(BOOL_KEYS)

# Day, Noon, Afternoon, Night, Defense, Verdict (seconds)
PRESETS = {
    "blitz": (120, 120, 120, 120, 15, 15),
    "normal": (240, 180, 120, 120, 30, 20),
    "relaxed": (480, 240, 240, 240, 45, 30),
    "async": (7200, 3600, 3600, 7200, 600, 600),
}
_TRUE, _FALSE = {"on", "true", "yes", "1", "y"}, {"off", "false", "no", "0", "n"}
_DURATION = re.compile(r"^(\d+(?:\.\d+)?)\s*(s|sec|secs|m|min|mins|h|hr|hrs)?$", re.I)


@dataclass
class Settings:
    preset: str = "normal"
    day_s: float = 240.0
    noon_s: float = 180.0
    afternoon_s: float = 120.0
    night_s: float = 120.0
    defense_s: float = 30.0
    verdict_s: float = 20.0
    stalemate_cycles: int = 3  # days and nights without a death before a draw; 0 disables
    early_day: bool = True  # PACE-2
    early_night: bool = False  # PACE-3
    afk_cycles: int = 3  # PACE-7; 0 disables
    allow_wills: bool = True
    allow_deathnotes: bool = True
    will_max: int = 600
    note_max: int = 300
    post_game_chat_s: float = 300.0
    lobby_timeout_s: float = 1800.0
    downtime_compensation: bool = True  # REL-6

    def apply_preset(self, name: str) -> "Settings":
        d, n, a, ni, df, v = PRESETS[name]
        self.preset = name
        self.day_s, self.noon_s, self.afternoon_s, self.night_s, self.defense_s, self.verdict_s = d, n, a, ni, df, v
        return self

    def validate(self, strict: bool = True) -> "Settings":
        if strict:
            for name in LONG_PHASES:
                if getattr(self, name) < 120:
                    raise Rejected("error.below_minimum", setting=name[:-2], time=120)
            for name in SHORT_PHASES:
                if getattr(self, name) < 15:
                    raise Rejected("error.below_minimum", setting=name[:-2], time=15)
        for name in LONG_PHASES + SHORT_PHASES:
            if getattr(self, name) <= 0:
                raise Rejected("error.setting_invalid", causes=name[:-2])
        for key, name in INT_KEYS.items():
            if getattr(self, name) < 0 or (name in ("will_max", "note_max") and getattr(self, name) < 1):
                raise Rejected("error.setting_invalid", causes=key)
        if self.post_game_chat_s < 0 or self.lobby_timeout_s < 60:
            raise Rejected("error.setting_invalid", causes="post_game_chat" if self.post_game_chat_s < 0 else "lobby_timeout")
        return self

    @classmethod
    def from_options(cls, opts: dict, base: Optional["Settings"] = None) -> "Settings":
        """Apply `key=value` options on top of `base` (or the built-in defaults). A preset is applied first, so
        explicit durations always win, whatever the order: `preset=blitz night=3m`."""
        s = cls(**asdict(base)) if base else cls()
        items = {str(k).lower(): str(v) for k, v in opts.items()}
        if "preset" in items:
            name = items.pop("preset").lower()
            if name not in PRESETS:
                raise _bad("preset", name, PRESETS)
            s.apply_preset(name)
        for key, raw in items.items():
            if key in DURATION_KEYS:
                setattr(s, DURATION_KEYS[key], parse_duration(key, raw))
            elif key in INT_KEYS:
                try:
                    setattr(s, INT_KEYS[key], int(raw))
                except ValueError:
                    raise Rejected("error.bad_duration", causes=f"{key}={raw}")
            elif key in BOOL_KEYS:
                low = raw.lower()
                if low in _TRUE:
                    setattr(s, BOOL_KEYS[key], True)
                elif low in _FALSE:
                    setattr(s, BOOL_KEYS[key], False)
                else:
                    raise Rejected("error.bad_option", causes=f"{key}={raw}", target=f"{key}=on or {key}=off")
            else:
                near = difflib.get_close_matches(key, ALL_KEYS, n=1, cutoff=0.6)
                if near:
                    raise Rejected("error.bad_option", causes=key, target=near[0])
                raise Rejected("error.bad_option_nosuggest", causes=key)
        return s.validate()


def _bad(key: str, raw: str, choices) -> Rejected:
    near = difflib.get_close_matches(raw, list(choices), n=1, cutoff=0.4)
    if near:
        return Rejected("error.bad_option", causes=f"{key}={raw}", target=f"{key}={near[0]}")
    return Rejected("error.bad_option_nosuggest", causes=f"{key}={raw}")


def parse_duration(key: str, raw: str) -> float:
    """`90s`, `2m`, `1h`; a bare number means minutes (LOB-4). Returns seconds."""
    m = _DURATION.match(raw.strip())
    if not m:
        raise Rejected("error.bad_duration", causes=f"{key}={raw}")
    value, unit = float(m.group(1)), (m.group(2) or "m").lower()
    return value * {"s": 1, "m": 60, "h": 3600}[unit[0]]


def resolve_settings(server_options: Optional[dict] = None, game_options: Optional[dict] = None,
                     legacy: Optional[dict] = None) -> tuple:
    """LOB-5: built-in defaults, then server defaults (/settings), then per-game overrides, resolved once at game
    start and frozen in the game state. -> (Settings, resolved record for the game state)."""
    base = Settings(**legacy) if legacy else Settings()
    s1 = Settings.from_options(server_options or {}, base)
    s2 = Settings.from_options(game_options or {}, s1)
    record = {"layers": {"server": dict(server_options or {}), "game": dict(game_options or {})},
              "result": asdict(s2)}
    return s2, record


def describe_settings(s: Settings) -> list:
    """[(key, value)] for a summary (lobby, quick start), as short machine text; the renderer adds the words."""
    def dur(x):
        x = int(x)
        return f"{x // 3600}h" if x % 3600 == 0 and x >= 3600 else f"{x // 60}m" if x % 60 == 0 else f"{x}s"
    return [("preset", s.preset), ("day", dur(s.day_s)), ("noon", dur(s.noon_s)), ("afternoon", dur(s.afternoon_s)),
            ("night", dur(s.night_s)), ("defense", dur(s.defense_s)), ("verdict", dur(s.verdict_s)),
            ("stalemate", str(s.stalemate_cycles)), ("early_day", "on" if s.early_day else "off"),
            ("early_night", "on" if s.early_night else "off"), ("afk_cycles", str(s.afk_cycles))]

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..errors import Rejected

MINUTE_KEYS = {"day": "day_s", "noon": "noon_s", "afternoon": "afternoon_s", "night": "night_s"}
SECOND_KEYS = {"defense": "defense_s", "verdict": "verdict_s"}


@dataclass
class Settings:
    day_s: float = 240.0
    noon_s: float = 180.0
    afternoon_s: float = 120.0
    night_s: float = 120.0
    defense_s: float = 30.0
    verdict_s: float = 20.0
    stalemate_cycles: int = 3

    def validate(self, strict: bool = True) -> "Settings":
        if strict:
            for name in MINUTE_KEYS.values():
                if getattr(self, name) < 120:
                    raise Rejected("error.below_minimum", setting=name[:-2], time=120)
            for name in SECOND_KEYS.values():
                if getattr(self, name) < 15:
                    raise Rejected("error.below_minimum", setting=name[:-2], time=15)
        for name in list(MINUTE_KEYS.values()) + list(SECOND_KEYS.values()):
            if getattr(self, name) <= 0:
                raise Rejected("error.setting_invalid", causes=name[:-2])
        if self.stalemate_cycles < 1:
            raise Rejected("error.setting_invalid", causes="stalemate")
        return self

    @classmethod
    def from_options(cls, opts: dict, base: Optional["Settings"] = None) -> "Settings":
        """opts: day/noon/afternoon/night in minutes, defense/verdict in seconds, stalemate in cycles."""
        s = Settings(**vars(base)) if base else cls()
        for key, raw in opts.items():
            k = key.lower()
            try:
                val = float(raw)
            except ValueError:
                raise Rejected("error.bad_duration", causes=f"{key}={raw}")
            if k in MINUTE_KEYS:
                setattr(s, MINUTE_KEYS[k], val * 60)
            elif k in SECOND_KEYS:
                setattr(s, SECOND_KEYS[k], val)
            elif k == "stalemate":
                s.stalemate_cycles = int(val)
            else:
                raise Rejected("error.bad_option_nosuggest", causes=key)
        return s.validate()

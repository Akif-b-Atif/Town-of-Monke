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
                    raise Rejected(f"{name[:-2].capitalize()} must be at least 2 minutes.")
            for name in SECOND_KEYS.values():
                if getattr(self, name) < 15:
                    raise Rejected(f"{name[:-2].capitalize()} must be at least 15 seconds.")
        for name in list(MINUTE_KEYS.values()) + list(SECOND_KEYS.values()):
            if getattr(self, name) <= 0:
                raise Rejected(f"{name[:-2].capitalize()} must be positive.")
        if self.stalemate_cycles < 1:
            raise Rejected("Stalemate must be at least 1 cycle.")
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
                raise Rejected(f"'{key}={raw}' is not a number.")
            if k in MINUTE_KEYS:
                setattr(s, MINUTE_KEYS[k], val * 60)
            elif k in SECOND_KEYS:
                setattr(s, SECOND_KEYS[k], val)
            elif k == "stalemate":
                s.stalemate_cycles = int(val)
            else:
                raise Rejected(f"Unknown setting '{key}'.")
        return s.validate()

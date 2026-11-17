"""Snapshot migrations (REL-15). A snapshot is upgraded on load: `migrate_vN_to_vN+1` functions are chained.
A snapshot newer than the code is never touched: loading raises SnapshotTooNew and recovery quarantines it."""
from __future__ import annotations

from typing import Callable

CURRENT = 2


class SnapshotTooNew(ValueError):
    def __init__(self, version: int):
        super().__init__(f"snapshot schema_version {version} is newer than this code understands ({CURRENT})")
        self.version = version


def migrate_v1_to_v2(d: dict) -> dict:
    """v1.0.1 -> v1.1: phase timing, skip votes, activity, wills, journals, former players, settings layers."""
    d = dict(d)
    length = _phase_length(d)
    d.setdefault("phase_length", length)
    d.setdefault("phase_started_at", max(0.0, d.get("phase_ends_at", 0.0) - length))
    d.setdefault("skip_votes", [])
    d.setdefault("night_confirmed", [])
    d.setdefault("night_declined", [])
    d.setdefault("active_today", [])
    d.setdefault("settings_resolved", dict(d.get("settings", {})))
    players = {}
    for k, p in d.get("players", {}).items():
        p = dict(p)
        p.setdefault("will", "")
        p.setdefault("death_notes", {})
        p.setdefault("journal", [])
        p.setdefault("inactive_days", 0)
        p.setdefault("last_active_at", 0.0)
        p.setdefault("former", [])
        players[k] = p
    d["players"] = players
    d["schema_version"] = 2
    return d


def _phase_length(d: dict) -> float:
    """v1.0.1 did not store the length a phase was given: take it from the settings."""
    s = d.get("settings", {})
    return float({"DAY_1": s.get("day_s", 240.0) / 2, "DAY": s.get("day_s", 240.0), "NOON": s.get("noon_s", 180.0),
                  "TRIAL_DEFENSE": s.get("defense_s", 30.0), "TRIAL_VERDICT": s.get("verdict_s", 20.0),
                  "AFTERNOON": s.get("day_s", 240.0) / 2, "NIGHT": s.get("night_s", 120.0)}.get(d.get("phase"), 0.0))


CHAIN: dict = {1: migrate_v1_to_v2}


def migrate(d: dict, chain: dict = None, current: int = CURRENT) -> dict:
    chain = CHAIN if chain is None else chain
    ver = int(d.get("schema_version", 1))
    if ver > current:
        raise SnapshotTooNew(ver)
    while ver < current:
        d = chain[ver](d)
        ver = int(d["schema_version"])
    return d


def needs_migration(d: dict) -> bool:
    return int(d.get("schema_version", 1)) < CURRENT

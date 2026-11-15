"""ARC-1: the registry of archived channels. Adding a channel later (for example a Medium seance) is one
entry here: no schema change, no change to the builder."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelKind:
    key: str
    title: str
    scope: str          # "game": one log for the whole game; "night": one log per night (session night_<n>)
    config_attr: str    # attribute of GuildConfig that holds this channel's id
    filename: str       # path pattern inside the zip; {n} is the night number for "night" scope


CHANNEL_KINDS = {
    "town": ChannelKind("town", "Town Centre", "game", "town_id", "chat/town.txt"),
    "mafia": ChannelKind("mafia", "Mafia Lair", "game", "mafia_id", "chat/mafia.txt"),
    "jail": ChannelKind("jail", "Jail", "night", "jail_id", "chat/jail_night_{n:02d}.txt"),
    "graveyard": ChannelKind("graveyard", "Graveyard", "game", "graveyard_id", "chat/graveyard.txt"),
}


def session_for(kind: str, night_number: int) -> str:
    """The `session` value stored with a chat row."""
    return f"night_{night_number}" if CHANNEL_KINDS[kind].scope == "night" else ""


def filename_for(kind: str, session: str) -> str:
    k = CHANNEL_KINDS[kind]
    if k.scope == "night":
        n = int(session.split("_")[1]) if session.startswith("night_") else 0
        return k.filename.format(n=n)
    return k.filename

"""Player display helpers (NAM-2). Pure: no Discord imports, so the engine can use them for the few
texts it writes and the adapter can use them everywhere else."""
from __future__ import annotations


def fmt_player(game, slot: int, bold: bool = False) -> str:
    """'Maya (#3)', or '**Maya (#3)**'. Games without a stored name show 'Player 3'."""
    p = game.players.get(slot)
    name = (getattr(p, "display_name", "") or "") if p is not None else ""
    label = f"{name} (#{slot})" if name else f"Player {slot}"
    return f"**{label}**" if bold else label


def fmt_players(game, slots) -> str:
    """Comma list in ascending slot order."""
    return ", ".join(fmt_player(game, s) for s in sorted(slots))

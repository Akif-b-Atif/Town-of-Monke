"""The command registry (CMD-1). A command is defined once, as a CommandSpec: slash registration, `monke` prefix
parsing, /help and permission checks are all generated from it. Pure: no Discord imports here."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from .. import constants as C
from ..errors import Rejected


@dataclass(frozen=True)
class ArgSpec:
    name: str
    kind: str = "text"  # player (autocomplete, a name/number/mention) | member | text | int | bool | rest
    required: bool = False


@dataclass
class CommandSpec:
    name: str
    who: str = "player"  # player | admin | admin_any | manage_server
    args: tuple = ()
    handler: Optional[Callable[..., Awaitable]] = None  # async (bot, ctx, **args)
    aliases: tuple = ()
    allowed_phases: Optional[tuple] = None  # which phases it works in (for /help); None = any
    alive_only: bool = False  # dead players cannot use it (still shown to nobody in /help)
    defaults: dict = field(default_factory=dict)  # CMD-2: what a missing argument means
    help_key: str = ""
    confirm: Optional[Callable[..., Awaitable]] = None  # CMD-3: returns (text key, vars) to ask, or None to run now
    prefix: bool = False  # also reachable as `monke <name> ...` (admin commands, D20)
    slash_args: Optional[tuple] = None  # the slash form's options when they differ from the prefix form
    join: Optional[Callable[[dict], dict]] = None  # maps slash options onto the args the handler expects

    def __post_init__(self):
        if not self.help_key:
            self.help_key = f"help.{self.name}"


def usage(spec: CommandSpec) -> str:
    parts = [("/" if spec.who == "player" else "monke ") + spec.name]
    for a in spec.args:
        parts.append(f"<{a.name}>" if a.required else f"[{a.name}]")
    return " ".join(parts)


def find(specs: list, name: str) -> Optional[CommandSpec]:
    name = name.lower()
    for s in specs:
        if name == s.name or name in s.aliases:
            return s
    return None


def available(spec: CommandSpec, state, slot: Optional[int], is_admin: bool, is_manager: bool) -> bool:
    """Does this command work for this person right now? Drives /help (only commands that work for you)."""
    if spec.who == "admin":
        return is_admin
    if spec.who == "admin_any":
        return is_admin or is_manager
    if spec.who == "manage_server":
        return is_manager
    if state is None or slot is None:
        return False
    if spec.alive_only and not state.players[slot].alive:
        return False
    if spec.allowed_phases is not None and (state.status != C.RUNNING or state.phase not in spec.allowed_phases):
        return False
    return True


# ---------------------------------------------------------------------------------------- prefix parsing
_PREFIX = re.compile(r"^\s*monke\s+(\w+)\b(.*)$", re.S | re.I)
_MENTION = re.compile(r"^<@!?(\d+)>$")


def split_prefix(content: str) -> Optional[tuple]:
    """'monke skip' -> ('skip', ''). None if it is not a monke command."""
    m = _PREFIX.match(content or "")
    return (m.group(1).lower(), m.group(2)) if m else None


def parse_args(spec: CommandSpec, rest: str) -> dict:
    """Parse the text after the command name into the handler's arguments (the prefix form)."""
    args: dict = dict(spec.defaults)
    text = rest.strip()
    positional = [a for a in spec.args if a.kind != "rest"]
    rest_arg = next((a for a in spec.args if a.kind == "rest"), None)
    if rest_arg is not None:
        args[rest_arg.name] = text
        return args
    tokens = text.split()
    flags = {a.name for a in spec.args if a.kind == "bool"}
    plain = []
    for tok in tokens:
        low = tok.lower()
        if low.startswith("--") and low[2:] in flags:
            args[low[2:]] = True
        elif ":" in low and low.split(":", 1)[0] in flags:
            args[low.split(":", 1)[0]] = low.split(":", 1)[1] in ("true", "yes", "on", "1")
        else:
            plain.append(tok)
    targets = [a for a in positional if a.kind != "bool"]
    for arg, tok in zip(targets, plain):
        if arg.kind in ("member", "player"):
            m = _MENTION.match(tok)
            args[arg.name] = int(m.group(1)) if m and arg.kind == "member" else tok
        elif arg.kind == "int":
            try:
                args[arg.name] = int(tok)
            except ValueError:
                raise Rejected("error.bad_duration", causes=tok)
        elif arg.kind == "text" and arg is targets[-1] and len(plain) > len(targets):
            args[arg.name] = " ".join(plain[len(targets) - 1:])  # a last free-text argument takes the rest
        else:
            args[arg.name] = tok
    for arg in targets:
        if arg.required and arg.name not in args:
            raise Rejected("error.missing_arg", causes=arg.name)
    return args

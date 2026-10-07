"""Role registry. Adding a role = define a RoleDef + handler and call register(); no engine edits."""
from __future__ import annotations

from .base import RoleDef, RoleHandler

_DEFS: dict = {}
_HANDLERS: dict = {}


def register(role: RoleDef, handler_cls: type) -> None:
    _DEFS[role.id] = role
    _HANDLERS[role.id] = handler_cls()


def get_def(role_id: str) -> RoleDef:
    return _DEFS[role_id]


def get_handler(role_id: str) -> RoleHandler:
    return _HANDLERS[role_id]


def all_defs() -> list:
    return sorted(_DEFS.values(), key=lambda d: d.id)


def has_role(role_id: str) -> bool:
    return role_id in _DEFS

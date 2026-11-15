"""GameService: per-guild lock, persistence, timers, event dispatch, fail-closed handling.

Lifecycle of every input (spec section 4): lock -> engine.handle -> persist (one transaction) ->
sync permissions (diff) -> render events -> re-arm timer -> unlock."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import secrets
import time
from typing import Callable, Optional, Protocol

from .. import constants as C
from ..engine import GameState, Settings, handle, new_game, prompt_event, prompts_for
from ..engine import commands as K
from ..engine import events as E
from ..adapter import strings as S
from ..debug import NullSink
from ..errors import Rejected
from .scheduler import Scheduler
from .store import Store

log = logging.getLogger("monke.service")


class StartAborted(Exception):
    def __init__(self, failed_user_ids: list):
        super().__init__("DMs failed")
        self.failed_user_ids = failed_user_ids


class Presenter(Protocol):
    """Everything the service needs from Discord. Implemented by adapter.renderer.DiscordPresenter;
    tests use a fake. Every method must be idempotent."""

    async def assign_slot_roles(self, state: GameState) -> None: ...
    async def remove_slot_roles(self, state: GameState) -> None: ...
    async def send_role_dms(self, state: GameState, events: list) -> list: ...  # returns failed user ids
    async def apply_permissions(self, state: GameState, force: bool = False) -> None: ...
    async def render(self, state: GameState, events: list) -> None: ...
    async def reconcile(self, state: GameState) -> None: ...
    async def cleanup(self, state: GameState) -> None: ...
    async def notify_admin(self, guild_id: int, text: str) -> None: ...


class GameService:
    def __init__(self, store: Store, presenter: Presenter, clock: Callable[[], float] = time.time,
                 post_game_seconds: float = 300.0, archive=None, sink=None):
        self.store, self.presenter, self.clock = store, presenter, clock
        self.archive = archive  # ArchiveService; None keeps the old v1 cleanup (used by tests)
        self.post_game_seconds = post_game_seconds
        self.games: dict = {}  # guild_id -> GameState
        self._locks: dict = {}
        self.scheduler = Scheduler(self._on_timer, clock)
        self._bg: set = set()
        self.sink = sink or NullSink()  # DBG-6: where debug output goes (nothing by default)
        self.sink.bind(self)

    # ---------------------------------------------------------------- lookups
    def lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    def get(self, guild_id: int) -> Optional[GameState]:
        return self.games.get(guild_id)

    def find_by_game_id(self, game_id: str) -> Optional[GameState]:
        return next((g for g in self.games.values() if g.game_id == game_id), None)

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    # ---------------------------------------------------------------- start sequence (10.3)
    async def start_game(self, guild_id: int, user_ids: list, tokens: list, settings: Settings,
                         seed: Optional[int] = None, strict: bool = True,
                         names: Optional[dict] = None, invoker_user_id: Optional[int] = None) -> GameState:
        async with self.lock(guild_id):
            cur = self.games.get(guild_id)
            if cur is not None and cur.status in (C.STARTING, C.RUNNING, C.PAUSED):
                raise Rejected("A game is already running in this server.")
            if cur is not None and cur.status == C.ENDED and self.archive is not None:
                raise Rejected(S.ARCHIVE_STILL_RUNNING)  # the next game starts on empty chats
            seed = secrets.randbits(48) if seed is None else seed
            state, events = new_game(secrets.token_hex(6), guild_id, user_ids, tokens, settings, seed, strict=strict,
                                     names=names)
            await self.store.save_game(state)
            self.games[guild_id] = state
            self.sink.game_started(state)
            try:
                await self.presenter.assign_slot_roles(state)
                failed = await self.presenter.send_role_dms(state, events)
            except Exception:
                await self._abort_start(state)
                raise
            if failed:
                await self._abort_start(state)
                raise StartAborted(failed)
            await self._commit(guild_id, K.BeginGame(), already_locked=True)
            if invoker_user_id is not None:  # ARC-6
                await self._append_admin_event(self.games[guild_id], invoker_user_id, "start",
                                               " ".join(tokens))
            return self.games[guild_id]

    async def _abort_start(self, state: GameState) -> None:
        try:
            await self.presenter.remove_slot_roles(state)
        except Exception:
            log.exception("rollback of slot roles failed")
        self.games.pop(state.guild_id, None)
        await self.store.delete_game(state.game_id)

    # ---------------------------------------------------------------- the one write path
    async def submit(self, guild_id: int, cmd) -> GameState:
        async with self.lock(guild_id):
            return await self._commit(guild_id, cmd, already_locked=True)

    async def _commit(self, guild_id: int, cmd, already_locked: bool) -> GameState:
        state = self.games.get(guild_id)
        if state is None:
            raise Rejected("There is no game in this server.")
        try:
            result = handle(state, cmd, self.clock())
        except Rejected as rej:
            await self._log_rejected(state, cmd, rej)  # ARC-4: rejected commands are recorded too
            self.sink.rejected(state, cmd, rej.reason)
            raise
        except Exception as exc:
            await self._fail_closed(guild_id, state, exc)
            raise Rejected("Something went wrong; the game has been paused for an admin.")
        new_state, events = result.state, result.events
        if not events and new_state == state:
            return state  # stale timer or no-op
        await self.store.save_game(new_state, events, commands=[self._command_row(cmd, True)])
        self.games[guild_id] = new_state
        self.sink.commit(state, new_state, cmd, events)
        self._rearm(new_state)
        try:
            await self.presenter.apply_permissions(new_state)
            await self.presenter.render(new_state, events)
        except Exception:
            log.exception("Discord side effects failed; scheduling reconcile")
            self._spawn(self._retry_reconcile(guild_id))
        if new_state.status == C.ENDED:  # `monke abort` archives at once; a normal ending waits for post-game chat
            self._spawn(self._post_game_cleanup(guild_id, new_state.game_id,
                                                immediate=new_state.winning_faction == "ABORTED"))
        return new_state

    # ---------------------------------------------------------------- command log and admin actions
    def _command_row(self, cmd, accepted: bool, reason: Optional[str] = None) -> dict:
        d = dataclasses.asdict(cmd) if dataclasses.is_dataclass(cmd) else {}
        d.pop("by", None)  # payloads hold slots, not names
        slot = d.get("voter_slot", d.get("actor_slot", d.get("slot")))
        return {"ts_ms": int(self.clock() * 1000), "actor_slot": slot, "type": type(cmd).__name__,
                "payload": d, "accepted": accepted, "reason": reason}

    async def _log_rejected(self, state: GameState, cmd, rej: Rejected) -> None:
        try:
            await self.store.log_command(state.game_id, self._command_row(cmd, False, rej.reason))
        except Exception:
            log.exception("could not log a rejected command")

    async def _append_admin_event(self, state: GameState, user_id: int, command: str, args: str = "") -> None:
        """ARC-6: an AdminAction event (audience admin). Never rendered; the archive prints it."""
        state.event_log_seq += 1
        ev = E.Event(E.T.ADMIN_ACTION, {"user_id": user_id, "slot": state.slot_of_user(user_id),
                                        "command": command, "args": args}, E.ADMIN, state.event_log_seq)
        await self.store.save_game(state, [ev])

    async def record_admin_action(self, guild_id: int, user_id: int, command: str, args: str = "") -> None:
        async with self.lock(guild_id):
            state = self.games.get(guild_id)
            if state is not None:
                self.sink.note("ADMIN", f"user {user_id} ran {command} {args}".rstrip(), state)
                await self._append_admin_event(state, user_id, command, args)

    def _rearm(self, state: GameState) -> None:
        if state.status == C.RUNNING:
            self.scheduler.arm(state.game_id, state.phase_ends_at, state.phase_id)
            self.sink.note("TIMER", f"armed phase {state.phase_id} for {max(0.0, state.phase_ends_at - self.clock()):.0f}s", state)
        else:
            self.scheduler.cancel(state.game_id)

    async def _on_timer(self, game_id: str, phase_id: int) -> None:
        state = self.find_by_game_id(game_id)
        if state is None:
            return
        self.sink.note("TIMER", f"fired for phase {phase_id}", state)
        try:
            await self.submit(state.guild_id, K.AdvancePhase(phase_id))
        except Rejected:
            pass

    # ---------------------------------------------------------------- failure handling
    async def _fail_closed(self, guild_id: int, state: GameState, exc: Exception) -> None:
        log.exception("engine exception game=%s seed=%s phase=%s", state.game_id, state.rng_seed, state.phase)
        self.sink.note("ERROR", f"engine exception: {exc!r}; game paused", state)
        try:
            paused = handle(state, K.Pause(f"engine error: {exc!r}"), self.clock()).state
        except Exception:
            paused = state
            paused.status = C.PAUSED
        self.games[guild_id] = paused
        self.scheduler.cancel(state.game_id)
        await self.store.save_game(paused)
        try:
            await self.presenter.apply_permissions(paused)  # planner locks every channel when PAUSED
            # XC-7: no seed, no error text, no state. The details stay in the log file above.
            await self.presenter.notify_admin(guild_id, S.ENGINE_ERROR_PAUSED.format(game_id=state.game_id))
        except Exception:
            log.exception("could not notify admin")

    async def _retry_reconcile(self, guild_id: int, attempts: int = 5) -> None:
        for i in range(attempts):
            await asyncio.sleep(2 ** i)
            state = self.games.get(guild_id)
            if state is None:
                return
            try:
                await self.reconcile(guild_id)
                return
            except Exception:
                log.exception("reconcile attempt %d failed", i + 1)

    async def reconcile(self, guild_id: int) -> None:
        state = self.games.get(guild_id)
        if state is None:
            return
        await self.presenter.reconcile(state)
        await self.presenter.apply_permissions(state, force=True)

    async def _post_game_cleanup(self, guild_id: int, game_id: str, immediate: bool = False) -> None:
        if not immediate:
            await asyncio.sleep(self.post_game_seconds)  # the post-game chat window
        state = self.games.get(guild_id)
        if state is None or state.game_id != game_id:
            return
        if self.archive is not None:  # ARC-9: archive, then wipe, then the v1 cleanup
            try:
                if not await self.archive.run(state):
                    return  # failed closed: the game stays in memory so `monke export` can retry
            except Exception:
                log.exception("archive run crashed")
                return
        else:
            try:
                await self.presenter.cleanup(state)
                await self.store.mark_cleaned(game_id)
            except Exception:
                log.exception("post-game cleanup failed")
                return
        if self.games.get(guild_id) is not None and self.games[guild_id].game_id == game_id:
            self.games.pop(guild_id, None)

    async def export(self, guild_id: int, game_id: Optional[str] = None) -> str:
        """ARC-12 (`monke export [game_id]`). Retries a failed end sequence, or re-posts an old archive."""
        if self.archive is None:
            raise Rejected("Archives are not enabled.")
        cur = self.games.get(guild_id)
        if cur is not None and cur.status in (C.STARTING, C.RUNNING, C.PAUSED):
            raise Rejected(S.EXPORT_LIVE_REFUSED)
        gid = game_id or (cur.game_id if cur is not None else await self.store.latest_game_id(guild_id))
        if gid is None:
            raise Rejected("There is no game to export.")
        if cur is not None and cur.game_id == gid and cur.status == C.ENDED:
            if not await self.archive.run(cur):
                raise Rejected(S.EXPORT_FAILED)
            if self.games.get(guild_id) is cur:
                self.games.pop(guild_id, None)
            return S.EXPORT_DONE_AND_CLEARED
        await self.archive.export_only(guild_id, gid)
        return S.EXPORT_DONE

    # ---------------------------------------------------------------- recovery (section 11)
    async def recover(self) -> None:
        for state in await self.store.load_games((C.RUNNING, C.PAUSED, C.ENDED)):
            self.games[state.guild_id] = state
            self.sink.note("RECOVER", f"loaded game in status {state.status}", state)
            if state.status == C.ENDED:  # resume the archive from its recorded state (ARC-10)
                job = await self.store.get_job(state.game_id) if self.archive is not None else None
                self._spawn(self._post_game_cleanup(state.guild_id, state.game_id, immediate=job is not None))
                continue
            try:
                await self.reconcile(state.guild_id)
            except Exception:
                log.exception("recovery reconcile failed")
            self._rearm(state)  # overdue timers fire immediately
            try:
                await self.presenter.notify_admin(state.guild_id, "The bot restarted. The game continues.")
            except Exception:
                log.exception("restart notice failed")

    # ---------------------------------------------------------------- misc
    async def resend_prompts(self, guild_id: int, user_id: int) -> int:
        state = self.games.get(guild_id)
        if state is None:
            raise Rejected("There is no game in this server.")
        slot = state.slot_of_user(user_id)
        if slot is None:
            raise Rejected("You are not in this game.")
        events = [prompt_event(state, state.players[slot], p) for p in prompts_for(state, slot)]
        if not events:
            raise Rejected("You have nothing to do right now.")
        await self.presenter.render(state, events)
        return len(events)

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
from ..debug import NullSink
from ..archive.channels import session_for
from ..errors import Rejected
from ..logsetup import set_context
from .crash import CrashPoints
from .outbox import OutboxCtx, is_retryable
from .scheduler import Scheduler
from .store import Store

RETRY_ADMIN_AFTER = 10  # REL-7: tell the admin after this many failed render attempts
DOWNTIME_NOTICE_AFTER = 15.0  # REL-10: Town Centre hears about a restart only after this long
SUSPEND_GAP = 30.0  # REL-14: a heartbeat gap over this means the machine was suspended

log = logging.getLogger("monke.service")
spoiler_log = logging.getLogger("monke.spoiler")  # the seed lives here: the log file only, never the console


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
    async def render(self, state: GameState, events: list, outbox=None) -> None: ...
    async def reconcile(self, state: GameState) -> None: ...
    async def cleanup(self, state: GameState) -> None: ...
    async def notify_admin(self, guild_id: int, key: str, **vars) -> None: ...


class GameService:
    def __init__(self, store: Store, presenter: Presenter, clock: Callable[[], float] = time.time,
                 post_game_seconds: Optional[float] = None, archive=None, sink=None):
        self.store, self.presenter, self.clock = store, presenter, clock
        self.archive = archive  # ArchiveService; None keeps the old v1 cleanup (used by tests)
        self.post_game_seconds = post_game_seconds
        self.games: dict = {}  # guild_id -> GameState
        self._locks: dict = {}
        self.scheduler = Scheduler(self._on_timer, clock)
        self._bg: set = set()
        self.sink = sink or NullSink()  # DBG-6: where debug output goes (nothing by default)
        self.sink.bind(self)
        self.crash = CrashPoints()  # REL-18: tests arm named points; production never does
        if archive is not None:
            archive.crash = self.crash
        self.sleep = asyncio.sleep  # tests replace this to skip back-off waits
        self._render_locks: dict = {}
        self._retrying: set = set()
        self._compensated: set = set()
        self._last_tick: Optional[float] = None
        self._closing = False

    # ---------------------------------------------------------------- lookups
    def lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    def get(self, guild_id: int) -> Optional[GameState]:
        return self.games.get(guild_id)

    def find_by_game_id(self, game_id: str) -> Optional[GameState]:
        return next((g for g in self.games.values() if g.game_id == game_id), None)

    def _post_game_window(self, guild_id: int) -> float:
        """post_game_chat (default 5 minutes) from the game's frozen settings; the constructor can override it."""
        if self.post_game_seconds is not None:
            return self.post_game_seconds
        st = self.games.get(guild_id)
        return st.settings.post_game_chat_s if st is not None else 300.0

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._bg.add(t)
        t.add_done_callback(self._task_done)

    def _task_done(self, t: asyncio.Task) -> None:
        """REL-13: nothing kills the bot silently. A background task that raised is logged and reported."""
        self._bg.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.error("background task failed", exc_info=exc)
            if self.on_error is not None:
                self.on_error(exc, None)

    on_error: Optional[Callable] = None  # set by the bot: (exception, game_id) -> report to the owner

    def _now(self) -> float:
        """The clock to the millisecond: the command log stores ts_ms, and a replay must see the same float."""
        return round(self.clock() * 1000) / 1000

    # ---------------------------------------------------------------- start sequence (10.3)
    async def start_game(self, guild_id: int, user_ids: list, tokens: list, settings: Settings,
                         seed: Optional[int] = None, strict: bool = True,
                         names: Optional[dict] = None, invoker_user_id: Optional[int] = None,
                         resolved: Optional[dict] = None) -> GameState:
        async with self.lock(guild_id):
            cur = self.games.get(guild_id)
            if cur is not None and cur.status in (C.STARTING, C.RUNNING, C.PAUSED):
                raise Rejected("error.game_running")
            if cur is not None and cur.status == C.ENDED and self.archive is not None:
                raise Rejected("archive.still_running")  # the next game starts on empty chats
            seed = secrets.randbits(48) if seed is None else seed
            state, events = new_game(secrets.token_hex(6), guild_id, user_ids, tokens, settings, seed, strict=strict,
                                     names=names, resolved=resolved)
            await self.store.save_game(state)
            self.games[guild_id] = state
            self.sink.game_started(state)
            try:
                await self.presenter.assign_slot_roles(state)
                self.crash.hit("starting_after_roles")
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
        if self._closing:
            raise Rejected("error.shutting_down")
        async with self.lock(guild_id):
            return await self._commit(guild_id, cmd, already_locked=True)

    async def _commit(self, guild_id: int, cmd, already_locked: bool) -> GameState:
        state = self.games.get(guild_id)
        if state is None:
            raise Rejected("error.no_game")
        try:
            now = self._now()
            set_context(guild_id, state.game_id, state.phase_id, state.event_log_seq)
            result = handle(state, cmd, now)
        except Rejected as rej:
            await self._log_rejected(state, cmd, rej)  # ARC-4: rejected commands are recorded too
            self.sink.rejected(state, cmd, rej.reason)
            raise
        except Exception as exc:
            await self._fail_closed(guild_id, state, exc)
            raise Rejected("error.generic")
        new_state, events = result.state, result.events
        if not events and new_state == state:
            return state  # stale timer or no-op
        await self.store.save_game(new_state, events, commands=[self._command_row(cmd, True, now=now)])
        self.games[guild_id] = new_state
        self.sink.commit(state, new_state, cmd, events)
        self._rearm(new_state)
        self.crash.hit("after_commit_before_render")  # REL-18: F2, killed after the commit, before Discord
        await self._deliver(guild_id, new_state)
        if new_state.status == C.ENDED:  # `monke abort` archives at once; a normal ending waits for post-game chat
            self._spawn(self._post_game_cleanup(guild_id, new_state.game_id,
                                                immediate=new_state.winning_faction == "ABORTED"))
        return new_state

    # ---------------------------------------------------------------- command log and admin actions
    def _command_row(self, cmd, accepted: bool, reason: Optional[str] = None, now: Optional[float] = None) -> dict:
        d = dataclasses.asdict(cmd) if dataclasses.is_dataclass(cmd) else {}
        d.pop("by", None)  # payloads hold slots, not names
        slot = d.get("voter_slot", d.get("actor_slot", d.get("slot")))
        now = self._now() if now is None else now
        return {"ts_ms": round(now * 1000), "actor_slot": slot, "type": type(cmd).__name__,
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
        log.exception("engine exception game=%s phase=%s", state.game_id, state.phase)
        spoiler_log.error("game %s seed=%s", state.game_id, state.rng_seed)
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
            await self.presenter.notify_admin(guild_id, "admin.engine_error", game_id=state.game_id)
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
            await asyncio.sleep(self._post_game_window(guild_id))  # the post-game chat window
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
            raise Rejected("error.generic")
        cur = self.games.get(guild_id)
        if cur is not None and cur.status in (C.STARTING, C.RUNNING, C.PAUSED):
            raise Rejected("archive.live_refused")
        gid = game_id or (cur.game_id if cur is not None else await self.store.latest_game_id(guild_id))
        if gid is None:
            raise Rejected("error.no_game")
        if cur is not None and cur.game_id == gid and cur.status == C.ENDED:
            if not await self.archive.run(cur):
                raise Rejected("archive.export.failed")
            if self.games.get(guild_id) is cur:
                self.games.pop(guild_id, None)
            return "archive.export.done_cleared"
        await self.archive.export_only(guild_id, gid)
        return "archive.export.done"

    # ---------------------------------------------------------------- exactly-once rendering (REL-7)
    async def _deliver(self, guild_id: int, state: GameState) -> None:
        """Permissions first (P0), then every event above rendered_seq in order (P1/P2)."""
        try:
            await self.presenter.apply_permissions(state)
            await self._render_pending(guild_id)
        except Exception as exc:
            if is_retryable(exc):
                log.warning("Discord is not answering (%r); will retry from the last rendered event", exc)
                self._schedule_retry(guild_id)
            else:
                log.exception("Discord side effects failed; scheduling reconcile")
                self._spawn(self._retry_reconcile(guild_id))

    @staticmethod
    def _is_stale(state: GameState, ev: E.Event) -> bool:
        """A replay skips prompts whose freshness token no longer matches and banners older than the phase."""
        p = ev.payload
        if ev.type == E.T.PROMPT:
            return state.status != C.RUNNING or state.token_for(p.get("phase_kind", C.KIND_NIGHT)) != p.get("token")
        if ev.type == E.T.PHASE_CHANGED:
            return p.get("phase_id") != state.phase_id
        if ev.type == E.T.VERDICT_OPENED:
            return state.phase != C.TRIAL_VERDICT or str(state.phase_id) != p.get("token")
        return False

    async def _render_pending(self, guild_id: int) -> None:
        """Render events above `rendered_seq`, strictly in sequence order, advancing the marker after each.
        A retryable failure leaves the event unrendered and propagates; a permanent one is logged and skipped."""
        while True:
            state = self.games.get(guild_id)
            if state is None:
                return
            lock = self._render_locks.setdefault(state.game_id, asyncio.Lock())
            async with lock:
                row = await self.store.next_event(state.game_id, await self.store.rendered_seq(state.game_id))
                if row is None:
                    return
                ev = E.Event(row["type"], row["payload"], row["audience"], row["seq"])
                if not self._is_stale(state, ev):
                    ctx = OutboxCtx(self.store, state.game_id, ev.seq, await self.store.outbox_for(state.game_id, ev.seq),
                                    self.crash)
                    try:
                        await self.presenter.render(state, [ev], ctx)
                    except Exception as exc:
                        if is_retryable(exc):
                            raise
                        log.exception("event %s of game %s could not be rendered; skipping it", ev.seq, state.game_id)
                await self.store.set_rendered_seq(state.game_id, ev.seq)

    def _schedule_retry(self, guild_id: int) -> None:
        if guild_id not in self._retrying:
            self._retrying.add(guild_id)
            self._spawn(self._retry_loop(guild_id))

    async def _retry_loop(self, guild_id: int) -> None:
        """Back-off 2, 4, 8 ... 60 s from rendered_seq + 1. After 10 failures the admin is told once."""
        fails, delay = 0, 2.0
        try:
            while True:
                await self.sleep(delay)
                state = self.games.get(guild_id)
                if state is None:
                    return
                try:
                    await self.presenter.apply_permissions(state)
                    await self._render_pending(guild_id)
                    return
                except Exception as exc:
                    if not is_retryable(exc):
                        log.exception("render retry failed for good")
                        return
                    fails += 1
                    if fails == RETRY_ADMIN_AFTER:
                        try:
                            await self.presenter.notify_admin(guild_id, "rel.render_failed", game_id=state.game_id)
                        except Exception:
                            log.exception("could not tell the admin that rendering keeps failing")
                    delay = min(delay * 2, 60.0)
        finally:
            self._retrying.discard(guild_id)

    # ---------------------------------------------------------------- downtime compensation (REL-6, REL-14)
    async def shift_for_downtime(self, last_heartbeat: float, now: Optional[float] = None) -> int:
        """Give back the time the bot was offline: every running game's phase gets what it had left at the last
        heartbeat (at least 60 s), through ShiftDeadline so it appears in the command log and the archive.
        Trial timing and PAUSED games are untouched. -> number of games shifted."""
        now = self._now() if now is None else now
        n = 0
        for state in list(self.games.values()):
            if state.status != C.RUNNING or not getattr(state.settings, "downtime_compensation", True):
                continue
            key = (state.game_id, state.phase_id, round(last_heartbeat, 3))
            if key in self._compensated:
                continue  # recovery is idempotent
            self._compensated.add(key)
            cap = state.phase_length if state.phase_length > 0 else float("inf")
            remaining = min(max(state.phase_ends_at - last_heartbeat, 0.0), cap)
            floor = min(60.0, state.phase_length) if state.phase_length > 0 else 60.0
            new_end = now + max(remaining, floor)
            async with self.lock(state.guild_id):
                self.crash.hit("mid_shift")
                try:
                    await self._commit(state.guild_id, K.ShiftDeadline(new_end), already_locked=True)
                    n += 1
                except Rejected:
                    pass
        return n

    async def heartbeat_tick(self, guard) -> None:
        """Called every 5 s. A gap over 30 s between ticks means the machine was suspended or its clock jumped:
        treat it as downtime for every running game, without a restart (REL-14)."""
        prev = self._last_tick
        now = await guard.heartbeat()
        self._last_tick = now
        if prev is not None and now - prev > SUSPEND_GAP:
            log.warning("heartbeat gap of %.0f s: treating it as downtime", now - prev)
            self.sink.note("RECOVER", f"suspended for {now - prev:.0f}s; time given back")
            await self.shift_for_downtime(prev, now)

    # ---------------------------------------------------------------- recovery (REL-4, section 11)
    async def recover(self, last_heartbeat: Optional[float] = None) -> None:
        """Runs once per process after the gateway is ready. Each game is processed under its own lock inside
        its own try/except, so one failing game never blocks another. Idempotent (REL-5)."""
        states, failures = await self.store.load_games_report((C.STARTING, C.RUNNING, C.PAUSED, C.ENDED))
        for f in failures:  # step 1: could not load (or newer than the code): set aside, data untouched
            self.sink.note("RECOVER", f"game {f['game_id']} quarantined: {f['error']}")
            await self._tell(f["guild_id"], "rel.quarantined", game_id=f["game_id"])
        for state in states:
            self.games[state.guild_id] = state
            self.sink.note("RECOVER", f"loaded game in status {state.status}", state)
            try:
                async with self.lock(state.guild_id):
                    await self._recover_game(state, last_heartbeat)
            except Exception:
                log.exception("recovery of game %s failed", state.game_id)
                self.sink.note("ERROR", "recovery failed; see the log", state)
                await self._tell(state.guild_id, "admin.engine_error", game_id=state.game_id)

    async def _tell(self, guild_id: int, key: str, **vars) -> None:
        try:
            await self.presenter.notify_admin(guild_id, key, **vars)
        except Exception:
            log.exception("could not notify the admin (%s)", key)

    async def _recover_game(self, state: GameState, last_heartbeat: Optional[float]) -> None:
        gid, guild = state.game_id, state.guild_id
        if state.status == C.STARTING:  # 2: REL-8
            await self._abort_start(state)
            await self._tell(guild, "rel.starting_cancelled")
            return
        if state.status == C.ENDED:  # the final events first, then resume the archive from its recorded state (ARC-10)
            try:
                await self._render_pending(guild)
            except Exception as exc:
                if is_retryable(exc):
                    self._schedule_retry(guild)
                else:
                    raise
            job = await self.store.get_job(gid) if self.archive is not None else None
            self._spawn(self._post_game_cleanup(guild, gid, immediate=job is not None))
            return
        missing = await self._call("structures_missing", state, default=[])  # 3
        if missing:
            await self._pause_quietly(state, "structures missing")
            await self._tell(guild, "rel.structures_missing", causes=", ".join(missing))
            return
        gone = await self._call("members_missing", state, default=[])  # 4
        if gone:
            for slot in gone:
                try:
                    await self._commit(guild, K.Abandon(slot), already_locked=True)
                except Rejected:
                    pass
            await self._tell(guild, "rel.players_left", count=len(gone))
            state = self.games[guild]
        now = self._now()
        compensated = False
        if last_heartbeat is not None and state.status == C.RUNNING:  # 5: REL-6
            compensated = await self._shift_one(state, last_heartbeat, now) or compensated
            state = self.games[guild]
        try:  # 6: REL-7
            await self.presenter.apply_permissions(state, force=True)
            await self._render_pending(guild)
        except Exception as exc:
            if is_retryable(exc):
                self._schedule_retry(guild)
            else:
                raise
        await self._gap_fill(state)  # 7: REL-9
        try:  # 8: reconcile
            await self.presenter.reconcile(state)
            await self.presenter.apply_permissions(state, force=True)
        except Exception:
            log.exception("recovery reconcile failed")
        self._rearm(self.games[guild])  # 9
        state = self.games[guild]
        downtime = max(0.0, now - last_heartbeat) if last_heartbeat is not None else 0.0
        await self._tell(guild, "rel.restarted_admin", game_id=gid, time=downtime)  # REL-10
        if downtime > DOWNTIME_NOTICE_AFTER and state.status == C.RUNNING:
            await self._call("post_key", state, "town", "rel.restarted_town", default=None)

    async def _shift_one(self, state: GameState, last_heartbeat: float, now: float) -> bool:
        """shift_for_downtime for one game whose lock the caller already holds."""
        if not getattr(state.settings, "downtime_compensation", True):
            return False
        key = (state.game_id, state.phase_id, round(last_heartbeat, 3))
        if key in self._compensated:
            return False
        self._compensated.add(key)
        cap = state.phase_length if state.phase_length > 0 else float("inf")
        remaining = min(max(state.phase_ends_at - last_heartbeat, 0.0), cap)
        floor = min(60.0, state.phase_length) if state.phase_length > 0 else 60.0
        self.crash.hit("mid_shift")
        await self._commit(state.guild_id, K.ShiftDeadline(now + max(remaining, floor)), already_locked=True)
        return True

    async def _call(self, name: str, state: GameState, *args, default=None):
        """A presenter hook that fakes in older tests may not have."""
        fn = getattr(self.presenter, name, None)
        return default if fn is None else await fn(state, *args)

    async def _pause_quietly(self, state: GameState, reason: str) -> None:
        """Pause without touching Discord (its channels may be gone)."""
        try:
            paused = handle(state, K.Pause(reason), self._now()).state
        except Exception:
            paused = state
            paused.status = C.PAUSED
        self.games[state.guild_id] = paused
        self.scheduler.cancel(state.game_id)
        await self.store.save_game(paused)

    async def _gap_fill(self, state: GameState) -> None:
        """REL-9: fetch what was said in the game channels while the bot was offline into chat_log
        (backfilled=1). If a prisoner exists, tell the Jail and the Jailor what could not be relayed."""
        fetch = getattr(self.presenter, "fetch_history_after", None)
        if fetch is None or self.archive is None:
            return
        jail_rows: list = []
        for kind in ("town", "mafia", "jail", "graveyard"):
            try:
                after = await self.store.last_chat_message_id(state.game_id, kind)
                rows = await fetch(state, kind, after)
            except Exception:
                log.exception("chat gap-fill failed for %s", kind)
                continue
            out = []
            for r in rows:
                slot = state.slot_of_user(r["author_user_id"]) if r.get("author_user_id") else None
                out.append({**r, "game_id": state.game_id, "channel_kind": kind, "backfilled": True,
                            "session": session_for(kind, state.night_number), "author_slot": slot,
                            "author_name": (state.players[slot].display_name if slot is not None else r.get("author_name"))})
            if out:
                await self.store.add_chat_rows(out)
            if kind == "jail":
                jail_rows = [r for r in out if r["kind"] == "msg" and r.get("author_slot") is not None]
        if state.prisoner_slot is not None and state.status == C.RUNNING:
            await self._call("jail_gap", state, jail_rows, default=None)

    async def light_pass(self) -> None:
        """After a long gateway outage (REL-13): only permissions and render retries, never the full recovery."""
        for guild_id, state in list(self.games.items()):
            if state.status in (C.RUNNING, C.PAUSED):
                try:
                    await self.presenter.apply_permissions(state, force=True)
                    await self._render_pending(guild_id)
                except Exception as exc:
                    if is_retryable(exc):
                        self._schedule_retry(guild_id)
                    else:
                        log.exception("light recovery pass failed")

    # ---------------------------------------------------------------- shutdown (REL-12)
    async def shutdown(self, wait: float = 10.0) -> None:
        """Stop accepting commands, wait for in-flight locks, cancel timers, tell Town Centre. The caller flushes the
        chat queue and marks the clean exit. A crash skips all this; recovery covers it (F1 to F6)."""
        self._closing = True
        for lock in list(self._locks.values()):
            try:
                await asyncio.wait_for(lock.acquire(), wait)
                lock.release()
            except asyncio.TimeoutError:
                log.warning("a command was still running at shutdown")
        for state in list(self.games.values()):
            self.scheduler.cancel(state.game_id)
            if state.status == C.RUNNING:
                await self._call("post_key", state, "town", "rel.shutdown_notice", default=None)

    # ---------------------------------------------------------------- misc
    async def resend_prompts(self, guild_id: int, user_id: int) -> int:
        state = self.games.get(guild_id)
        if state is None:
            raise Rejected("error.no_game")
        slot = state.slot_of_user(user_id)
        if slot is None:
            raise Rejected("error.not_in_game")
        events = [prompt_event(state, state.players[slot], p) for p in prompts_for(state, slot)]
        if not events:
            raise Rejected("error.nothing_to_do")
        await self.presenter.render(state, events, None)  # a resend is not an event of the log: no outbox
        return len(events)

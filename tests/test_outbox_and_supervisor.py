"""REL-17 (ordered writer) and REL-11 (supervisor)."""
import asyncio
import signal

from monke.service.outbox import GuildWriter, OutboxCtx, Retryable, is_retryable
from monke.supervisor import child_command, supervise


def run(c):
    return asyncio.run(c)


def test_lower_priorities_run_first_and_p3_edits_are_coalesced():
    async def go():
        w, order = GuildWriter(), []

        def job(name):
            async def f():
                order.append(name)
            return f
        gate = asyncio.Event()

        async def hold():
            await gate.wait()
        first = asyncio.create_task(w.run(GuildWriter.P1, hold))  # keeps the worker busy
        await asyncio.sleep(0)
        t = [asyncio.create_task(w.run(p, job(n), key=k)) for p, n, k in (
            (GuildWriter.P3, "edit1", "banner"), (GuildWriter.P1, "announce", None), (GuildWriter.P0, "perms", None),
            (GuildWriter.P3, "edit2", "banner"))]
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(first, *t)
        assert order == ["perms", "announce", "edit2"]  # P0 before P1; the older P3 edit was dropped
    run(go())


def test_at_most_five_dms_in_flight():
    async def go():
        w = GuildWriter()

        async def dm():
            await asyncio.sleep(0.01)
        await asyncio.gather(*[w.run(GuildWriter.P2, dm) for _ in range(20)])
        assert 1 < w.max_dm_in_flight <= 5
    run(go())


def test_an_exception_in_a_write_reaches_the_caller():
    async def go():
        w = GuildWriter()

        async def bad():
            raise Retryable("down")
        try:
            await w.run(GuildWriter.P1, bad)
        except Retryable:
            return True
    assert run(go())


def test_retryable_classification():
    import discord

    class R:
        def __init__(self, status): self.status, self.reason = status, ""
    assert is_retryable(discord.HTTPException(R(503), "x")) and is_retryable(discord.HTTPException(R(429), "x"))
    assert not is_retryable(discord.Forbidden(R(403), "x")) and not is_retryable(discord.NotFound(R(404), "x"))
    assert is_retryable(asyncio.TimeoutError()) and not is_retryable(ValueError())


def test_the_outbox_skips_what_was_already_sent():
    async def go():
        class S:
            def __init__(self): self.rows = []
            async def outbox_add(self, *a): self.rows.append(a)
        st, sent = S(), []
        ctx = OutboxCtx(st, "g", 5, {(0, "town"): 1}, None)

        async def send():
            sent.append(1)
            return None
        await ctx.once("town", send)  # part 0 already done
        await ctx.once("town", send)  # part 1 is new
        assert len(sent) == 1 and st.rows[0][:3] == ("g", 5, 1)
    run(go())


class FakeProc:
    def __init__(self, codes):
        self.codes = codes

    def wait(self, timeout=None):
        c = self.codes.pop(0)
        if c == "interrupt":
            raise KeyboardInterrupt
        return c

    def send_signal(self, s): self.signalled = s
    def kill(self): ...


def sup(codes, times=None, **kw):
    out, sleeps = [], []
    procs = [FakeProc(["interrupt", 0] if c == "interrupt" else [c]) for c in codes]
    clock = iter(times) if times else iter(range(0, 10_000, 1))
    rc = supervise(["x"], popen=lambda cmd: procs.pop(0), sleep=sleeps.append, clock=lambda: next(clock), out=out.append, **kw)
    return rc, sleeps, out


def test_supervisor_restarts_with_doubling_backoff_and_stops_on_exit_zero():
    rc, sleeps, out = sup([1, 1, 1, 0])
    assert rc == 0 and sleeps == [1, 2, 4]


def test_supervisor_gives_up_after_five_crashes_in_five_minutes():
    rc, sleeps, out = sup([1] * 5)
    assert rc == 1 and len(sleeps) == 4 and "giving up" in out[-1]


def test_supervisor_backoff_resets_after_stability_and_caps_at_sixty():
    # each run lasts 400 s of fake time: stable, so the back-off never grows
    times = []
    for i in range(3):
        times += [i * 1000, i * 1000 + 400]
    rc, sleeps, _ = sup([1, 1, 0], times=times + [9999] * 4)
    assert sleeps == [1, 1]
    rc, sleeps, _ = sup([1] * 4 + [0], max_crashes=99)
    assert sleeps == [1, 2, 4, 8]
    rc, sleeps, _ = sup([1] * 9 + [0], window=0.0001, max_crashes=99)
    assert max(sleeps) == 60


def test_ctrl_c_is_forwarded_and_ends_supervision():
    rc, sleeps, _ = sup(["interrupt", 0])
    assert rc == 0 and sleeps == []


def test_child_command_drops_the_supervise_flag():
    cmd = child_command(["--supervise", "--debug"])
    assert cmd[1:] == ["-m", "monke", "--debug"]

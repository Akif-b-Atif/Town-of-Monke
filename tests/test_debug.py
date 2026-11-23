"""DBG-8: golden console output for one scripted game, human chat prints only a length line, and nothing is
printed with debug off."""
import io
import os
import pathlib

from monke import constants as C
from monke.debug import BANNER, ConsoleSink, NullSink, make_sink
from monke.sim.cli import run_game

GOLDEN = pathlib.Path(__file__).parent / "golden" / "debug_game.txt"


def _console(seed=7, n=6):
    out = io.StringIO()
    sink = ConsoleSink(out=out, color=False)
    run_game(seed, n, sink)
    return out.getvalue()


def _mask(text: str) -> str:
    """The golden file pins the console's structure: columns, tags, phases, who receives what. The words of a message
    belong to flavour.yaml (tested in test_text.py), so a text edit must not break this test."""
    import re
    return re.sub(r"^(.*? (?:DM|POST|PROMPT) .*?)'.*'$", r"\1'...'", text, flags=re.M)


def test_golden_console_output_for_a_scripted_game():
    text = _console()
    if os.environ.get("UPDATE_GOLDEN") or not GOLDEN.exists():
        GOLDEN.write_text(text, encoding="utf-8")
    assert _mask(text) == _mask(GOLDEN.read_text(encoding="utf-8"))


def test_every_line_has_the_fixed_columns_and_a_known_tag():
    from monke.debug import TAGS
    for line in _console(3, 7).splitlines():
        parts = line.split(" ")
        assert len(parts[0]) == 8 and parts[0][2] == ":"  # HH:MM:SS
        assert any(t in parts for t in TAGS), line


def test_the_console_shows_roles_and_private_text_but_names_people_the_same_way_everywhere():
    text = _console()
    assert "#05 Sim6 (Jailor)" in text  # '#04 Sam (Godfather)' style
    assert " DM " in text and " PROMPT " in text and " TRACE " in text and " DEATH " in text


def test_human_chat_prints_only_its_length():
    out = io.StringIO()
    sink = ConsoleSink(out=out, color=False, clock=lambda: 0)
    sink.chat(None, "mafia", 4, "Sam", "we kill the Doctor tonight")
    assert "CHAT #04 Sam in mafia (26 chars)" in out.getvalue()
    assert "Doctor" not in out.getvalue()


def test_debug_chat_flag_prints_the_text():
    out = io.StringIO()
    ConsoleSink(out=out, color=False, clock=lambda: 0, chat=True).chat(None, "town", 2, "Ali", "hello")
    assert "CHAT #02 Ali in town: hello" in out.getvalue()


def test_debug_off_prints_nothing(capsys):
    sink = make_sink(False)
    assert isinstance(sink, NullSink) and not sink.enabled
    run_game(5, 6, sink)
    assert capsys.readouterr().out == ""


def test_banner_and_file_output(tmp_path, capsys):
    f = tmp_path / "debug.log"
    sink = make_sink(True, str(f))
    run_game(5, 5, sink)
    assert capsys.readouterr().out.startswith(BANNER)
    written = f.read_text(encoding="utf-8")
    assert BANNER in written and " GAME " in written


def test_no_colour_when_not_a_terminal():
    out = io.StringIO()
    ConsoleSink(out=out).emit("GAME", "x", None, "-", 0)
    assert "\x1b[" not in out.getvalue()


def test_the_service_and_presenter_hooks_print_commands_and_exact_delivered_text():
    """DBG-6: the commit hook prints commands and outcomes; the presenter hooks print each DM and post."""
    import asyncio

    from monke.adapter.renderer import DiscordPresenter
    from monke.engine import Settings
    from monke.engine import commands as K
    from monke.errors import Rejected
    from monke.service.game_service import GameService
    from monke.service.store import Store
    import tempfile
    import pytest

    class Pres:
        async def assign_slot_roles(self, s): pass
        async def remove_slot_roles(self, s): pass
        async def send_role_dms(self, s, e): return []
        async def apply_permissions(self, s, force=False): pass
        async def render(self, s, e, outbox=None): pass
        async def reconcile(self, s): pass
        async def cleanup(self, s): pass
        async def notify_admin(self, g, t): pass

    async def go():
        out = io.StringIO()
        sink = ConsoleSink(out=out, color=False)
        store = Store(tempfile.mktemp(suffix=".db"))
        await store.open()
        try:
            svc = GameService(store, Pres(), sink=sink)
            st = await svc.start_game(1, [11, 12, 13, 14, 15], ["Jailor", "Godfather", "TI", "TP", "MK"], Settings(),
                                      seed=5, names={11: "A", 12: "B", 13: "C", 14: "D", 15: "E"})
            with pytest.raises(Rejected):
                await svc.submit(1, K.Vote(1, 2))  # not Noon
            svc.scheduler.cancel(st.game_id)
        finally:
            await store.close()
        text = out.getvalue()
        assert " GAME start seed=5" in text and " PHASE " in text and "REJECTED" in text

        # the presenter hooks print exactly what was delivered, with the recipient
        pres = DiscordPresenter(bot=None, store=None)
        sink2 = ConsoleSink(out=io.StringIO(), color=False)
        sink2.bind(svc)
        pres.sink = sink2

        class U:
            async def send(self, **kw): pass

        class B:
            def get_user(self, uid): return U()
        pres.bot = B()
        await pres._dm(st.players[1].user_id, content="Your target was attacked!")
        assert "DM " in sink2.out.getvalue() and "<- 'Your target was attacked!'" in sink2.out.getvalue()

    asyncio.run(go())

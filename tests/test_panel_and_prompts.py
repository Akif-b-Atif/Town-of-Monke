"""CMD-5 (vote panel) and QOL-8 (prompt hygiene) in the presenter, with fake Discord messages."""
import asyncio
from types import SimpleNamespace

from monke import constants as C
from monke.adapter.renderer import DiscordPresenter
from monke.compose import Composer
from monke.engine import Settings, handle, new_game
from monke.engine import commands as K
from monke.text.bank import default_bank
from tests.crashworld import NAMES, TOKENS, USERS


def noon_state():
    s, _ = new_game("g", 1, USERS, TOKENS, Settings(), 5, names=NAMES)
    s = handle(s, K.BeginGame(), 0).state
    res = None
    for t in (1, 2, 3):
        res = handle(s, K.AdvancePhase(s.phase_id, force=True), t)
        s = res.state
    return s, res.events


class Msg:
    def __init__(self):
        self.edits = []

    async def edit(self, **kw):
        self.edits.append(kw)


def presenter(state):
    pres = DiscordPresenter(bot=SimpleNamespace(service=SimpleNamespace(get=lambda gid: state)), store=None)
    pres.PANEL_DEBOUNCE = 0.0
    return pres


def test_noon_posts_a_banner_and_a_vote_panel_with_every_living_player():
    s, ev = noon_state()
    c = Composer(default_bank(), fixed=True)
    changed = next(e for e in ev if e.type == "PhaseChanged")
    msgs = c.compose(s, changed)
    assert [m.effect for m in msgs] == ["banner", "panel"]
    panel = msgs[1]
    assert panel.view[0] == "panel" and set(panel.view[3]) == set(s.alive_slots())
    assert "Votes" in panel.embed["title"]


def test_the_panel_tally_is_edited_once_however_many_votes_arrive():
    async def go():
        s, _ = noon_state()
        pres = presenter(s)
        panel = Msg()
        pres._panels[s.game_id] = (s.phase_id, panel)
        for _ in range(5):
            pres._schedule_panel_refresh(s)
        await asyncio.sleep(0.05)
        assert len(panel.edits) == 1 and "embed" in panel.edits[0]
    asyncio.run(go())


def test_changing_phase_closes_the_panel_and_expires_stale_prompts_only():
    async def go():
        s, _ = noon_state()
        pres = presenter(s)
        panel, old, fresh = Msg(), Msg(), Msg()
        pres._panels[s.game_id] = (s.phase_id - 1, panel)  # a panel from an earlier phase
        pres._prompts[s.game_id] = [
            {"token": "n1", "kind": C.KIND_NIGHT, "message": old, "label": "Heal someone"},  # last night's prompt
            {"token": s.token_for(C.KIND_DAY), "kind": C.KIND_DAY, "message": fresh, "label": "Choose who to jail"}]
        await pres._after_phase(s)
        assert panel.edits and panel.edits[0]["view"] is None  # closed
        assert old.edits and "Heal someone" in old.edits[0]["content"] and old.edits[0]["view"] is None
        assert not fresh.edits  # today's prompt is still live
        assert len(pres._prompts[s.game_id]) == 1
    asyncio.run(go())


def test_a_failure_while_expiring_is_ignored():
    async def go():
        s, _ = noon_state()
        pres = presenter(s)

        class Broken:
            async def edit(self, **kw):
                raise RuntimeError("gone")
        pres._prompts[s.game_id] = [{"token": "n0", "kind": C.KIND_NIGHT, "message": Broken(), "label": "x"}]
        await pres._after_phase(s)  # must not raise
        assert pres._prompts[s.game_id] == []
    asyncio.run(go())

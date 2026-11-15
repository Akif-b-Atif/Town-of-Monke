"""XC-2 to XC-4: send_logged splits long text and long embeds, caps embeds per message, never pings."""
import asyncio

import discord

from monke.adapter.renderer import DiscordPresenter


class _Msg:
    def __init__(self, kw):
        self.kw = kw


class _Chan:
    def __init__(self):
        self.sent = []

    async def send(self, **kw):
        m = _Msg(kw)
        self.sent.append(m)
        return m


class _Session:
    guild_id = 1


def _presenter():
    p = DiscordPresenter(bot=None, store=None)
    chans = {}

    async def _channel(gid, key):
        return chans.setdefault(key, _Chan())

    p._channel = _channel
    return p, chans


def test_long_text_and_embeds_are_split():
    async def go():
        p, chans = _presenter()
        text = "\n".join("line %04d " % i + "x" * 90 for i in range(60))
        embeds = [discord.Embed(title=f"e{i}", description="d") for i in range(12)]
        big = discord.Embed(title="big", description="\n".join("row %05d " % i + "y" * 40 for i in range(300)))
        view = object()
        await p.send_logged("town", text, embeds + [big], None, session=_Session())
        return text, chans["town"].sent

    text, msgs = asyncio.run(go())
    assert all(len(m.kw.get("content", "")) <= 2000 for m in msgs)
    assert "\n".join(m.kw["content"] for m in msgs if "content" in m.kw) == text
    assert all(len(m.kw.get("embeds", [])) <= 10 for m in msgs)
    pieces = [e for m in msgs for e in m.kw.get("embeds", [])]
    assert all(len(e.description or "") <= 4096 for e in pieces)
    assert "".join(e.description for e in pieces if e.title in (None, "big")).count("row") == 300
    assert all(m.kw["allowed_mentions"].users is False for m in msgs)  # XC-3


def test_mentions_only_when_asked_and_only_game_channels():
    async def go():
        p, chans = _presenter()
        await p.send_logged("graveyard", "hi", session=_Session(), mentions=True)
        refused = False
        try:
            await p.send_logged("commands", "x", session=_Session())
        except ValueError:
            refused = True
        return chans["graveyard"].sent[0].kw["allowed_mentions"].users, refused

    users, refused = asyncio.run(go())
    assert users is True and refused is True

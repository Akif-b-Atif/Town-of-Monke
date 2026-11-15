"""ARC-3: which Discord events become chat_log rows, and which never do."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from monke import constants as C
from monke.adapter.chatlog import ChatLogger, flatten_embed, flatten_post
from monke.engine import Settings, handle, new_game
from monke.engine import commands as K

NAMES = {1: "Maya", 2: "Sam", 3: "Lee", 4: "Noor", 5: "Omar"}
CFG = SimpleNamespace(town_id=10, mafia_id=11, jail_id=12, graveyard_id=13)


class _Capture:
    def __init__(self): self.rows, self.closed = [], set()
    def put(self, row): self.rows.append(row)
    def is_closed(self, gid): return gid in self.closed


def _setup(night=2):
    s, _ = new_game("g1", 1, [1, 2, 3, 4, 5], ["Jailor", "Godfather", "TI", "TP", "MK"], Settings(), 5, names=NAMES)
    s = handle(s, K.BeginGame(), 0.0).state
    s.night_number = night

    async def get_config(gid): return CFG

    bot = SimpleNamespace(service=SimpleNamespace(get=lambda gid: s if gid == 1 else None),
                          store=SimpleNamespace(get_config=get_config), capture=_Capture())
    return s, bot, ChatLogger(bot)


def _msg(channel_id, user_id=1, content="hi", bot=False, guild=1):
    return SimpleNamespace(
        guild=SimpleNamespace(id=guild) if guild else None, channel=SimpleNamespace(id=channel_id),
        author=SimpleNamespace(id=user_id, bot=bot, display_name="Whoever"), content=content, id=555,
        attachments=[SimpleNamespace(filename="a.png", size=3, url="u")],
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))


def test_human_message_in_a_game_channel_is_logged_with_slot_and_name():
    s, bot, log = _setup()
    asyncio.run(log.on_message(_msg(10, user_id=1, content="hello")))
    (row,) = bot.capture.rows
    assert row["channel_kind"] == "town" and row["kind"] == "msg" and row["content"] == "hello"
    assert row["author_slot"] == s.slot_of_user(1) and row["author_name"] == "Maya"
    assert row["ts_ms"] == int(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp() * 1000)
    assert row["attachments"][0]["filename"] == "a.png" and row["session"] == ""


def test_jail_messages_get_a_night_session():
    s, bot, log = _setup(night=2)
    asyncio.run(log.on_message(_msg(12)))
    assert bot.capture.rows[0]["session"] == "night_2"


def test_dms_bots_other_channels_and_sealed_games_are_never_logged():
    s, bot, log = _setup()
    asyncio.run(log.on_message(_msg(10, guild=None)))            # a DM
    asyncio.run(log.on_message(_msg(10, bot=True)))              # another bot
    asyncio.run(log.on_message(_msg(99)))                        # not a game channel
    bot.capture.closed.add(s.game_id)
    asyncio.run(log.on_message(_msg(10)))                        # the archive has locked this game
    assert bot.capture.rows == []


def test_non_players_are_logged_without_a_slot():
    s, bot, log = _setup()
    asyncio.run(log.on_message(_msg(10, user_id=999)))
    row = bot.capture.rows[0]
    assert row["author_slot"] is None and row["author_name"] == "Whoever"


def test_edits_and_deletes():
    s, bot, log = _setup()
    asyncio.run(log.on_raw_edit(SimpleNamespace(guild_id=1, channel_id=10, message_id=7,
                                                data={"content": "new text", "edited_timestamp": "2026-01-02T03:04:06+00:00"})))
    asyncio.run(log.on_raw_delete(SimpleNamespace(guild_id=1, channel_id=10, message_id=7)))
    asyncio.run(log.on_raw_edit(SimpleNamespace(guild_id=1, channel_id=10, message_id=8, data={"embeds": []})))  # no text
    kinds = [r["kind"] for r in bot.capture.rows]
    assert kinds == ["edit", "delete"] and bot.capture.rows[0]["content"] == "new text"
    assert all(r["message_id"] == 7 for r in bot.capture.rows)


def test_bot_posts_flatten_embeds_and_the_jailor_is_logged_under_their_slot():
    s, bot, log = _setup()
    emb = SimpleNamespace(title="Verdict", description="2 guilty", fields=[("Role list", "Jailor")], footer=None)
    assert flatten_embed(emb) == "Verdict\n2 guilty\nRole list: Jailor"
    assert flatten_post("hi", [emb]).startswith("hi\nVerdict")
    log.log_bot(s, "town", "hello", [emb], SimpleNamespace(id=9, created_at=None))
    asyncio.run(log.log_jailor(s, "tell me the truth", 123))
    bot_row, jail_row = bot.capture.rows
    assert bot_row["kind"] == "bot" and "2 guilty" in bot_row["content"]
    jailor = next(p for p in s.players.values() if p.role_id == "jailor")
    assert jail_row["channel_kind"] == "jail" and jail_row["author_slot"] == jailor.slot
    assert jail_row["session"] == "night_2" and jail_row["content"] == "tell me the truth"
